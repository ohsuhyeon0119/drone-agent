"""대화를 그대로 쌓지 않고, 보호자가 볼 만한 형태로 압축해 저장한다.

전사(transcription)를 통째로 남기면 양이 많고 개인정보 부담도 크다. 대신 세션이
끝날 때 한 번 요약해서 남긴다. 요약의 핵심은 **"어르신이 요청했는데 이뤄지지
않은 것"** 이다 — 동행이는 팔·다리가 없어서 물건을 가져다줄 수 없으므로, 이런
미이행 요청이야말로 보호자가 대신 챙겨야 하는 정보다.

요약에 실패해도 세션 종료를 막지 않는다 (요약은 부가 기능이므로).
"""

from __future__ import annotations

import json
import logging
import os
import re

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

logger = logging.getLogger(__name__)

SUMMARY_MODEL = os.getenv("SUMMARY_MODEL", "meta-llama/llama-4-scout")

_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPEN_ROUTER_KEY", ""),
)

PROMPT = """당신은 노인 돌봄 에이전트 '동행이'의 대화 기록을 보호자에게 보고하는 역할입니다.
아래 대화를 읽고 보호자가 알아야 할 것만 뽑아 요약하세요.

가장 중요한 것은 **어르신이 요청했지만 이뤄지지 않은 일**입니다. 동행이는 카메라와
목소리만 있고 팔·다리가 없어서 물건을 가져다주거나 만질 수 없습니다. 그래서
"물 좀 갖다줘", "약 좀 꺼내줘" 같은 요청은 말로 안내만 하고 실제로는 해결되지
않습니다. 이런 것을 빠짐없이 찾아주세요.

반드시 아래 JSON 형식으로만 답하세요. 코드펜스 금지:
{
  "summary": "대화 전체를 2~3문장으로 (한국어)",
  "requests": [
    {"text": "어르신이 요청한 내용", "fulfilled": true 또는 false,
     "note": "이뤄졌다면 어떻게, 아니면 왜 못했는지 한 문장"}
  ],
  "notable": ["보호자가 알아야 할 특이사항 (통증 호소, 기분 변화 등). 없으면 빈 배열"],
  "mood": "밝음 | 보통 | 가라앉음 | 불안"
}

요청이 하나도 없으면 requests는 빈 배열로 두세요. 대화에 없는 내용을 지어내지 마세요.

--- 대화 ---
"""


def _parse_json(text: str) -> dict | None:
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return None


def render_transcript(turns: list[dict]) -> str:
    """[{role, text}] → 모델에게 넘길 대화 텍스트."""
    label = {"user": "어르신", "agent": "동행이", "system": "[상황]"}
    lines = []
    for t in turns:
        text = (t.get("text") or "").strip()
        if text:
            lines.append(f"{label.get(t.get('role'), t.get('role'))}: {text}")
    return "\n".join(lines)


async def summarize(turns: list[dict]) -> dict | None:
    """대화를 압축한다. 대화가 너무 짧으면(인사만 하고 끝) 저장할 가치가 없어 건너뛴다."""
    transcript = render_transcript(turns)
    if len(transcript) < 40:
        return None

    try:
        response = await _client.chat.completions.create(
            model=SUMMARY_MODEL,
            messages=[{"role": "user", "content": PROMPT + transcript}],
            temperature=0.2,
            max_tokens=700,
            extra_body={"provider": {"order": ["groq"]}},
        )
        result = _parse_json(response.choices[0].message.content or "")
    except Exception as e:
        logger.error(f"[summarizer] 요약 실패: {type(e).__name__}: {e}")
        return None

    if not isinstance(result, dict) or not result.get("summary"):
        logger.warning("[summarizer] 요약 형식이 올바르지 않아 저장하지 않음")
        return None

    requests = [r for r in (result.get("requests") or []) if isinstance(r, dict) and r.get("text")]
    return {
        "summary": str(result["summary"]).strip(),
        "requests": requests,
        "unfulfilled": [r for r in requests if not r.get("fulfilled")],
        "notable": [str(x) for x in (result.get("notable") or []) if str(x).strip()],
        "mood": result.get("mood") or "보통",
        "turn_count": len(turns),
    }
