"""구조화된 시나리오(감지 + 지침) 정의와 로더.

시나리오는 "무엇을 감지하고(detect_prompt), 얼마나 자주 재판정하고(cooldown),
감지되면 에이전트에게 뭐라고 알리고(nudge_template), 에이전트는 어떻게
대응해야 하는지(instructions)"를 하나로 묶은 단위다. 향후 관리 화면에서
시나리오별 지침을 추가/삭제하는 기능을 지원하기 위해, 이 정의를
`agent/scenarios/<key>.yaml` 파일로 오버라이드할 수 있게 했다.

파일이 없거나 읽는 데 실패하면 DEFAULT_SCENARIOS(기존에 main.py/persona.py에
하드코딩돼 있던 값 그대로)로 동작한다 — 즉 아무 설정 파일도 만들지 않으면
지금까지와 완전히 동일하게 돈다.
"""

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

SCENARIOS_ROOT = Path(__file__).parent / "scenarios"


def scenarios_dir(agent_id: int = 1) -> Path:
    """에이전트별 시나리오 디렉토리. 보호자마다 계정이 있으므로 섞이면 안 된다."""
    return SCENARIOS_ROOT / str(agent_id)

# 기존에 main.py(FALL_DETECT_PROMPT 등)와 persona.py(UNIFIED_PERSONA 문구)에
# 하드코딩돼 있던 내용을 그대로 옮긴 기본값. agent/scenarios/<key>.yaml이
# 없으면 이 값이 쓰인다.
DEFAULT_SCENARIOS = {
    "fall": {
        "key": "fall",
        "name": "낙상 감지",
        "target_event": "fall",
        "cooldown": 10.0,
        "min_confidence": 0.7,
        "detect_prompt": (
            "이 이미지를 보고 사람이 엎드려 있거나 넘어져 있는지 감지하라.\n"
            "반드시 아래 JSON 형식으로만 답하라, 코드펜스 금지:\n"
            '{"event": "fall" 또는 "none", "confidence": 0.0~1.0, '
            '"reason": "판단 근거를 한 문장으로"}\n'
        ),
        "nudge_template": (
            "[SYSTEM] 카메라 영상에서 사용자가 방금 쓰러지는 것이 감지되었습니다. "
            "지금 하던 대화를 멈추고 걱정스러운 톤으로 '괜찮으세요?'라고 즉시 물어보세요."
        ),
        "instructions": [
            {"text": '쓰러짐이 감지되면 즉시 걱정스러운 톤으로 "괜찮으세요?"라고 물어봅니다.'},
            {"text": "사용자가 괜찮지 않다고 답하거나 응답이 없으면 보호자에게 알립니다.",
             "action": "notify_caregiver"},
            {"text": "사용자가 명확히 괜찮다고 답하면 신고하지 않고 안심시키는 말로 마무리합니다."},
        ],
    },
    "medication": {
        "key": "medication",
        "name": "복약 확인",
        "target_event": "taken",
        "cooldown": 15.0,
        "min_confidence": 0.7,
        "detect_prompt": (
            "이 이미지를 보고 사람이 알약, 약봉투, 약통, 물컵을 손에 들고 있거나\n"
            "입 근처로 가져가 약을 복용하는 동작을 하고 있는지 감지하라.\n"
            "반드시 아래 JSON 형식으로만 답하라, 코드펜스 금지:\n"
            '{"event": "taken" 또는 "none", "confidence": 0.0~1.0, '
            '"reason": "판단 근거를 한 문장으로"}\n'
        ),
        "nudge_template": (
            "[SYSTEM] 방금 카메라로 사용자가 약을 복용하는 모습이 확인되었습니다. "
            "잘하셨다고 따뜻하게 칭찬하고 격려해주세요."
        ),
        "instructions": [
            {"text": "복약 시간 신호를 받으면 처방 정보를 바탕으로 먼저 다정하게 복용을 권합니다."},
            {"text": '카메라로 복용이 확인되면 "잘하셨어요!"처럼 따뜻하게 칭찬합니다.'},
            {"text": "아직 복용하지 않았다면 다그치지 않고 부드럽게 다시 권유합니다."},
            {"text": "어르신이 약을 드셨다고 말씀하시면 기록을 남깁니다.",
             "action": "record_medication"},
        ],
    },
}


def _load_override(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError("scenario yaml must be a mapping")
        return data
    except Exception as e:
        logger.warning(f"[scenarios] {path} 로드 실패, 기본값 사용: {type(e).__name__}: {e}")
        return None


def load_scenarios(agent_id: int = 1) -> dict:
    """key -> 시나리오 dict.

    디렉토리를 훑어서 읽는다 — 기본값 키만 순회하면 관리 화면에서 새로 만든
    시나리오(예: intrusion.yaml)가 영영 로드되지 않는다. 기본값은 파일이 없거나
    깨졌을 때의 안전망 역할만 한다.

    파일이 하나도 없으면(첫 실행) 기본값을 그대로 쓴다.
    """
    scenarios = {key: dict(default) for key, default in DEFAULT_SCENARIOS.items()}

    directory = scenarios_dir(agent_id)
    found = sorted(directory.glob("*.yaml")) if directory.exists() else []
    if not found:
        return scenarios

    # 파일이 있으면 그 목록이 곧 시나리오 목록이다 (콘솔에서 지운 것이 되살아나지 않게)
    loaded: dict = {}
    for path in found:
        key = path.stem
        override = _load_override(path)
        if override is None:
            # 형식이 깨진 파일 — 기본값이 있으면 그것으로, 없으면 건너뛴다
            if key in DEFAULT_SCENARIOS:
                loaded[key] = dict(DEFAULT_SCENARIOS[key])
            continue
        base = DEFAULT_SCENARIOS.get(key, {"key": key, "name": key, "target_event": "event"})
        loaded[key] = {**base, **override}
    return loaded or scenarios
