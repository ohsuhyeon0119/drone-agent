"""
동행이 — 노인 돌봄 드론 에이전트 PoC, 3개 시나리오 통합 앱.

/fall        긴급 상황: 낙상 감지 → 프로액티브 발화 → 119 신고(tool call)
/medication  약 복용: 프로액티브 인사 → 복용 감지 → 메모리 기록 → 대시보드 표시
/task        작업 보조: 단순 VLM 대화 (감지 로직 없음)

세 페이지 모두 Gemini Live API(음성 대화, gemini_live.py)를 공유하고,
/fall·/medication은 추가로 OpenRouter(Groq 백엔드) 기반 프레임 감지 루프를 돌려
감지되면 nudge_input_queue를 통해 Gemini Live에 강제로 턴을 발생시킨다.
이 메커니즘은 gemini-live-api-examples/gemini-live-genai-python-sdk에서
먼저 검증된 것을 그대로 가져온 것이다.
"""

import asyncio
import base64
import json
import logging
import os
import re
import time

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI

import memory
from gemini_live import GeminiLive

load_dotenv()

logging.basicConfig(level=logging.INFO)
logging.getLogger("gemini_live").setLevel(logging.INFO)
logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("MODEL", "gemini-3.1-flash-live-preview")
OPENROUTER_API_KEY = os.getenv("OPEN_ROUTER_KEY", "")
DETECT_MODEL = "meta-llama/llama-4-scout"

# 폰 스트림 소스 (phone-stream 서버, 예: https://droneagent.cloud)
# 설정하면 브라우저 웹캠/마이크 대신 폰의 영상·오디오가 모델 입력이 된다.
# 비우면 기존처럼 브라우저 getUserMedia 사용.
PHONE_STREAM_URL = os.getenv("PHONE_STREAM_URL", "").strip().rstrip("/")
# Gemini Live에 넣는 영상은 기존 브라우저 경로와 동일하게 ~1fps로 제한
# (frame_buffer는 매 프레임 갱신 — 감지 VLM은 항상 최신 프레임을 본다)
PHONE_VIDEO_TO_GEMINI_INTERVAL = 1.0

# ──────────────────────────────────────────────────────────────
# 공통 페르소나
# ──────────────────────────────────────────────────────────────
PERSONA_BASE = """당신의 이름은 '동행이'입니다. 노인 곁을 지키는 돌봄 드론 에이전트입니다.
항상 다정하고 차분한 존댓말을 쓰고, 문장은 짧고 명확하게 말합니다. 서두르지 않습니다.

당신은 카메라로 지켜보고 목소리로 말할 수 있을 뿐입니다. 팔·다리·손이 없어서 물건을
직접 만지거나, 집어주거나, 가져다줄 수 없습니다. "물을 가져다드릴까요?"처럼 물리적으로
할 수 없는 행동을 제안하지 마세요. 대신 말로 안내하거나(예: "물은 식탁 위에 있어요"),
필요하면 보호자에게 알리는 방식으로 도우세요.

가끔 '[SYSTEM]'으로 시작하는 메시지를 받을 수 있습니다. 이는 사용자가 직접 말한 것이
아니라, 카메라로 관찰된 상황이나 시간 등을 알려주는 내부 신호입니다. 이런 메시지를
받으면 지금 하던 대화를 자연스럽게 멈추고 그 상황에 맞게 먼저 말을 걸거나 확인 질문을
하세요. '[SYSTEM]' 문구 자체를 사용자에게 그대로 읽거나 언급하지 마세요."""

FALL_PERSONA = (
    PERSONA_BASE
    + """

지금은 산책 등 일상 대화 중 낙상 사고를 대비하는 상황입니다.
낙상이 감지되었다는 [SYSTEM] 메시지를 받으면 즉시 걱정스러운 톤으로
"괜찮으세요?"라고 물어보고 119 신고 여부를 확인하세요. 사용자가 신고를 원하거나,
괜찮지 않다고 답하거나, 응답이 없으면 notify_caregiver 도구를 호출해 신고 상황을
기록하세요. 사용자가 명확히 괜찮다고 답하면 신고하지 말고 안심시키는 말로 마무리하세요."""
)

MEDICATION_PERSONA = (
    PERSONA_BASE
    + """

지금은 노인의 복약 시간을 챙기는 상황입니다. [SYSTEM] 메시지로 지금이 복약 시간이라는
안내를 받으면, 그 내용을 바탕으로 먼저 다정하게 말을 걸어 복용을 권해주세요
(예: "OO님, 지금 20시입니다. 지난번에 처방받으신 혈압약을 드셔야 해요.").
사용자가 복용하는 모습이 카메라로 확인되었다는 [SYSTEM] 메시지를 받으면
"잘하셨어요!"처럼 따뜻하게 칭찬하고 격려하세요. 아직 안 먹었다고 답하면
부드럽게 다시 권유하고, 재차 확인해주세요."""
)

