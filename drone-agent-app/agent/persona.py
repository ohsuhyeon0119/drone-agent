"""동행이의 페르소나(시스템 지침)를 구성한다.

시나리오별 대응 지침(낙상이면 어떻게, 복약이면 어떻게)은 더 이상 여기 문자열로
박혀 있지 않고 `agent/scenarios.py`(→ `agent/scenarios/<key>.yaml`)에서 온다.
관리 화면에서 지침을 추가/삭제하는 기능은 결국 그 yaml 파일을 고치는 것이고,
파일이 없거나 잘못돼도 `scenarios.py`의 DEFAULT_SCENARIOS로 안전하게 대체되므로
이 모듈이 만드는 UNIFIED_PERSONA는 항상 지금까지와 동일한 방식으로 동작한다.
"""

from agent.scenarios import load_scenarios

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


def _render_scenario_block(index: int, scenario: dict) -> str:
    bullets = "\n".join(f"   - {line}" for line in scenario["instructions"])
    return f"{index}. {scenario['name']} 신호를 받으면:\n{bullets}"


def build_unified_persona(scenarios: dict) -> str:
    """PERSONA_BASE + 시나리오별 지침을 하나의 시스템 프롬프트로 합친다.

    어떤 [SYSTEM] 신호가 오든 그때그때 알아서 대응하고, 아무 신호가 없을 때는
    자유로운 대화/작업 보조 역할을 한다는 큰 틀은 그대로 두고, 시나리오
    지침 부분만 `scenarios`(agent/scenarios.py, yaml로 오버라이드 가능)에서
    가져와 번호를 매겨 채워 넣는다.
    """
    blocks = [_render_scenario_block(i, s) for i, s in enumerate(scenarios.values(), start=1)]
    other_index = len(blocks) + 1
    return (
        PERSONA_BASE
        + "\n\n당신은 아래 상황들을 동시에 대비합니다 — 무슨 상황인지는 당신이 미리 아는 게 "
        "아니라, 그때그때 받는 [SYSTEM] 신호로 알게 됩니다:\n\n"
        + "\n\n".join(blocks)
        + f"\n\n{other_index}. 그 외에는: 평소처럼 자유롭게 대화하거나, 사용자가 화면·물건에 대해 "
        "물어보면 카메라로 보이는 것을 근거로 쉽고 친절하게 설명해주세요.\n\n"
        "여러 신호가 겹치면 더 급한 것(낙상)을 우선하세요."
    )


SCENARIOS = load_scenarios()
UNIFIED_PERSONA = build_unified_persona(SCENARIOS)

# main.py의 감지 루프가 쓰는 값들 — 지금은 SCENARIOS에서 그대로 뽑아 쓰지만,
# 하위 호환을 위해 이름은 유지한다.
FALL_DETECT_PROMPT = SCENARIOS["fall"]["detect_prompt"]
MEDICATION_DETECT_PROMPT = SCENARIOS["medication"]["detect_prompt"]
