"""Gemini Live에 등록하는 tool(function calling) 정의."""

import logging

logger = logging.getLogger(__name__)

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
