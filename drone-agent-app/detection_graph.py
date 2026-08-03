"""
"카메라 프레임 → 이벤트 감지 → (통과 시) 넛지 문구 생성" 파이프라인을
LangGraph로 일반화한 것.

이전에는 main.py의 vision_loop()가 /fall과 /medication에 거의 동일한 형태로
복붙돼 있었다(프롬프트·타겟 이벤트·쿨다운·넛지 문구만 다름). 이 파일은 그
3단계(Detect → Decide → Nudge)를 하나의 그래프로 정의해두고, 시나리오별
설정값만 다르게 넣어 재사용한다.

이 그래프가 담당하는 건 "무엇을 감지했을 때 넛지 텍스트를 만들지"까지다.
그 넛지를 실제로 Gemini Live 세션에 주입하는 것과, 감지에 따른 시나리오별
부수 효과(예: 약 복용 시 memory.py에 기록)는 main.py 쪽 호출부의 책임으로
남겨둔다 — 그래프는 감지 로직만, 세션 제어와 시나리오별 부수효과는 호출부가.
"""

import base64
import json
import os
import re
import time

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph
from openai import AsyncOpenAI
from typing_extensions import TypedDict

# main.py의 load_dotenv() import 순서에 기대지 않도록, 이 모듈 자체가 .env를 로드한다
# (모듈 최상단에서 바로 클라이언트를 만들기 때문에 순서에 취약함).
load_dotenv()

DETECT_MODEL = "meta-llama/llama-4-scout"

_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPEN_ROUTER_KEY", ""),
)


class DetectionState(TypedDict, total=False):
    # ── 입력 (시나리오별 설정 + 매 호출 시 프레임) ──
    frame: bytes
    prompt: str            # 감지 기준을 담은 시스템 프롬프트
    target_event: str      # 이 값과 event가 일치해야 트리거됨
    cooldown: float        # 초 단위, 마지막 트리거 이후 이만큼 지나야 재트리거
    last_trigger_at: float  # 호출자가 들고 있는 마지막 트리거 시각
    nudge_template: str    # 트리거 시 nudge_input_queue에 넣을 문구

    # ── detect 노드가 채움 ──
    event: str
    confidence: float
    reason: str
    error: str

    # ── decide 노드가 채움 ──
    should_trigger: bool
    new_last_trigger_at: float

    # ── nudge 노드가 채움 ──
    nudge_text: str


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


async def detect_node(state: DetectionState) -> dict:
    """단일 프레임을 OpenRouter(Groq 우선, 혼잡 시 자동 대체)로 판정한다."""
    data_url = f"data:image/jpeg;base64,{base64.b64encode(state['frame']).decode()}"
    try:
        response = await _client.chat.completions.create(
            model=DETECT_MODEL,
            messages=[
                {"role": "system", "content": state["prompt"]},
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
        result = _parse_json(raw)
        if result is None:
            return {"error": f"판정 결과 JSON 파싱 실패: {raw[:200]!r}"}
        return {
            "event": result.get("event", "none"),
            "confidence": float(result.get("confidence", 0.0)),
            "reason": result.get("reason", ""),
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def decide_node(state: DetectionState) -> dict:
    """타겟 이벤트와 일치하고 쿨다운이 지났는지 판단한다."""
    if state.get("error"):
        return {"should_trigger": False}

    now = time.time()
    cooldown_passed = now - state.get("last_trigger_at", 0.0) > state["cooldown"]
    matched = state.get("event") == state["target_event"]

    if matched and cooldown_passed:
        return {"should_trigger": True, "new_last_trigger_at": now}
    return {"should_trigger": False, "new_last_trigger_at": state.get("last_trigger_at", 0.0)}


def nudge_node(state: DetectionState) -> dict:
    """트리거가 확정된 경우에만 실행되며, 넛지 문구를 state에 채운다."""
    return {"nudge_text": state["nudge_template"]}


def _route_after_decide(state: DetectionState) -> str:
    return "nudge" if state.get("should_trigger") else END


def build_detection_graph():
    graph = StateGraph(DetectionState)
    graph.add_node("detect", detect_node)
    graph.add_node("decide", decide_node)
    graph.add_node("nudge", nudge_node)

    graph.add_edge(START, "detect")
    graph.add_edge("detect", "decide")
    graph.add_conditional_edges("decide", _route_after_decide, {"nudge": "nudge", END: END})
    graph.add_edge("nudge", END)

    return graph.compile()


# 그래프는 순수 함수들로만 구성돼 상태가 없다(state는 매 호출마다 인자로 들어옴) —
# 컴파일을 한 번만 해서 모든 시나리오가 공유해도 안전하다.
detection_graph = build_detection_graph()
