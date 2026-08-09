"""보호자에게 어르신에 대해 물어보는 온보딩 인터뷰.

설계 근거는 저장소 루트의 personalization.plan.md §3.

핵심 구조는 **슬롯 상태 기계 + 필요할 때만 LLM**이다.

  - 물어볼 질문과 순서는 코드에 고정돼 있다(SLOTS). LLM이 질문을 지어내게 두지
    않는 이유는 두 가지다. 어르신 건강을 묻는 자리라 문장 하나가 실례가 될 수
    있고, 매번 다른 걸 물으면 데이터가 모이지 않는다.
  - 되묻기도 코드에 있다(followups) — 어떤 답에 무엇을 되물을지는 규칙이라
    모델에게 맡길 이유가 없다.
  - LLM은 **보호자가 직접 타이핑했을 때만** 부른다. "조용하세요, 귀도 좀
    어두우시고" 한마디에 슬롯 두 개가 동시에 채워지는 경우를 잡기 위해서다.
    선택지를 눌렀으면 값이 이미 정확하므로 모델을 부르지 않는다(즉답).

질문 순서는 관찰하기 쉽고 감정 부담이 없는 것부터다. 인지 저하(memory)를
맨 뒤에 둔 건, 그걸 인정하는 게 자녀에게 가장 힘든 일이라 앞에 놓으면
거기서 대화가 끊기기 때문이다.
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

INTERVIEW_MODEL = os.getenv("SUMMARY_MODEL", "meta-llama/llama-4-scout")

_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPEN_ROUTER_KEY", ""),
)

GREETING = (
    "안녕하세요, 동행이입니다.\n"
    "어르신 곁에서 잘 도와드리려면 어떤 분이신지 알아야 해서 몇 가지만 여쭤볼게요. "
    "3분이면 됩니다.\n"
    "모르시는 건 '모르겠어요'라고 하셔도 괜찮고, 언제든 그만두셔도 됩니다."
)

# 각 슬롯이 무엇을 바꾸는지는 plan §6.1 참고. 착지점 없는 질문은 넣지 않는다.
SLOTS: list[dict] = [
    {
        "key": "name",
        "question": "먼저, 어르신 성함이 어떻게 되세요?",
        "options": [],
    },
    {
        "key": "birth_year",
        "question": "몇 년생이세요?",
        "options": [],
        "hint": "예: 1943",
    },
    {
        "key": "address_as",
        "question": "동행이가 어르신을 뭐라고 불러드리면 좋을까요?",
        "options": ["어르신", "성함으로", "할머니", "할아버지"],
    },
    {
        "key": "lives_alone",
        "question": "평소에 혼자 지내세요?",
        "options": ["혼자 지내세요", "배우자와 함께", "가족과 함께"],
    },
    # ── 여기부터 돌봄 판단에 쓰이는 항목 ──────────────────────────
    {
        "key": "mobility",
        "question": "혼자 화장실 다녀오시는 건 괜찮으세요?",
        "options": ["괜찮으세요", "조금 불편해하세요", "지팡이를 쓰세요", "보행기나 휠체어를 쓰세요"],
        "followups": {
            # 장소를 적어야 하는 질문이다. 선택지는 "없다"고 답할 지름길일 뿐이라
            # 자유 입력을 함께 열어둔다(free) — 안 그러면 화장실이라고 쓸 방법이 없다.
            v: {"q": "집에서 특히 넘어지실까 걱정되는 곳이 있으세요?",
                "key": "risk_places", "options": ["딱히 없어요"], "free": True,
                "hint": "예: 화장실, 문턱, 계단"}
            for v in ("조금 불편해하세요", "지팡이를 쓰세요", "보행기나 휠체어를 쓰세요")
        },
    },
    {
        "key": "fall_history",
        "question": "최근 1년 안에 넘어지신 적 있으세요?",
        "options": ["없어요", "있어요", "모르겠어요"],
        # 어르신은 넘어진 걸 자식에게 말하지 않는 경우가 많다 — 걱정 끼치기 싫어서,
        # 또는 요양원 이야기가 나올까 봐. "없다"를 그대로 믿지 않고 한 번 우회한다.
        "followups": {
            "있어요": {"q": "어디서 넘어지셨어요?", "key": "fall_place",
                      "options": ["기억이 안 나세요"], "free": True,
                      "hint": "예: 화장실, 마당"},
            "없어요": {"q": "혹시 멍이 들었거나 어디 부딪히셨다는 말씀을 하신 적은 없으세요?",
                      "key": "fall_hidden",
                      "options": ["그런 적 없어요", "그런 적 있어요", "모르겠어요"]},
            "모르겠어요": {"q": "혹시 멍이 들었거나 어디 부딪히셨다는 말씀을 하신 적은 없으세요?",
                       "key": "fall_hidden",
                       "options": ["그런 적 없어요", "그런 적 있어요", "모르겠어요"]},
        },
    },
    {
        # 청력을 자녀에게 직접 물으면 답이 왜곡된다 — 이미 크게 말하는 데 적응해서
        # 문제를 인지하지 못하고, 통화가 주된 접점이면 원래 잘 안 들린다.
        # TV 음량은 관찰 가능하고 적응 편향이 없다.
        "key": "hearing",
        "question": "TV 소리를 크게 틀어두시는 편인가요?",
        "options": ["아니요, 괜찮으세요", "조금 크게 트세요", "많이 크게 트세요", "모르겠어요"],
        "followups": {
            v: {"q": "말씀드린 걸 여러 번 되물으시는 일도 잦으세요?",
                "key": "hearing_recheck", "options": ["네, 잦아요", "아니요"]}
            for v in ("조금 크게 트세요", "많이 크게 트세요")
        },
    },
    {
        "key": "talkativeness",
        "question": "평소에 말씀이 많은 편이세요, 조용하신 편이세요?",
        # 원래 과묵하신 분과 최근 말수가 준 분은 완전히 다른 신호다.
        # 전자는 "과하게 말 걸지 않기", 후자는 보호자에게 알려야 할 변화다.
        "options": ["말씀이 많으세요", "보통이세요", "조용하신 편이에요"],
        "followups": {
            "조용하신 편이에요": {
                "q": "원래 그러셨어요, 아니면 예전보다 줄어드신 건가요?",
                "key": "talk_change", "options": ["원래 그러세요", "예전보다 줄었어요"],
            },
        },
    },
    {
        "key": "help_attitude",
        "question": "누가 도와드리려고 하면 어떤 반응이세요?",
        "options": ["편하게 받으세요", "괜찮다고 하세요", "싫어하세요"],
    },
    {
        # 가장 무거운 질문이라 맨 뒤에 둔다.
        "key": "memory",
        "question": "예전에 비해 같은 이야기를 자주 하시나요?",
        "options": ["아니요", "가끔 그러세요", "자주 그러세요", "모르겠어요"],
        "followups": {
            "자주 그러세요": {
                "q": "약을 드셨는지 못 알아보시는 정도인가요?",
                "key": "memory_med", "options": ["그 정도는 아니에요", "네, 그러세요"],
            },
        },
    },
    {
        "key": "interests",
        "question": "어르신이 좋아하시는 게 있으세요? 대화 나눌 때 꺼낼 만한 거요.",
        "options": [],
        "hint": "예: 트로트, 화투, 텃밭 가꾸기",
    },
    {
        # 슬롯에 없는 것이 여기서 나온다. 실제로 가장 값어치 있는 질문일 수 있다.
        # 선택지("없어요")는 빠져나갈 지름길일 뿐이라 자유 입력을 함께 연다.
        "key": "free",
        "question": "마지막으로, 제가 꼭 알아야 할 게 더 있을까요?",
        "options": ["없어요"],
        "free": True,
        "hint": "예: 요즘 자꾸 밤에 나가려고 하세요",
    },
]

SLOT_BY_KEY = {s["key"]: s for s in SLOTS}

MAX_TURNS = 20


# ──────────────────────────────────────────────────────────────
# 대화 진행
# ──────────────────────────────────────────────────────────────
def _next_slot(answers: dict) -> dict | None:
    """아직 답이 없는 첫 슬롯. 이미 답한 것과 이미 물어본 것은 건너뛴다.

    '물어본 것'을 따로 기억하는 이유는, 보호자가 자유롭게 쓴 답을 선택지 값으로
    옮기지 못하는 경우가 있기 때문이다. 그때 값이 비었다고 다시 물으면 같은
    질문을 반복하게 된다 — 한 번 물었으면 넘어가고, 그 항목은 '모름'으로 남긴다.
    """
    asked = set(answers.get("_asked") or [])
    for slot in SLOTS:
        if not answers.get(slot["key"]) and slot["key"] not in asked:
            return slot
    return None


def opening() -> dict:
    """인터뷰 첫 화면 — 인사와 첫 질문."""
    first = SLOTS[0]
    return {
        "greeting": GREETING,
        "question": first["question"],
        "slot": first["key"],
        "options": first["options"],
        "allow_text": bool(first.get("free")) or not first["options"],
        "hint": first.get("hint", ""),
        "done": False,
        "progress": {"filled": 0, "total": len(SLOTS)},
    }


async def advance(answers: dict, asked: str, text: str, pending_followup: str = "") -> dict:
    """답변 하나를 받아 다음에 할 말을 정한다.

    `asked`는 방금 물어본 슬롯, `pending_followup`은 방금 던진 되묻기의 저장 키다
    (되묻기에 대한 답은 슬롯 진행을 바꾸지 않고 그 키에만 저장한다).

    선택지를 누른 경우에는 값이 이미 정확하므로 LLM을 부르지 않는다 — 대부분의
    턴이 즉답으로 끝난다. 직접 타이핑한 경우에만 모델을 불러서 값을 매핑하고,
    묻지 않은 슬롯이 함께 답해졌는지 확인한다.
    """
    answers = dict(answers)
    text = (text or "").strip()
    slot = SLOT_BY_KEY.get(asked)

    if pending_followup:
        # 되묻기에 대한 답 — 그대로 저장하고 다음 슬롯으로 넘어간다
        if text:
            answers[pending_followup] = text
        return _reply(answers)

    if not slot:
        return _reply(answers)

    answers["_asked"] = sorted(set(answers.get("_asked") or []) | {slot["key"]})

    options = slot.get("options") or []
    if text in options:
        answers[slot["key"]] = text
    elif text:
        extracted = await _map_answer(slot, text, answers)
        answers.update(extracted)
        if not answers.get(slot["key"]):
            # 선택지 중 어느 것인지 정하지 못했다. 원문은 남겨서 보호자가 한 말이
            # 사라지지 않게 하되, 슬롯 값으로는 쓰지 않는다 — 정의되지 않은 값이
            # 들어가면 감지 설정을 엉뚱하게 조정하게 된다. (plan §3.3)
            answers[f"{slot['key']}__raw"] = text

    # 되묻기는 규칙이다. 방금 확정된 값에 걸린 게 있으면 그것부터 던진다.
    value = answers.get(slot["key"])
    followup = (slot.get("followups") or {}).get(value)
    if followup:
        return {
            "question": followup["q"],
            "slot": slot["key"],
            "options": followup.get("options", []),
            # 선택지가 있어도 자유 입력을 함께 받아야 하는 질문이 있다 (장소 이름 등)
            "allow_text": bool(followup.get("free")),
            "hint": followup.get("hint", ""),
            "followup_key": followup["key"],
            "done": False,
            "answers": answers,
            "progress": _progress(answers),
        }

    return _reply(answers)


def _reply(answers: dict) -> dict:
    nxt = _next_slot(answers)
    if nxt is None or len(answers) > MAX_TURNS:
        return {
            "question": "",
            "slot": "",
            "options": [],
            "done": True,
            "answers": answers,
            "progress": _progress(answers),
        }
    return {
        "question": nxt["question"],
        "slot": nxt["key"],
        "options": nxt["options"],
        "allow_text": bool(nxt.get("free")) or not nxt["options"],
        "hint": nxt.get("hint", ""),
        "followup_key": "",
        "done": False,
        "answers": answers,
        "progress": _progress(answers),
    }


def _progress(answers: dict) -> dict:
    """진행률은 '답한 수'가 아니라 '물어본 수'로 센다 — 모른다고 답한 항목도
    진행은 된 것이라, 값 기준으로 세면 막대가 멈춘 것처럼 보인다."""
    asked = set(answers.get("_asked") or [])
    done = sum(1 for s in SLOTS if answers.get(s["key"]) or s["key"] in asked)
    return {"filled": done, "total": len(SLOTS)}


# ──────────────────────────────────────────────────────────────
# 자유 답변 → 슬롯 값
# ──────────────────────────────────────────────────────────────
_MAP_PROMPT = """당신은 노인 돌봄 서비스의 보호자 상담 내용을 정리하는 역할입니다.
보호자의 답변을 읽고, 알 수 있는 항목의 값을 정하세요.