TASK_PERSONA = (
    PERSONA_BASE
    + """

지금은 일상적인 작업(예: 키오스크, 가전제품, 서류 등)을 함께 보면서 돕는 상황입니다.
사용자가 화면이나 눈앞의 물건에 대해 물어보면, 카메라로 보이는 것을 근거로
쉽고 친절하게 한 단계씩 설명해주세요. 어려운 용어는 피하고, 필요하면 되물어서
정확히 확인한 뒤 안내하세요."""
)

FALL_DETECT_PROMPT = """이 이미지를 보고 사람이 엎드려 있거나 넘어져 있는지 감지하라.
반드시 아래 JSON 형식으로만 답하라, 코드펜스 금지:
{"event": "fall" 또는 "none", "confidence": 0.0~1.0, "reason": "판단 근거를 한 문장으로"}
"""

MEDICATION_DETECT_PROMPT = """이 이미지를 보고 사람이 알약이나 물컵을 입 근처로 가져가
약을 복용하는 동작을 하고 있는지 감지하라.
반드시 아래 JSON 형식으로만 답하라, 코드펜스 금지:
{"event": "taken" 또는 "none", "confidence": 0.0~1.0, "reason": "판단 근거를 한 문장으로"}
"""

NOTIFY_CAREGIVER_TOOL = {
    "function_declarations": [
        {
            "name": "notify_caregiver",
            "description": (
                "노인의 낙상이나 위급 상황이 감지되어 보호자 또는 119에 알림을 "
                "보내야 할 때 호출합니다. 사용자가 괜찮다고 명확히 답하면 호출하지 마세요."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "event_type": {"type": "STRING", "description": "감지된 이벤트 종류 (예: fall)"},
                    "message": {"type": "STRING", "description": "보호자에게 전달할 상황 요약 (한국어)"},
                },
                "required": ["event_type", "message"],
            },
        }
    ]
}


def notify_caregiver(event_type: str, message: str) -> str:
    logger.info(f"[TOOL CALL] notify_caregiver: event_type={event_type!r} message={message!r}")
    return "보호자에게 알림을 전송했습니다."


def _parse_json(text: str) -> dict | None:
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return None


async def detect_event(openrouter_client: AsyncOpenAI, frame: bytes, prompt: str) -> dict | None:
    """단일 프레임을 OpenRouter(Groq 우선, 혼잡 시 자동 대체)로 분석해 JSON 판정을 받는다."""
    data_url = f"data:image/jpeg;base64,{base64.b64encode(frame).decode()}"
    response = await openrouter_client.chat.completions.create(
        model=DETECT_MODEL,
        messages=[
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "이 이미지를 판정하세요."},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        temperature=0.1,
        max_tokens=100,
        extra_body={"provider": {"order": ["groq"]}},
    )
    raw = response.choices[0].message.content or ""
    return _parse_json(raw)


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


@app.get("/")
async def root():
    return RedirectResponse(url="/fall")


@app.get("/fall")
async def fall_page():
    return FileResponse("static/fall.html")


@app.get("/medication")
async def medication_page():
    return FileResponse("static/medication.html")


@app.get("/task")
async def task_page():
    return FileResponse("static/task.html")


@app.get("/api/medication/state")
async def medication_state():
    """대시보드가 새로고침 시에도 지금까지의 메모리 기록을 볼 수 있게 하는 조회용 엔드포인트."""
    return {"profile": memory.get_profile(), "logs": memory.get_logs()}


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


async def _receive_from_client(websocket, audio_input_queue, video_input_queue, text_input_queue, frame_buffer):
    """브라우저 → 모델 입력. PHONE_STREAM_URL이 설정되면 영상/오디오는 폰 피드가
    담당하므로 브라우저의 마이크 오디오와 웹캠 이미지는 버린다 (이중 입력 방지).
    텍스트 메시지는 항상 통과."""
    use_phone_source = bool(PHONE_STREAM_URL)
    try:
        while True:
            message = await websocket.receive()
            if message.get("bytes"):
                if not use_phone_source:
                    await audio_input_queue.put(message["bytes"])
            elif message.get("text"):
                text = message["text"]
                try:
                    payload = json.loads(text)
                    if isinstance(payload, dict) and payload.get("type") == "image":
                        if not use_phone_source:
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


