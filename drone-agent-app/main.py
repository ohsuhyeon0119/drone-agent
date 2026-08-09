"""
동행이 — 노인 돌봄 드론 에이전트 PoC.

/ (=/unified) 하나의 페이지·하나의 WebSocket 세션(/ws/unified)에서 낙상 감지와
복약 확인을 동시에 처리한다. 두 감지기 모두 "감지 → 판단 → 넛지" 파이프라인
(detection_graph.py, LangGraph로 구현)을 프롬프트·타겟이벤트·쿨다운만 다르게
넣어서 공유하고, 감지되면 nudge_input_queue를 통해 Gemini Live(gemini_live.py)에
강제로 턴을 발생시켜 스스로 먼저 말을 걸게 만든다.

영상·오디오 입력은 기본적으로 브라우저 getUserMedia를 쓰지만, PHONE_STREAM_URL이
설정돼 있으면 phone-stream 서버(폰 카메라/마이크)가 송출 중일 때 그쪽을 우선
사용하고 아니면 브라우저로 자동 폴백한다 (_pump_phone_stream, _phone_is_active).
"""

import asyncio
import base64
import json
import logging
import os
import time

from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import accounts
import admin_store
import live_monitor
import memory
from admin_api import router as admin_router
from agent.persona import build_nudge, build_unified_persona
from agent.scenarios import load_scenarios
from agent.summarizer import summarize
from agent.tools import build_tool_mapping, build_tools
from detection_graph import detection_graph
from gemini_live import GeminiLive

load_dotenv()

logging.basicConfig(level=logging.INFO)
logging.getLogger("gemini_live").setLevel(logging.INFO)
logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("MODEL", "gemini-3.1-flash-live-preview")

# 폰 스트림 소스 (phone-stream 서버, 예: http://localhost:8080)
# 설정하면 폰(드론 카메라)이 송출 중일 때 그 영상·오디오가 모델 입력이 되고,
# 송출이 없으면 자동으로 브라우저 웹캠/마이크로 폴백한다 (스마트 전환).
# 비우면 항상 브라우저 getUserMedia만 사용.
PHONE_STREAM_URL = os.getenv("PHONE_STREAM_URL", "").strip().rstrip("/")
# Gemini Live에 넣는 영상은 기존 브라우저 경로와 동일하게 ~1fps로 제한
# (frame_buffer는 매 프레임 갱신 — 감지 VLM은 항상 최신 프레임을 본다)
PHONE_VIDEO_TO_GEMINI_INTERVAL = 1.0
# 폰 패킷이 이 시간(초) 안에 들어왔으면 "폰 송출 중"으로 보고 브라우저 입력을 무시
PHONE_ACTIVE_WINDOW = 3.0

# 기기는 관전 화면이 부드럽도록 초당 여러 장을 보내지만, 모델에 넣는 것은
# 이 간격으로 솎아낸다 — 판단이 나아지지 않으면서 토큰만 늘어나기 때문이다.
MODEL_FRAME_INTERVAL = 1.0

# 페르소나(agent/persona.py)와 tool 정의(agent/tools.py)는 agent/ 아래로 분리했다.

async def _record_medication_on_detect(websocket, result):
    """카메라가 복용을 확인하면 모델을 거치지 않고 바로 기록한다."""
    record = memory.record_medication_taken(note=result.get("reason", ""))
    admin_store.log_event("medication_recorded", {"source": "vision", "record": record})
    await websocket.send_json({
        "type": "memory_update", "record": record,
        "message": f"✅ {record['timestamp']} — {record['medication']} 복용 확인, 메모리 업데이트됨",
    })


# 감지되면 코드가 직접 하는 일. 시나리오 키별로만 있고, 없으면 넛지만 나간다.
_ON_DETECT_SIDE_EFFECTS = {"medication": _record_medication_on_detect}

# 현재 연결된 /ws/unified 세션 핸들 — "약 복용 알림" 버튼이 여기로 넛지를 주입한다.
_active_unified_session = {"queue": None, "websocket": None}

# ──────────────────────────────────────────────────────────────
# FastAPI 앱
# ──────────────────────────────────────────────────────────────
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/agent-static", StaticFiles(directory="agent/static"), name="agent-static")