[방금 물어본 항목 — 답변에서 값을 정할 수 있으면 반드시 결과에 포함하세요]
{asked}

[보호자가 먼저 말했다면 함께 채울 항목 — 언급이 없으면 빼세요]
{others}

규칙:
- 값은 반드시 위에 나열된 값 중 하나를 **글자 그대로** 쓰세요. 새로 지어내지 마세요.
- 애매하면 반드시 **덜 심각한 쪽**으로 정하세요. 과대 판정은 잘못된 알림으로 이어집니다.
- 언급이 전혀 없는 항목은 결과에 넣지 마세요.

예시)
답변: "무릎이 안 좋아서 지팡이 짚으세요. 귀도 어두우셔서 TV를 크게 트시고요."
결과: {{"mobility": "지팡이를 쓰세요", "hearing": "많이 크게 트세요"}}

반드시 JSON만 출력하세요. 코드펜스 금지:
{{"항목이름": "값", ...}}

보호자 답변: {text}"""


async def _map_answer(slot: dict, text: str, answers: dict) -> dict:
    """타이핑한 답을 슬롯 값으로 옮긴다. 다른 슬롯이 함께 답해졌으면 그것도 채운다.

    "조용하세요, 귀도 좀 어두우시고" 한마디에 두 항목이 동시에 나오는데,
    이걸 못 잡으면 이미 답한 걸 또 물어보게 된다.
    """
    if not slot.get("options"):
        # 자유 서술 항목(성함, 좋아하시는 것 등)은 그대로 저장한다
        return {slot["key"]: text}

    def describe(s: dict) -> str:
        return f"- {s['key']} ({s['question']})\n  고를 수 있는 값: {s['options']}"

    others = "\n".join(
        describe(s) for s in SLOTS
        if s["key"] != slot["key"] and s.get("options") and not answers.get(s["key"])
    )
    prompt = _MAP_PROMPT.format(
        asked=describe(slot),
        others=others or "(없음)",
        text=text,
    )

    try:
        response = await _client.chat.completions.create(
            model=INTERVIEW_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=300,
            extra_body={"provider": {"order": ["groq"]}},
        )
        parsed = _parse_json(response.choices[0].message.content or "")
    except Exception as e:
        logger.warning(f"[interviewer] 답변 매핑 실패, 원문 저장: {type(e).__name__}: {e}")
        return {slot["key"]: text}

    if not isinstance(parsed, dict):
        return {slot["key"]: text}

    # 모델이 선택지 밖의 값을 만들어내는 경우가 있어 정의된 값만 받는다
    clean: dict = {}
    for key, value in parsed.items():
        target = SLOT_BY_KEY.get(key)
        if not target or not isinstance(value, str):
            continue
        if not target.get("options") or value in target["options"]:
            clean[key] = value
    return clean


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


# ──────────────────────────────────────────────────────────────
# 답변 → 프로필
# ──────────────────────────────────────────────────────────────
_HEARING = {
    "아니요, 괜찮으세요": "잘 들으심",
    "조금 크게 트세요": "조금 어두우심",
    "많이 크게 트세요": "많이 어두우심",
}
_MOBILITY = {
    "괜찮으세요": "자유로움",
    "조금 불편해하세요": "불편하심",
    "지팡이를 쓰세요": "지팡이",
    "보행기나 휠체어를 쓰세요": "보행기·휠체어",
}
_MEMORY = {
    "아니요": "또렷하심",
    "가끔 그러세요": "가끔 잊으심",
    "자주 그러세요": "자주 잊으심",
}
_TALKATIVE = {
    "말씀이 많으세요": "많으심",
    "보통이세요": "보통",
    "조용하신 편이에요": "조용하심",
}
_HELP = {
    "편하게 받으세요": "편하게 받으심",
    "괜찮다고 하세요": "사양하시는 편",
    "싫어하세요": "꺼리시는 편",
}


def to_profile(answers: dict) -> dict:
    """인터뷰 답변을 프로필 형태로 옮긴다.

    "모르겠어요"는 값을 넣지 않고 비워둔다 — 틀린 값은 없는 값보다 나쁘다.
    비어 있으면 감지 설정이 안전한 기본값으로 돌지만, 틀리면 민감도를 잘못된
    방향으로 조정한다. (plan §3.3)
    """
    def pick(key: str, table: dict) -> str:
        value = answers.get(key)
        return table.get(value, "") if value else ""

    year = re.search(r"(19|20)\d{2}", str(answers.get("birth_year", "")))
    name = (answers.get("name") or "").strip()
    if name in _NONE_ANSWERS:
        name = ""

    address_as = (answers.get("address_as") or "").strip()
    if address_as in _NONE_ANSWERS:
        address_as = ""
    elif address_as == "성함으로":
        address_as = f"{name} 님".strip() if name else ""

    hearing = pick("hearing", _HEARING)
    # 되묻기는 답을 기록만 하는 게 아니라 값을 바꾼다 — 그게 되물은 이유다.
    # TV를 조금 크게 트시는 데다 되묻는 일까지 잦으면 실제 청력 저하로 본다.
    if hearing == "조금 어두우심" and answers.get("hearing_recheck") == "네, 잦아요":
        hearing = "많이 어두우심"

    # 자녀가 "없다"고 답했어도 멍·부딪힘 정황이 있으면 낙상이 있었던 것으로 본다.
    # 어르신이 넘어진 걸 알리지 않으신 경우다.
    fell = answers.get("fall_history") == "있어요"
    hidden_fall = answers.get("fall_hidden") == "그런 적 있어요"

    # 이 문장들은 페르소나(모델이 읽음)와 온보딩 요약 화면(보호자가 읽음) 양쪽에
    # 그대로 쓰인다. 그래서 "위 6번을 참고해" 같은 내부 참조를 넣지 않는다 —
    # 보호자에게는 무슨 말인지 알 수 없는 소리가 된다.
    notes = []
    if hidden_fall and not fell:
        notes.append("넘어지신 적은 없다고 하시지만 멍이나 부딪힌 정황이 있었습니다. "
                     "말씀하지 않으셨을 수 있으니 자세를 더 주의 깊게 봐야 합니다.")
    if answers.get("talk_change") == "예전보다 줄었어요":
        # 원래 과묵하신 것과 최근 말수가 준 것은 완전히 다른 신호다 (plan §3.1)
        notes.append("예전보다 말수가 줄어드셨습니다. 억지로 밝게 만들려 하지 말고 먼저 듣고 "
                     "공감하되, 기운이 많이 없어 보이시면 보호자에게 알려야 합니다.")
    if answers.get("memory_med") == "네, 그러세요":
        notes.append("약을 드셨는지 기억하지 못하실 때가 있습니다. 다그치거나 되묻지 말고 "
                     "기록을 확인해 대신 알려드려야 합니다.")
    free = (answers.get("free") or "").strip()
    if free and free not in ("없어요", "없습니다", "아니요", "모르겠어요"):
        notes.append(free)

    # 선택지로 옮기지 못한 답변도 보호자가 한 말이므로 버리지 않는다.
    # 감지 설정은 못 바꾸지만 페르소나에는 그대로 들어가 대화에 반영된다.
    for slot in SLOTS:
        raw = (answers.get(f"{slot['key']}__raw") or "").strip()
        if raw:
            notes.append(raw)

    profile = {
        "name": name,
        "birth_year": int(year.group()) if year else None,
        "address_as": address_as or "어르신",
        "lives_alone": answers.get("lives_alone") == "혼자 지내세요",
        "hearing": hearing,
        "mobility": pick("mobility", _MOBILITY),
        "memory": pick("memory", _MEMORY),
        "talkativeness": pick("talkativeness", _TALKATIVE),
        "help_attitude": pick("help_attitude", _HELP),
        "fall_history": fell or hidden_fall,
        "risk_places": _split(answers.get("risk_places", "")) + _split(answers.get("fall_place", "")),
        "interests": _split(answers.get("interests", "")),
        "notes": notes,
    }
    # 답하지 않았거나 모른다고 한 항목 — 틀린 값을 넣지 않고 비워둔 채 기억해서,
    # 프로필 화면의 "아직 안 알려주신 것"으로 나중에 채우게 한다 (plan §3.3)
    profile["unknown"] = [
        s["key"] for s in SLOTS
        if not answers.get(s["key"]) or answers.get(s["key"]) == "모르겠어요"
    ]
    return profile


_NONE_ANSWERS = {"딱히 없어요", "기억이 안 나세요", "없어요", "모르겠어요", "없습니다"}


def _split(text: str) -> list[str]:
    """"화장실이랑 문턱이요" → ["화장실", "문턱"].

    말로 답한 문장이라 쉼표로만 나누면 거의 안 쪼개진다. 접속조사와 문장 끝의
    말버릇("~이요", "~요")까지 걷어내야 페르소나에 넣을 만한 낱말이 남는다.
    """
    if not text or not text.strip() or text.strip() in _NONE_ANSWERS:
        return []
    parts = re.split(r"[,、·/]|이랑|하고|그리고|랑\s|와\s|과\s", text)
    out = []
    for part in parts:
        word = re.sub(r"(이에요|예요|이요|요|입니다|이야)$", "", part.strip()).strip()
        word = word.strip("·. ")
        if word and word not in _NONE_ANSWERS:
            out.append(word)
    return out[:5]