async def _pump_phone_stream(audio_input_queue, video_input_queue, frame_buffer):
    """phone-stream 서버의 /ws/feed에 붙어 폰의 영상('V')/오디오('A')를 모델 입력에 주입.

    패킷 포맷: [1B 'V'|'A'][8B LE float64 capture_ts_ms][payload]
      - V: JPEG → frame_buffer(감지 VLM, 매 프레임) + video_input_queue(Gemini, ~1fps 제한)
      - A: 16kHz 16bit 모노 PCM → audio_input_queue (브라우저 마이크와 동일 포맷)
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
                        if frame_buffer is not None:
                            frame_buffer["data"] = payload
                        now = time.monotonic()
                        if now - last_video_to_gemini >= PHONE_VIDEO_TO_GEMINI_INTERVAL:
                            last_video_to_gemini = now
                            await video_input_queue.put(payload)
                    elif kind == b"A":
                        await audio_input_queue.put(payload)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"phone-stream feed 끊김/실패, 3초 후 재시도: {type(e).__name__}: {e}")
        await asyncio.sleep(3)


# ──────────────────────────────────────────────────────────────
# /ws/fall — 낙상 감지
# ──────────────────────────────────────────────────────────────
@app.websocket("/ws/fall")
async def ws_fall(websocket: WebSocket):
    await websocket.accept()
    logger.info("[/fall] WebSocket connection accepted")

    audio_input_queue = asyncio.Queue()
    video_input_queue = asyncio.Queue()
    text_input_queue = asyncio.Queue()
    nudge_input_queue = asyncio.Queue()
    frame_buffer = {"data": None}
    cooldown = {"fall": 0.0}
    FALL_COOLDOWN = 10.0

    gemini_client = GeminiLive(
        api_key=GEMINI_API_KEY,
        model=GEMINI_MODEL,
        input_sample_rate=16000,
        tools=[NOTIFY_CAREGIVER_TOOL],
        tool_mapping={"notify_caregiver": notify_caregiver},
        system_instruction=FALL_PERSONA,
    )

    receive_task = asyncio.create_task(
        _receive_from_client(websocket, audio_input_queue, video_input_queue, text_input_queue, frame_buffer)
    )
    phone_task = asyncio.create_task(
        _pump_phone_stream(audio_input_queue, video_input_queue, frame_buffer)
    ) if PHONE_STREAM_URL else None

    async def vision_loop():
        openrouter_client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
        while True:
            await asyncio.sleep(2)
            frame = frame_buffer["data"]
            if frame is None:
                continue
            try:
                result = await detect_event(openrouter_client, frame, FALL_DETECT_PROMPT)
                if result is None:
                    await websocket.send_json({"type": "detect_result", "ok": False, "error": "판정 파싱 실패"})
                    continue
            except Exception as e:
                logger.error(f"[/fall] detect error: {e}")
                await websocket.send_json({"type": "detect_result", "ok": False, "error": str(e)[:200]})
                continue

            await websocket.send_json({
                "type": "detect_result", "ok": True,
                "event": result.get("event"), "confidence": result.get("confidence"),
                "reason": result.get("reason"),
            })

            now = time.time()
            if result.get("event") == "fall" and now - cooldown["fall"] > FALL_COOLDOWN:
                cooldown["fall"] = now
                logger.info(f"[/fall] Fall detected! confidence={result.get('confidence')}")
                await websocket.send_json({
                    "type": "alert", "message": "낙상 감지! 즉시 확인이 필요합니다.",
                })
                nudge = (
                    "[SYSTEM] 카메라 영상에서 사용자가 방금 쓰러지는 것이 감지되었습니다. "
                    "지금 하던 대화를 멈추고 걱정스러운 톤으로 '괜찮으세요?'라고 즉시 물어보세요."
                )
                await websocket.send_json({"type": "system_nudge", "text": nudge})
                await nudge_input_queue.put(nudge)

    vision_task = asyncio.create_task(vision_loop())

    try:
        await _run_gemini_session(websocket, gemini_client, audio_input_queue, video_input_queue, text_input_queue, nudge_input_queue)
    except Exception as e:
        logger.error(f"[/fall] session error: {type(e).__name__}: {e}")
    finally:
        receive_task.cancel()
        vision_task.cancel()
        if phone_task:
            phone_task.cancel()
        try:
            await websocket.close()
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────
# /ws/medication — 약 복용 확인
# ──────────────────────────────────────────────────────────────
@app.websocket("/ws/medication")
async def ws_medication(websocket: WebSocket):
    await websocket.accept()
    logger.info("[/medication] WebSocket connection accepted")

    audio_input_queue = asyncio.Queue()
    video_input_queue = asyncio.Queue()
    text_input_queue = asyncio.Queue()
    nudge_input_queue = asyncio.Queue()
    frame_buffer = {"data": None}
    cooldown = {"taken": 0.0}
    TAKEN_COOLDOWN = 15.0
    already_confirmed = {"value": False}

    gemini_client = GeminiLive(
        api_key=GEMINI_API_KEY,
        model=GEMINI_MODEL,
        input_sample_rate=16000,
        system_instruction=MEDICATION_PERSONA,
    )

    receive_task = asyncio.create_task(
        _receive_from_client(websocket, audio_input_queue, video_input_queue, text_input_queue, frame_buffer)
    )
    phone_task = asyncio.create_task(
        _pump_phone_stream(audio_input_queue, video_input_queue, frame_buffer)
    ) if PHONE_STREAM_URL else None

    async def greet_once():
        """세션 시작 후 잠깐 기다렸다가(오디오/영상 파이프 준비 시간) 먼저 말을 건다."""
        await asyncio.sleep(2.5)
        profile = memory.get_profile()
        nudge = (
            f"[SYSTEM] 지금은 {profile['scheduled_time']}입니다. {profile['name']}님께 지난번에 "
            f"처방받으신 {profile['medication']}을 드셔야 한다고 먼저 다정하게 말을 거세요."
        )
        await websocket.send_json({"type": "system_nudge", "text": nudge})
        await nudge_input_queue.put(nudge)

    greet_task = asyncio.create_task(greet_once())

    async def vision_loop():
        openrouter_client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
        while True:
            await asyncio.sleep(2)
            frame = frame_buffer["data"]
            if frame is None:
                continue
            try:
                result = await detect_event(openrouter_client, frame, MEDICATION_DETECT_PROMPT)
                if result is None:
                    await websocket.send_json({"type": "detect_result", "ok": False, "error": "판정 파싱 실패"})
                    continue
            except Exception as e:
                logger.error(f"[/medication] detect error: {e}")
                await websocket.send_json({"type": "detect_result", "ok": False, "error": str(e)[:200]})
                continue

            await websocket.send_json({
                "type": "detect_result", "ok": True,
                "event": result.get("event"), "confidence": result.get("confidence"),
                "reason": result.get("reason"),
            })

            now = time.time()
            if result.get("event") == "taken" and now - cooldown["taken"] > TAKEN_COOLDOWN:
                cooldown["taken"] = now
                already_confirmed["value"] = True
                record = memory.record_medication_taken(note=result.get("reason", ""))
                logger.info(f"[/medication] Medication taken! record={record}")
                await websocket.send_json({
                    "type": "memory_update",
                    "record": record,
                    "message": f"✅ {record['timestamp']} — {record['medication']} 복용 확인, 메모리 업데이트됨",
                })
                nudge = (
                    "[SYSTEM] 방금 카메라로 사용자가 약을 복용하는 모습이 확인되었습니다. "
                    "잘하셨다고 따뜻하게 칭찬하고 격려해주세요."
                )
                await websocket.send_json({"type": "system_nudge", "text": nudge})
                await nudge_input_queue.put(nudge)

    vision_task = asyncio.create_task(vision_loop())

    try:
        await _run_gemini_session(websocket, gemini_client, audio_input_queue, video_input_queue, text_input_queue, nudge_input_queue)
    except Exception as e:
        logger.error(f"[/medication] session error: {type(e).__name__}: {e}")
    finally:
        receive_task.cancel()
        vision_task.cancel()
        greet_task.cancel()
        if phone_task:
            phone_task.cancel()
        try:
            await websocket.close()
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────
# /ws/task — 단순 VLM 대화 (감지 로직 없음)
# ──────────────────────────────────────────────────────────────
@app.websocket("/ws/task")
async def ws_task(websocket: WebSocket):
    await websocket.accept()
    logger.info("[/task] WebSocket connection accepted")

    audio_input_queue = asyncio.Queue()
    video_input_queue = asyncio.Queue()
    text_input_queue = asyncio.Queue()

    gemini_client = GeminiLive(
        api_key=GEMINI_API_KEY,
        model=GEMINI_MODEL,
        input_sample_rate=16000,
        system_instruction=TASK_PERSONA,
    )

    receive_task = asyncio.create_task(
        _receive_from_client(websocket, audio_input_queue, video_input_queue, text_input_queue, None)
    )
    phone_task = asyncio.create_task(
        _pump_phone_stream(audio_input_queue, video_input_queue, None)
    ) if PHONE_STREAM_URL else None

    try:
        await _run_gemini_session(websocket, gemini_client, audio_input_queue, video_input_queue, text_input_queue, None)
    except Exception as e:
        logger.error(f"[/task] session error: {type(e).__name__}: {e}")
    finally:
        receive_task.cancel()
        if phone_task:
            phone_task.cancel()
        try:
            await websocket.close()
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8003))
    uvicorn.run(app, host="0.0.0.0", port=port)