# 관리 화면(보호자용 콘솔)의 빌드 산출물. 빌드본이 없는 개발 환경에서는 콘솔을
# Vite(5173)로 따로 띄우므로, 없으면 조용히 건너뛴다.
CONSOLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "console")
CONSOLE_INDEX = os.path.join(CONSOLE_DIR, "index.html")
HAS_CONSOLE = os.path.isfile(CONSOLE_INDEX)
if HAS_CONSOLE:
    app.mount("/assets", StaticFiles(directory=os.path.join(CONSOLE_DIR, "assets")),
              name="console-assets")


@app.middleware("http")
async def _no_cache_static(request, call_next):
    """CSS/JS를 고쳐도 브라우저가 예전 것을 계속 쓰는 문제를 막는다.
    (화면을 다듬는 동안 '왜 안 바뀌지'로 시간을 버리지 않기 위함)"""
    response = await call_next(request)
    if request.url.path.startswith(("/static/", "/agent-static/")):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response

# 관리 콘솔(보호자용) API — 설정 버전 관리 저장소는 data/console.db (admin_store.py)
admin_store.init_db()
accounts.init_db()
app.include_router(admin_router)


@app.get("/")
async def root():
    """루트는 보호자용 관리 화면이다.

    이 주소로 들어오는 사람은 설정을 하러 오는 보호자다. 어르신은 폰 앱이나
    드론으로 붙지 주소를 치지 않는다. 어르신과 대화하는 화면은 /unified에 둔다.
    """
    return FileResponse(CONSOLE_INDEX if HAS_CONSOLE else "static/unified.html")


@app.get("/unified")
async def unified_page():
    return FileResponse("static/unified.html")


@app.get("/api/medication/state")
async def medication_state():
    """대시보드가 새로고침 시에도 지금까지의 메모리 기록을 볼 수 있게 하는 조회용 엔드포인트."""
    return {"profile": memory.get_profile(), "logs": memory.get_logs()}


@app.post("/api/pair")
async def pair_device(code: str = Body(..., embed=True)):
    """어르신 폰이 6자 코드를 신원으로 바꿔 가는 곳.

    보호자는 이메일·비밀번호로 로그인하지만 어르신에게 그걸 시킬 수는 없다.
    코드 하나를 넣으면 그 에이전트에 묶인 기기 토큰을 받아, 이후 연결마다
    "내가 누구의 곁에 있는지"를 서버에 증명한다.
    """
    found = admin_store.agent_by_pair_code(code)
    if not found:
        raise HTTPException(status_code=404, detail="코드를 찾을 수 없습니다.")

    agent_id = found["agent_id"]
    profile = admin_store.get_profile(agent_id)
    admin_store.log_event("device_paired", {"agent_id": agent_id}, agent_id=agent_id)
    return {
        "ok": True,
        "token": accounts.make_device_token(agent_id),
        "agent_id": agent_id,
        "agent_name": found["agent_name"],
        "elder_name": profile.get("name") or "",
    }


@app.post("/api/remind-medication")
async def remind_medication():
    """"약 복용 알림" 버튼(프론트에서 5초 카운트다운 후 호출)이 여기로 들어온다.

    현재 연결된 /ws/unified 세션에 복약 안내 넛지를 주입해 동행이가 먼저 말을
    걸게 만든다. 연결된 세션이 없으면 에러를 돌려준다.
    """
    queue = _active_unified_session["queue"]
    ws = _active_unified_session["websocket"]
    if queue is None:
        return {"ok": False, "error": "연결된 세션이 없습니다. 먼저 대화를 시작하세요."}

    profile = memory.get_profile()
    nudge = (
        f"[SYSTEM] 지금은 {profile['scheduled_time']}입니다. {profile['name']}님께 지난번에 "
        f"처방받으신 {profile['medication']}을 드셔야 한다고 먼저 다정하게 말을 거세요."
    )
    if ws is not None:
        await ws.send_json({"type": "system_nudge", "text": nudge})
    await queue.put(nudge)
    logger.info("[/api/remind-medication] 복약 알림 넛지 주입됨")
    return {"ok": True}


