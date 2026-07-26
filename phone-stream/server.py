"""
폰 → 서버 실시간 영상 스트리밍 수신 서버.

아이폰 Safari(phone.html)가 카메라 프레임을 JPEG로 인코딩해 WebSocket 바이너리로
보내면, 최신 프레임을 frame_buffer에 유지하고 뷰어(viewer.html)들에게 브로드캐스트한다.

AI 파이프라인(기존 main.py의 Groq detect / Gemini Live)은 다음 훅으로 프레임을 소비:
  - GET /frame.jpg          : 최신 프레임 1장 (폴링용)
  - WS  /ws/viewer          : 프레임 push 구독
  - get_latest_frame()      : 같은 프로세스에 흡수 통합할 경우

바이너리 포맷 (폰 → 서버, 같은 WS에 영상/오디오 혼합):
  [1B 타입: b"V"=영상 | b"A"=오디오] + [8B LE float64: 서버시계 기준 캡처시각(ms)] + [payload]
  영상 payload: JPEG bytes / 오디오 payload: 16kHz 16bit 모노 PCM (기본 100ms = 3200B)
서버 → 뷰어: [8B capture_ts(ms)] + [8B recv_ts(ms)] + [JPEG bytes] (영상만)

iOS getUserMedia는 HTTPS 필수 → make_cert.sh로 인증서 생성 후 기동.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import struct
import time
from collections import deque
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# ---- frame_buffer: 최신 프레임 1장 (기존 파이프라인과 동일한 개념) ----
latest_jpeg: bytes | None = None
latest_meta: dict = {}  # capture_ts, recv_ts, seq
frame_seq = 0
phone_connected = False

# 최근 수신 시각들 — 수신 fps 계산용
recv_times: list[float] = []

# 뷰어 fan-out: 뷰어별 maxsize=2 큐. 느린 뷰어는 오래된 프레임을 버린다.
viewer_queues: set[asyncio.Queue] = set()

# ---- 오디오: 16kHz 16bit 모노 PCM 조각 스트림 ----
# 영상과 달리 조각을 버리면 소리가 끊기므로, 구독 큐는 넉넉하게 잡고 순서대로 전달한다.
AUDIO_SR = 16000
audio_chunk_seq = 0
audio_bytes_total = 0
audio_last_recv_ts: float | None = None
recent_audio: deque = deque(maxlen=100)  # (capture_ts, recv_ts, pcm) — 최근 ~10초
audio_queues: set[asyncio.Queue] = set()


def subscribe_audio(maxsize: int = 100) -> asyncio.Queue:
    """AI 파이프라인(Gemini Live 등)이 같은 프로세스에서 오디오를 구독할 때의 훅.
    큐 항목: (capture_ts_ms, pcm_bytes). 다 쓰면 audio_queues.discard(q)로 해지."""
    q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
    audio_queues.add(q)
    return q

# ---- 녹화 모드 (run.sh에서 선택) ----
#   off  : 저장 안 함 — 실시간 전달만 (기존 동작)
#   jpeg : 수신 프레임을 recordings/<세션>/frames/NNNNNN.jpg 로 전부 저장
#   mp4  : 위처럼 저장했다가 폰 연결 종료 시 ffmpeg로 video.mp4 조립 (JPEG는 삭제)
RECORD_MODE = os.getenv("RECORD_MODE", "off").lower()
RECORD_DIR = os.getenv("RECORD_DIR", os.path.join(BASE_DIR, "recordings"))


class Recorder:
    """폰 WS 세션 하나 = 녹화 세션 하나. 프레임을 디스크에 쌓고, mp4 모드면 종료 시 조립."""

    def __init__(self):
        session = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.dir = os.path.join(RECORD_DIR, session)
        self.frames_dir = os.path.join(self.dir, "frames")
        os.makedirs(self.frames_dir, exist_ok=True)
        self.meta_f = open(os.path.join(self.dir, "frames.jsonl"), "w")
        self.count = 0
        self.recv_ts_list: list[float] = []
        self.first_video_capture_ts: float | None = None
        # 오디오는 raw PCM을 이어 붙이기만 한다 (재생: ffplay -f s16le -ar 16000 -ac 1 audio.pcm)
        self.audio_f = None
        self.audio_first_capture_ts: float | None = None
        self.audio_bytes = 0
        logger.info("녹화 시작 (%s 모드): %s", RECORD_MODE, self.dir)

    def add_audio(self, pcm: bytes, capture_ts: float):
        if self.audio_f is None:
            self.audio_f = open(os.path.join(self.dir, "audio.pcm"), "wb")
            self.audio_first_capture_ts = capture_ts
        self.audio_f.write(pcm)
        self.audio_bytes += len(pcm)

    def add(self, jpeg: bytes, capture_ts: float, recv_ts: float):
        self.count += 1
        if self.first_video_capture_ts is None:
            self.first_video_capture_ts = capture_ts
        name = f"{self.count:06d}.jpg"
        with open(os.path.join(self.frames_dir, name), "wb") as f:
            f.write(jpeg)
        self.meta_f.write(json.dumps(
            {"file": name, "capture_ts": capture_ts, "recv_ts": recv_ts}) + "\n")
        self.recv_ts_list.append(recv_ts)

    async def finalize(self):
        self.meta_f.close()
        if self.audio_f:
            self.audio_f.close()
        if self.count == 0 and self.audio_bytes == 0:
            shutil.rmtree(self.dir, ignore_errors=True)
            return
        logger.info("녹화 종료: 영상 %d 프레임, 오디오 %.1f초 → %s",
                    self.count, self.audio_bytes / 2 / AUDIO_SR, self.dir)
        if RECORD_MODE != "mp4" or self.count == 0:
            return

        # 실제 수신 간격을 프레임 duration으로 써서 원래 속도로 재생되는 mp4를 만든다
        list_path = os.path.join(self.dir, "list.txt")
        with open(list_path, "w") as f:
            f.write("ffconcat version 1.0\n")
            for i in range(self.count):
                if i < self.count - 1:
                    dur = (self.recv_ts_list[i + 1] - self.recv_ts_list[i]) / 1000
                else:
                    dur = 0.2
                dur = min(max(dur, 0.01), 2.0)
                f.write(f"file 'frames/{i + 1:06d}.jpg'\nduration {dur:.3f}\n")

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            logger.warning("ffmpeg가 없어 mp4 조립 생략 — JPEG 프레임은 %s 에 남아있음", self.frames_dir)
            return
        mp4_path = os.path.join(self.dir, "video.mp4")
        args = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", list_path]
        if self.audio_bytes:
            # 캡처시각(둘 다 서버시계 기준) 차이로 오디오 시작점을 영상 타임라인에 정렬
            offset = max(0.0, (self.audio_first_capture_ts - self.first_video_capture_ts) / 1000)
            args += ["-itsoffset", f"{offset:.3f}",
                     "-f", "s16le", "-ar", str(AUDIO_SR), "-ac", "1",
                     "-i", os.path.join(self.dir, "audio.pcm")]
        args += ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
        if self.audio_bytes:
            args += ["-c:a", "aac"]
        args += [mp4_path]
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        if proc.returncode == 0 and os.path.exists(mp4_path):
            shutil.rmtree(self.frames_dir, ignore_errors=True)
            os.remove(list_path)
            logger.info("mp4 저장 완료 (%s): %s",
                        "오디오 포함" if self.audio_bytes else "무음", mp4_path)
        else:
            logger.error("ffmpeg 실패(code %s) — JPEG 프레임은 %s 에 남아있음",
                         proc.returncode, self.frames_dir)


def get_latest_frame() -> tuple[bytes, dict] | None:
    """AI 파이프라인이 같은 프로세스에서 쓸 때의 훅."""
    if latest_jpeg is None:
        return None
    return latest_jpeg, dict(latest_meta)


def _now_ms() -> float:
    return time.time() * 1000


@app.get("/")
async def phone_page():
    return FileResponse(os.path.join(BASE_DIR, "static", "phone.html"))


@app.get("/viewer")
async def viewer_page():
    return FileResponse(os.path.join(BASE_DIR, "static", "viewer.html"))


@app.get("/frame.jpg")
async def frame_jpg():
    """AI 파이프라인용: 언제든 최신 프레임 1장."""
    if latest_jpeg is None:
        return JSONResponse({"error": "no frame yet"}, status_code=404)
    return Response(
        content=latest_jpeg,
        media_type="image/jpeg",
        headers={
            "X-Capture-Ts": str(latest_meta.get("capture_ts", 0)),
            "X-Recv-Ts": str(latest_meta.get("recv_ts", 0)),
            "X-Seq": str(latest_meta.get("seq", 0)),
            "Cache-Control": "no-store",
        },
    )


@app.get("/stats")
async def stats():
    now = _now_ms()
    window = [t for t in recv_times if now - t < 5000]
    fps = len(window) / 5.0
    age_ms = (now - latest_meta["recv_ts"]) if latest_meta else None
    return {
        "record_mode": RECORD_MODE,
        "phone_connected": phone_connected,
        "frames_received": frame_seq,
        "recv_fps_5s": round(fps, 2),
        "latest_frame_age_ms": round(age_ms) if age_ms is not None else None,
        "latest_e2e_latency_ms": latest_meta.get("e2e_ms"),
        "viewers": len(viewer_queues),
        "audio_chunks_received": audio_chunk_seq,
        "audio_seconds_received": round(audio_bytes_total / 2 / AUDIO_SR, 1),
        "audio_last_age_ms": round(now - audio_last_recv_ts) if audio_last_recv_ts else None,
        "audio_subscribers": len(audio_queues),
    }


@app.websocket("/ws/phone")
async def ws_phone(ws: WebSocket):
    global latest_jpeg, latest_meta, frame_seq, phone_connected
    global audio_chunk_seq, audio_bytes_total, audio_last_recv_ts
    await ws.accept()
    phone_connected = True
    logger.info("phone connected: %s", ws.client)
    recorder = Recorder() if RECORD_MODE in ("jpeg", "mp4") else None
    try:
        while True:
            msg = await ws.receive()
            if msg.get("bytes") is not None:
                data: bytes = msg["bytes"]
                if len(data) < 10:
                    continue
                kind = data[0:1]
                (capture_ts,) = struct.unpack("<d", data[1:9])
                payload = data[9:]
                recv_ts = _now_ms()

                if kind == b"A":
                    audio_chunk_seq += 1
                    audio_bytes_total += len(payload)
                    audio_last_recv_ts = recv_ts
                    recent_audio.append((capture_ts, recv_ts, payload))
                    for q in list(audio_queues):
                        if q.full():
                            try:
                                q.get_nowait()  # 구독자가 5초 이상 밀리면 가장 오래된 것부터 포기
                            except asyncio.QueueEmpty:
                                pass
                        q.put_nowait((capture_ts, payload))
                    if recorder:
                        recorder.add_audio(payload, capture_ts)
                    continue

                if kind != b"V":
                    continue
                jpeg = payload
                frame_seq += 1
                latest_jpeg = jpeg
                latest_meta = {
                    "capture_ts": capture_ts,
                    "recv_ts": recv_ts,
                    "e2e_ms": round(recv_ts - capture_ts),
                    "seq": frame_seq,
                }
                recv_times.append(recv_ts)
                if len(recv_times) > 300:
                    del recv_times[:100]

                if recorder:
                    recorder.add(jpeg, capture_ts, recv_ts)

                out = struct.pack("<dd", capture_ts, recv_ts) + jpeg
                for q in list(viewer_queues):
                    if q.full():
                        try:
                            q.get_nowait()  # 오래된 프레임 버림
                        except asyncio.QueueEmpty:
                            pass
                    q.put_nowait(out)

            elif msg.get("text") is not None:
                # 시계 동기화 ping: {"type":"ping","t0":<phone ms>}
                try:
                    payload = json.loads(msg["text"])
                except json.JSONDecodeError:
                    continue
                if payload.get("type") == "ping":
                    await ws.send_text(json.dumps({
                        "type": "pong",
                        "t0": payload.get("t0"),
                        "server": _now_ms(),
                    }))
    except WebSocketDisconnect:
        pass
    finally:
        phone_connected = False
        logger.info("phone disconnected")
        if recorder:
            await recorder.finalize()


@app.websocket("/ws/viewer")
async def ws_viewer(ws: WebSocket):
    await ws.accept()
    q: asyncio.Queue = asyncio.Queue(maxsize=2)
    viewer_queues.add(q)
    logger.info("viewer connected (%d total)", len(viewer_queues))
    try:
        while True:
            frame = await q.get()
            await ws.send_bytes(frame)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        viewer_queues.discard(q)
        logger.info("viewer disconnected (%d total)", len(viewer_queues))


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8443))
    certfile = os.getenv("CERT_FILE", os.path.join(BASE_DIR, "certs", "cert.pem"))
    keyfile = os.getenv("KEY_FILE", os.path.join(BASE_DIR, "certs", "key.pem"))

    if os.path.exists(certfile) and os.path.exists(keyfile):
        logger.info("HTTPS 모드로 기동 (port %d)", port)
        uvicorn.run(app, host="0.0.0.0", port=port,
                    ssl_certfile=certfile, ssl_keyfile=keyfile)
    else:
        logger.warning(
            "인증서가 없어 HTTP 모드로 기동 — iOS getUserMedia는 HTTPS 필수이므로 "
            "실폰 테스트 전에 ./make_cert.sh 를 실행하세요 (또는 ngrok 사용)"
        )
        uvicorn.run(app, host="0.0.0.0", port=port)
