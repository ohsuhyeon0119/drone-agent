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
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import memory
from agent.persona import FALL_DETECT_PROMPT, MEDICATION_DETECT_PROMPT, UNIFIED_PERSONA
from agent.tools import NOTIFY_CAREGIVER_TOOL, notify_caregiver
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

# 페르소나(agent/persona.py)와 tool 정의(agent/tools.py)는 agent/ 아래로 분리했다.

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


@app.get("/")
async def root():
    return FileResponse("static/unified.html")


@app.get("/unified")
async def unified_page():
    return FileResponse("static/unified.html")


@app.get("/api/medication/state")
async def medication_state():
    """대시보드가 새로고침 시에도 지금까지의 메모리 기록을 볼 수 있게 하는 조회용 엔드포인트."""
    return {"profile": memory.get_profile(), "logs": memory.get_logs()}


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
):
    async def audio_output_callback(data):
        await websocket.send_bytes(data)

    async def audio_interrupt_callback():
        pass

    async for event in gemini_client.start_session(
        audio_input_queue=audio_input_queue,
        video_input_queue=video_input_queue,
        text_input_queue=text_input_queue,
        audio_output_callback=audio_output_callback,
        audio_interrupt_callback=audio_interrupt_callback,
        nudge_input_queue=nudge_input_queue,
    ):
        if event:
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
    try:
        while True:
            message = await websocket.receive()
            if message.get("bytes"):
                if not _phone_is_active(phone_active):
                    await audio_input_queue.put(message["bytes"])
            elif message.get("text"):
                text = message["text"]
                try:
                    payload = json.loads(text)
                    if isinstance(payload, dict) and payload.get("type") == "image":
                        if not _phone_is_active(phone_active):
                            image_data = base64.b64decode(payload["data"])
                            await video_input_queue.put(image_data)
                            if frame_buffer is not None:
                                frame_buffer["data"] = image_data
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
    합류시킨다. Gemini에게는 세 시나리오를 다 아우르는 UNIFIED_PERSONA와
    notify_caregiver tool을 준다 — "어떤 상황인지"는 코드가 미리 정하지 않고,
    그때그때 어느 감지기가 먼저 걸리느냐로 자연스럽게 결정된다.
    """
    await websocket.accept()
    logger.info("[/unified] WebSocket connection accepted")

    audio_input_queue = asyncio.Queue()
    video_input_queue = asyncio.Queue()
    text_input_queue = asyncio.Queue()
    nudge_input_queue = asyncio.Queue()
    frame_buffer = {"data": None}

    gemini_client = GeminiLive(
        api_key=GEMINI_API_KEY,
        model=GEMINI_MODEL,
        input_sample_rate=16000,
        tools=[NOTIFY_CAREGIVER_TOOL],
        tool_mapping={"notify_caregiver": notify_caregiver},
        system_instruction=UNIFIED_PERSONA,
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

    async def fall_vision_loop():
        last_trigger_at = 0.0
        while True:
            await asyncio.sleep(2)
            frame = frame_buffer["data"]
            if frame is None:
                continue
            result = await detection_graph.ainvoke({
                "frame": frame,
                "prompt": FALL_DETECT_PROMPT,
                "target_event": "fall",
                "cooldown": 10.0,
                "last_trigger_at": last_trigger_at,
                "nudge_template": (
                    "[SYSTEM] 카메라 영상에서 사용자가 방금 쓰러지는 것이 감지되었습니다. "
                    "지금 하던 대화를 멈추고 걱정스러운 톤으로 '괜찮으세요?'라고 즉시 물어보세요."
                ),
            })
            if result.get("error"):
                logger.error(f"[/unified:fall] detect error: {result['error']}")
                await websocket.send_json({"type": "detect_result", "ok": False, "source": "fall", "error": result["error"]})
                continue

            await websocket.send_json({
                "type": "detect_result", "source": "fall", "ok": True,
                "event": result.get("event"), "confidence": result.get("confidence"),
                "reason": result.get("reason"),
            })
            last_trigger_at = result.get("new_last_trigger_at", last_trigger_at)

            if result.get("should_trigger"):
                logger.info(f"[/unified:fall] Fall detected! confidence={result.get('confidence')}")
                await websocket.send_json({"type": "alert", "message": "낙상 감지! 즉시 확인이 필요합니다."})
                nudge = result["nudge_text"]
                await websocket.send_json({"type": "system_nudge", "text": nudge})
                await nudge_input_queue.put(nudge)

    async def medication_vision_loop():
        last_trigger_at = 0.0
        while True:
            await asyncio.sleep(2)
            frame = frame_buffer["data"]
            if frame is None:
                continue
            result = await detection_graph.ainvoke({
                "frame": frame,
                "prompt": MEDICATION_DETECT_PROMPT,
                "target_event": "taken",
                "cooldown": 15.0,
                "last_trigger_at": last_trigger_at,
                "nudge_template": (
                    "[SYSTEM] 방금 카메라로 사용자가 약을 복용하는 모습이 확인되었습니다. "
                    "잘하셨다고 따뜻하게 칭찬하고 격려해주세요."
                ),
            })
            if result.get("error"):
                logger.error(f"[/unified:medication] detect error: {result['error']}")
                await websocket.send_json({"type": "detect_result", "ok": False, "source": "medication", "error": result["error"]})
                continue

            await websocket.send_json({
                "type": "detect_result", "source": "medication", "ok": True,
                "event": result.get("event"), "confidence": result.get("confidence"),
                "reason": result.get("reason"),
            })
            last_trigger_at = result.get("new_last_trigger_at", last_trigger_at)

            if result.get("should_trigger"):
                record = memory.record_medication_taken(note=result.get("reason", ""))
                logger.info(f"[/unified:medication] Medication taken! record={record}")
                await websocket.send_json({
                    "type": "memory_update",
                    "record": record,
                    "message": f"✅ {record['timestamp']} — {record['medication']} 복용 확인, 메모리 업데이트됨",
                })
                nudge = result["nudge_text"]
                await websocket.send_json({"type": "system_nudge", "text": nudge})
                await nudge_input_queue.put(nudge)

    fall_task = asyncio.create_task(fall_vision_loop())
    medication_task = asyncio.create_task(medication_vision_loop())

    try:
        await _run_gemini_session(websocket, gemini_client, audio_input_queue, video_input_queue, text_input_queue, nudge_input_queue)
    except Exception as e:
        logger.error(f"[/unified] session error: {type(e).__name__}: {e}")
    finally:
        receive_task.cancel()
        fall_task.cancel()
        medication_task.cancel()
        if phone_task:
            phone_task.cancel()
        if _active_unified_session["queue"] is nudge_input_queue:
            _active_unified_session["queue"] = None
            _active_unified_session["websocket"] = None
        try:
            await websocket.close()
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8003))
    uvicorn.run(app, host="0.0.0.0", port=port)