@app.post("/api/scenarios/reload")
async def reload_scenarios():
    """agent/scenarios/*.yaml을 고친 뒤 누르는 "적용" 버튼이 여기로 들어온다.

    Gemini Live는 세션 시작 시점에만 persona/tool을 고정할 수 있어서, 이미
    떠 있는 세션의 내용 자체를 바꿔치기할 수는 없다. 대신 현재 연결된 세션이
    있으면 끊어서 재연결을 유도한다 — /ws/unified는 매 연결마다 yaml을 새로
    읽으므로(main.py의 ws_unified 참고), 다시 "대화 시작"을 누르는 순간부터
    새 지침이 반영된다. 연결된 세션이 없으면 어차피 다음 연결부터 바로
    반영되니 그대로 안내만 한다.
    """
    ws = _active_unified_session["websocket"]
    if ws is None:
        return {"ok": True, "closed_session": False, "message": "연결된 세션이 없습니다. 새로 대화를 시작하면 바로 반영됩니다."}

    # await로 기다리지 않는다 — 다른 요청(이 HTTP 요청) 핸들러에서 websocket을
    # 닫으면 uvicorn이 종료 핸드셰이크를 정리하는 데 수십 초가 걸릴 수 있는데,
    # 이 버튼은 그 정리가 끝나길 기다릴 필요 없이 "닫으라고 지시했다"만 즉시
    # 응답하면 된다. 실제 정리/재연결 허용은 백그라운드에서 진행된다.
    asyncio.create_task(ws.close())
    logger.info("[/api/scenarios/reload] 지침 갱신을 위해 활성 세션 종료를 요청함")
    return {"ok": True, "closed_session": True, "message": "현재 세션을 종료했습니다. 다시 '대화 시작'을 누르면 새 지침이 적용됩니다."}


# ──────────────────────────────────────────────────────────────
# 공통 웹소켓 보일러플레이트
# ──────────────────────────────────────────────────────────────
async def _run_gemini_session(
    websocket: WebSocket,
    gemini_client: GeminiLive,
    audio_input_queue,
    video_input_queue,
    text_input_queue,
    nudge_input_queue,
    transcript: list | None = None,
):
    async def audio_output_callback(data):
        await websocket.send_bytes(data)

    async def audio_interrupt_callback():
        pass

    # 전사는 조각으로 흘러온다 — 같은 화자의 조각을 이어 붙여 한 발화로 모은다.
    # (조각 단위로 저장하면 초당 여러 건이 쌓여 요약에도 방해가 된다)
    def collect(event: dict):
        if transcript is None:
            return
        role = {"user": "user", "gemini": "agent"}.get(event.get("type"))
        text = event.get("text")
        if not role or not text:
            return
        if transcript and transcript[-1]["role"] == role:
            transcript[-1]["text"] += text
        else:
            transcript.append({"role": role, "text": text})

    async for event in gemini_client.start_session(
        audio_input_queue=audio_input_queue,
        video_input_queue=video_input_queue,
        text_input_queue=text_input_queue,
        audio_output_callback=audio_output_callback,
        audio_interrupt_callback=audio_interrupt_callback,
        nudge_input_queue=nudge_input_queue,
    ):
        if event:
            collect(event)
            await websocket.send_json(event)


def _phone_is_active(phone_active: dict | None) -> bool:
    """폰(드론 카메라)이 최근 PHONE_ACTIVE_WINDOW초 안에 패킷을 보냈는지."""
    return (
        phone_active is not None
        and time.monotonic() - phone_active["last"] < PHONE_ACTIVE_WINDOW
    )


