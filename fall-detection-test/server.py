"""
낙상 감지 속도/정확도 단독 검증용 서버.

프론트가 1초마다 프레임 1장을 /detect로 보내면, 그 즉시 Groq VLM에게 물어서
"양손이 어깨 위로 올라가 있는지" 판정하고 결과 + 소요시간(ms)을 돌려준다.
에이전트(음성 대화) 쪽과는 완전히 분리된, detect 단계만 떼어낸 실험용 서버.

Groq를 쓰는 이유: gemini-3-flash-preview는 무료 티어 20회/일로 폴링에 못 씀.
Groq(llama-4-scout)는 무료 티어 1,000회/일·30회/분이라 검증용으로 충분하고,
Lifenology(../Lifenology)가 이미 같은 모델로 낙상 감지를 검증해둔 방식을 그대로 씀.
"""

import base64
import json
import logging
import os
import re
import time

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from groq import Groq
from pydantic import BaseModel

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

client = Groq(api_key=GROQ_API_KEY)

SYSTEM_PROMPT = """이 이미지를 보고 사람이 엎드려 있거나 넘어져 있는지 감지하라.
반드시 아래 JSON 형식으로만 답하라, 코드펜스 금지:
{"event": "fall" 또는 "none", "confidence": 0.0~1.0, "reason": "판단 근거를 한 문장으로"}
"""


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
    return FileResponse("static/index.html")


class DetectRequest(BaseModel):
    image: str  # base64 JPEG (data: 접두어 없이)


@app.post("/detect")
async def detect(req: DetectRequest):
    t0 = time.time()
    data_url = f"data:image/jpeg;base64,{req.image}"
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
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
        )
        raw = response.choices[0].message.content or ""
        result = _parse_json(raw)
        if result is None:
            raise ValueError(f"JSON 파싱 실패: {raw[:200]!r}")
    except Exception as e:
        latency_ms = int((time.time() - t0) * 1000)
        logger.error(f"detect error ({latency_ms}ms): {e}")
        return {"ok": False, "error": str(e), "latency_ms": latency_ms}

    latency_ms = int((time.time() - t0) * 1000)
    logger.info(f"result={result} latency={latency_ms}ms")
    return {"ok": True, "result": result, "latency_ms": latency_ms}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8002))
    uvicorn.run(app, host="0.0.0.0", port=port)