async def _receive_from_client(websocket, audio_input_queue, video_input_queue, text_input_queue, frame_buffer,
                               phone_active=None):
    """브라우저 → 모델 입력. 폰(드론 카메라)이 송출 중일 때만 브라우저의 마이크
    오디오와 웹캠 이미지를 버리고(이중 입력 방지), 아니면 그대로 모델에 넣는다.
    텍스트 메시지는 항상 통과."""
    # 마이크가 실제로 들어오는지 세어둔다. 영상만 흐르고 대화가 안 될 때
    # "클라이언트가 안 보내는 것"과 "서버가 버리는 것"을 구분할 방법이 없었다.
    audio_chunks = 0
    audio_bytes = 0
    last_model_frame_at = 0.0
    try:
        while True:
            message = await websocket.receive()
            if message.get("bytes"):
                audio_chunks += 1
                audio_bytes += len(message["bytes"])
                if audio_chunks % 100 == 0:
                    logger.info(f"[/unified] 마이크 수신 {audio_chunks}청크 / {audio_bytes:,}바이트"
                                f"{' (폰스트림 우선이라 버리는 중)' if _phone_is_active(phone_active) else ''}")
                if not _phone_is_active(phone_active):
                    await audio_input_queue.put(message["bytes"])
            elif message.get("text"):
                text = message["text"]
                try:
                    payload = json.loads(text)
                    if isinstance(payload, dict) and payload.get("type") == "image":
                        if not _phone_is_active(phone_active):
                            image_data = base64.b64decode(payload["data"])
                            # 프레임은 두 곳에서 쓰인다. 관전 화면은 부드러워야 해서
                            # 들어오는 대로 전부 받고, Gemini는 초당 한 장이면 충분하다
                            # (더 보내도 판단이 나아지지 않고 토큰만 늘어난다).
                            now = time.monotonic()
                            if now - last_model_frame_at >= MODEL_FRAME_INTERVAL:
                                last_model_frame_at = now
                                await video_input_queue.put(image_data)
                            if frame_buffer is not None:
                                frame_buffer["data"] = image_data
                                # 관전자가 같은 장면을 다시 받지 않도록 갱신을 표시한다
                                frame_buffer["seq"] = frame_buffer.get("seq", 0) + 1
                        continue
                except json.JSONDecodeError:
                    pass
                await text_input_queue.put(text)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"Error receiving from client: {e}")


async def _pump_phone_stream(audio_input_queue, video_input_queue, frame_buffer, phone_active):
    """phone-stream 서버의 /ws/feed에 붙어 폰의 영상('V')/오디오('A')를 모델 입력에 주입.

    패킷 포맷: [1B 'V'|'A'][8B LE float64 capture_ts_ms][payload]
      - V: JPEG → frame_buffer(감지 VLM, 매 프레임) + video_input_queue(Gemini, ~1fps 제한)
      - A: 16kHz 16bit 모노 PCM → audio_input_queue (브라우저 마이크와 동일 포맷)
    패킷이 올 때마다 phone_active["last"]를 갱신해 브라우저 입력을 잠재운다.
    끊기면 3초 간격으로 재접속한다.
    """
    import websockets

    base = PHONE_STREAM_URL
    if base.startswith("https://"):
        feed_url = "wss://" + base[len("https://"):] + "/ws/feed"
    elif base.startswith("http://"):
        feed_url = "ws://" + base[len("http://"):] + "/ws/feed"
    else:
        feed_url = base + "/ws/feed"

    last_video_to_gemini = 0.0
    while True:
        try:
            async with websockets.connect(feed_url, max_size=None) as ws:
                logger.info(f"phone-stream feed 연결됨: {feed_url}")
                async for data in ws:
                    if not isinstance(data, (bytes, bytearray)) or len(data) < 10:
                        continue
                    kind, payload = data[0:1], bytes(data[9:])
                    if kind == b"V":
                        phone_active["last"] = time.monotonic()
                        if frame_buffer is not None:
                            frame_buffer["data"] = payload
                        now = time.monotonic()
                        if now - last_video_to_gemini >= PHONE_VIDEO_TO_GEMINI_INTERVAL:
                            last_video_to_gemini = now
                            await video_input_queue.put(payload)
                    elif kind == b"A":
                        phone_active["last"] = time.monotonic()
                        await audio_input_queue.put(payload)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"phone-stream feed 끊김/실패, 3초 후 재시도: {type(e).__name__}: {e}")
        await asyncio.sleep(3)


# ──────────────────────────────────────────────────────────────
# /ws/unified — 낙상·복약·작업보조를 한 세션에서 동시에 판단
# ──────────────────────────────────────────────────────────────
@app.websocket("/ws/unified")
async def ws_unified(websocket: WebSocket):
    """세 감지기를 동시에 돌려서, 어떤 상황이든 알아서 알아채고 반응한다.

    /fall·/medication은 사람이 탭으로 시나리오를 미리 골라야 하지만, 여기서는
    detection_graph를 낙상용·복약용으로 각각 병렬 실행해 같은 nudge_input_queue에
    합류시킨다. Gemini에게는 세 시나리오를 다 아우르는 통합 페르소나(매 연결마다
    agent/scenarios/*.yaml을 새로 읽어 조립)와 notify_caregiver tool을 준다 —
    "어떤 상황인지"는 코드가 미리 정하지 않고, 그때그때 어느 감지기가 먼저
    걸리느냐로 자연스럽게 결정된다.
    """
    await websocket.accept()

    # 이 기기가 누구의 어르신 곁에 있는지 알아야 한다.
    #
    # 우선순위는 ?token= (페어링으로 발급된 기기 토큰)이다. ?agent=N은 서명이
    # 없어서 아무나 남의 번호를 적어 넣을 수 있으므로, 토큰이 있으면 그쪽만 믿는다.
    # 번호 방식은 코드 발급 이전에 만들어둔 데모 주소를 위해 남겨둔다.
    agent_id = accounts.agent_id_from_device_token(
        websocket.query_params.get("token") or ""
    )
    if agent_id is None:
        try:
            agent_id = int(websocket.query_params.get("agent") or admin_store.DEFAULT_AGENT_ID)
        except ValueError:
            agent_id = admin_store.DEFAULT_AGENT_ID
        logger.warning(f"[/unified] 서명 없는 접속 (agent={agent_id})")
    logger.info(f"[/unified] WebSocket connection accepted (agent={agent_id})")

    # 콘솔이 이 세션을 들여다볼 수 있게 이벤트를 복사해 흘린다. 감싸기만 하므로
    # 아래 코드는 평소처럼 websocket.send_json을 쓰면 된다.
    websocket = live_monitor.MirroredSocket(websocket, agent_id)

    # agent/scenarios/<agent_id>/*.yaml을 연결마다 새로 읽는다 — 서버 프로세스를
    # 재시작하지 않아도 지침을 고친 뒤 재연결하면 바로 반영되게 하기 위함.
    scenarios = load_scenarios(agent_id)

    # 행동(tool)과 연락처도 연결마다 새로 읽는다 — 콘솔에서 배포한 내용이
    # 다음 대화부터 반영되게 하기 위함. Gemini Live는 tool을 연결 시점에만
    # 고정할 수 있어서, 이미 열린 세션에는 반영할 수 없다.
    live_config = admin_store.get_live(agent_id)["config"]
    all_actions = live_config.get("actions", [])
    contacts = live_config.get("contacts", [])

    # 켜져 있는 시나리오의 지침에 붙은 행동만 이 세션에 등록한다 — 쓰지도 않을
    # 도구까지 전부 넘기면 모델이 엉뚱한 것을 고를 여지가 생긴다.
    used_action_ids = {
        x["action"]
        for sc in live_config.get("scenarios", [])
        if sc.get("enabled", True)
        for x in admin_store.normalize_instructions(sc.get("instructions"))
        if x.get("action")
    }
    actions = [a for a in all_actions if a.get("id") in used_action_ids]

    # 프로필도 매 연결마다 새로 읽는다 — 보호자가 콘솔에서 고친 사실이
    # 서버 재시작 없이 다음 대화부터 반영되게 하려는 것 (시나리오와 같은 이유).
    profile = admin_store.get_profile(agent_id)
    unified_persona = build_unified_persona(scenarios, actions, profile)

    audio_input_queue = asyncio.Queue()
    video_input_queue = asyncio.Queue()
    text_input_queue = asyncio.Queue()
    nudge_input_queue = asyncio.Queue()
    frame_buffer = {"data": None}

    async def on_tool_event(payload: dict):
        """tool이 실제로 실행됐을 때 — 활동 기록에 남기고 화면에도 보여준다."""
        admin_store.log_event("tool_call", payload)
        try:
            await websocket.send_json({"type": "tool_result", **payload})
        except Exception:
            pass  # 이미 끊긴 세션이면 기록만 남기고 넘어간다

    tool_context = {
        "contacts": contacts,
        # 연락 대상은 행동에만 둔다 (같은 값이 두 곳에 있으면 어느 쪽이 맞는지 모른다)
        "contact_ids_by_action_own": {
            a["id"]: a.get("notify_contact_ids") or [] for a in actions if a.get("id")
        },
        "on_event": on_tool_event,
    }
    tools = build_tools(actions)
    logger.info(f"[/unified] 지침이 쓰는 행동만 등록: {[a.get('id') for a in actions]} "
                f"(전체 {len(all_actions)}개 중) / 연락처 {len(contacts)}명")

    gemini_client = GeminiLive(
        api_key=GEMINI_API_KEY,
        model=GEMINI_MODEL,
        input_sample_rate=16000,
        tools=tools,
        tool_mapping=build_tool_mapping(actions, tool_context),
        system_instruction=unified_persona,
    )

    phone_active = {"last": 0.0}
    receive_task = asyncio.create_task(
        _receive_from_client(websocket, audio_input_queue, video_input_queue, text_input_queue, frame_buffer,
                             phone_active)
    )
    phone_task = asyncio.create_task(
        _pump_phone_stream(audio_input_queue, video_input_queue, frame_buffer, phone_active)
    ) if PHONE_STREAM_URL else None

    # 약 복용 알림은 자동 발화 대신 프론트의 "약 복용 알림" 버튼(5초 카운트다운
    # 후 /api/remind-medication 호출)으로 트리거한다 — 데모 중 원치 않는 타이밍에
    # 바로 말을 걸어버리는 문제를 피하기 위함.
    _active_unified_session["queue"] = nudge_input_queue
    _active_unified_session["websocket"] = websocket
    # 관전 채널은 프레임 버퍼를 참조만 한다 (복사하면 지연이 생긴다)
    live_monitor.monitor.session_started(agent_id, frame_buffer)

    async def vision_loop(scenario: dict):
        """시나리오 하나를 감시한다.

        시나리오마다 함수를 따로 두면 콘솔에서 새로 만든 시나리오가 영영 돌지
        않는다. 설정에서 온 시나리오를 그대로 받아 도는 하나의 루프로 두고,
        켜져 있고 감지 기준이 있는 것마다 이 루프를 띄운다.
        """
        key = scenario.get("key", "?")
        name = scenario.get("name", key)
        last_trigger_at = 0.0
        while True:
            await asyncio.sleep(2)
            frame = frame_buffer["data"]
            if frame is None:
                continue
            result = await detection_graph.ainvoke({
                "frame": frame,
                "prompt": scenario["detect_prompt"],
                "target_event": scenario.get("target_event", "event"),
                "cooldown": float(scenario.get("cooldown", 10.0)),
                "min_confidence": float(scenario.get("min_confidence", 0.7)),
                "last_trigger_at": last_trigger_at,
                "nudge_template": scenario.get("nudge_template", ""),
            })
            if result.get("error"):
                logger.error(f"[/unified:{key}] detect error: {result['error']}")
                await websocket.send_json({"type": "detect_result", "ok": False,
                                           "source": key, "label": name,
                                           "error": result["error"]})
                continue

            await websocket.send_json({
                "type": "detect_result", "source": key, "label": name, "ok": True,
                "event": result.get("event"), "confidence": result.get("confidence"),
                "reason": result.get("reason"),
            })
            last_trigger_at = result.get("new_last_trigger_at", last_trigger_at)

            if not result.get("should_trigger"):
                continue

            logger.info(f"[/unified:{key}] {name} 감지됨 (confidence={result.get('confidence')})")
            await websocket.send_json({
                "type": "alert", "source": key,
                "message": f"{name}! 즉시 확인이 필요합니다.",
            })

            # 감지 자체로 확정되는 부수 효과 (모델 판단을 거치지 않는 것)
            side_effect = _ON_DETECT_SIDE_EFFECTS.get(key)
            if side_effect:
                await side_effect(websocket, result)

            # 신호 문구는 여기서 만든다 — 카메라가 왜 그렇게 판단했는지(reason)를
            # 함께 넣어야 동행이가 상황에 맞게 물어볼 수 있다.
            nudge = build_nudge(scenario, result.get("reason"))
            await websocket.send_json({"type": "system_nudge", "text": nudge})
            await nudge_input_queue.put(nudge)

    # 켜져 있고 감지 기준이 있는 시나리오마다 하나씩
    vision_tasks = [
        asyncio.create_task(vision_loop(sc))
        for sc in scenarios.values()
        if sc.get("enabled", True) and str(sc.get("detect_prompt", "")).strip()
    ]
    logger.info(f"[/unified] 감시 중인 시나리오: "
                f"{[sc.get('name') for sc in scenarios.values() if sc.get('enabled', True) and sc.get('detect_prompt')]}")

    transcript: list[dict] = []

    try:
        # 브라우저가 끊겨도 Gemini 세션은 계속 살아 있어서, 그냥 await 하면 세션
        # 정리(대화 요약 저장 포함)가 실행되지 않는다. 둘 중 먼저 끝나는 쪽을 기다린다.
        session_task = asyncio.create_task(
            _run_gemini_session(websocket, gemini_client, audio_input_queue, video_input_queue,
                                text_input_queue, nudge_input_queue, transcript))
        done, _ = await asyncio.wait({session_task, receive_task},
                                     return_when=asyncio.FIRST_COMPLETED)
        session_task.cancel()
        for t in done:
            if t is session_task and t.exception():
                raise t.exception()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"[/unified] session error: {type(e).__name__}: {e}")
    finally:
        receive_task.cancel()
        for t in vision_tasks:
            t.cancel()
        if phone_task:
            phone_task.cancel()
        if _active_unified_session["queue"] is nudge_input_queue:
            _active_unified_session["queue"] = None
            _active_unified_session["websocket"] = None
        live_monitor.monitor.session_ended(agent_id)
        # 대화를 통째로 남기지 않고 요약해서 저장한다 — 특히 "요청했는데 이뤄지지
        # 않은 것". 세션 종료를 막지 않도록 별도 태스크로 돌린다.
        if transcript:
            asyncio.create_task(_save_conversation_summary(transcript))
        try:
            await websocket.close()
        except Exception:
            pass


@app.websocket("/ws/monitor")
async def ws_monitor(websocket: WebSocket):
    """관리 콘솔이 실행 중인 세션을 들여다보는 읽기 전용 채널.

    카메라가 보고 있는 화면과 그 사이 일어난 일(감지, 신호, 도구 실행, 대화)을
    그대로 흘려보낸다. 여기서 들어오는 것은 세션에 아무 영향을 주지 않는다 —
    보호자가 콘솔을 열어둔 것 때문에 어르신과의 대화가 달라지면 안 된다.

    브라우저 WebSocket은 헤더를 붙일 수 없어서 토큰을 쿼리로 받는다. 남의
    에이전트를 훔쳐보지 못하도록, 토큰의 주인이 가진 agent_id만 볼 수 있다.
    """
    token = websocket.query_params.get("token", "")
    user_id = accounts.user_id_from_token(token)
    user = accounts.get_user(user_id) if user_id else None
    if not user:
        await websocket.close(code=4401)
        return

    agent_id = user["agent_id"]
    await websocket.accept()
    queue = live_monitor.monitor.subscribe(agent_id)
    logger.info(f"[/monitor] 관전 시작 (agent={agent_id}, {user['email']})")

    try:
        # 콘솔을 나중에 열어도 직전 상황부터 보이도록 지난 기록을 먼저 준다
        await websocket.send_json({
            "type": "init",
            "status": live_monitor.monitor.status(agent_id),
            "events": live_monitor.monitor.recent(agent_id),
        })

        last_seq = -1
        while True:
            # 이벤트를 기다리되, 영상이 멈춰 보이지 않게 자주 깨어난다
            try:
                event = await asyncio.wait_for(queue.get(), timeout=0.05)
                await websocket.send_json({"type": "event", "event": event})
            except asyncio.TimeoutError:
                pass

            # 새 장면이 들어왔을 때만 보낸다. 고정 간격으로 퍼내면 기기가 더 자주
            # 보내도 화면이 그만큼 뚝뚝 끊기고, 반대로 기기가 멈춰 있으면 같은
            # 장면을 반복해서 실어 대역폭만 먹는다.
            seq = live_monitor.monitor.frame_seq(agent_id)
            if seq != last_seq:
                frame = live_monitor.monitor.frame(agent_id)
                if frame:
                    last_seq = seq
                    await websocket.send_bytes(frame)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.info(f"[/monitor] 관전 종료: {type(e).__name__}: {e}")
    finally:
        live_monitor.monitor.unsubscribe(agent_id, queue)


async def _save_conversation_summary(transcript: list[dict]):
    try:
        result = await summarize(transcript)
    except Exception as e:
        logger.error(f"[/unified] 대화 요약 실패: {type(e).__name__}: {e}")
        return
    if not result:
        return
    admin_store.log_event("conversation", result)
    unfulfilled = len(result.get("unfulfilled") or [])
    logger.info(f"[/unified] 대화 요약 저장됨 — 발화 {result['turn_count']}건, "
                f"미이행 요청 {unfulfilled}건")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8003))
    uvicorn.run(app, host="0.0.0.0", port=port)
