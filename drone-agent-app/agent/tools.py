"""Gemini Live에 등록하는 tool(function calling) — 설정 데이터에서 만든다.

이전에는 tool 선언과 구현이 이 파일에 상수로 박혀 있어서, 행동을 추가하려면
코드를 고치고 배포해야 했다. 지금은 관리 콘솔의 설정(actions[])에서 선언을
만들어 세션에 등록한다 — 지침(scenarios/*.yaml)이 이미 그런 것처럼.

두 종류를 구분한다:
  - builtin : 실행 코드가 여기 있어야 하는 것(알림·기록·신고). 콘솔에서는 설명
              문구와 시나리오 연결만 편집한다.
  - webhook : 콘솔에서 주소만 입력하면 되는 것. 범용 실행기 하나가 처리하므로
              코드 수정 없이 얼마든지 추가할 수 있다.

Gemini Live는 tool을 연결 시점에만 고정할 수 있다 — 대화 도중 행동을 추가하면
그 세션이 아니라 다음 대화부터 반영된다.
"""

from __future__ import annotations

import json
import logging
from typing import Callable

logger = logging.getLogger(__name__)

# 파라미터 이름은 한국어 라벨(콘솔 표시용) 대신 모델이 다루기 쉬운 영문 키를 쓴다.
BUILTIN_PARAM_SCHEMA = {
    "notify_caregiver": {
        "type": "OBJECT",
        "properties": {
            "event_type": {"type": "STRING", "description": "감지된 이벤트 종류 (예: fall)"},
            "message": {"type": "STRING", "description": "보호자에게 전달할 상황 요약 (한국어)"},
        },
        "required": ["event_type", "message"],
    },
    "record_medication": {
        "type": "OBJECT",
        "properties": {
            "note": {"type": "STRING", "description": "복용 상황 메모 (한국어)"},
        },
        "required": ["note"],
    },
    "report_119": {
        "type": "OBJECT",
        "properties": {
            "situation": {"type": "STRING", "description": "신고에 포함할 상황 설명 (한국어)"},
        },
        "required": ["situation"],
    },
}

WEBHOOK_PARAM_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "message": {"type": "STRING", "description": "전달할 내용 (한국어)"},
    },
    "required": ["message"],
}


def build_tools(actions: list[dict]) -> list[dict]:
    """설정의 actions[] → Gemini Live에 넘길 tool 선언.

    선언이 하나도 없으면 빈 리스트를 돌려준다(tool 없이 대화만 하는 세션).
    """
    declarations = []
    for a in actions:
        name = a.get("id")
        if not name:
            continue
        params = (BUILTIN_PARAM_SCHEMA.get(name) if a.get("kind") == "builtin"
                  else WEBHOOK_PARAM_SCHEMA)
        if params is None:
            logger.warning(f"[tools] 알 수 없는 내장 행동 '{name}' — 등록하지 않음")
            continue
        declarations.append({
            "name": name,
            "description": a.get("description") or a.get("name") or name,
            "parameters": params,
        })
    return [{"function_declarations": declarations}] if declarations else []


def build_tool_mapping(actions: list[dict], context: dict) -> dict[str, Callable]:
    """tool 이름 → 실제 실행 함수.

    context에는 이 세션의 실행 정보가 담긴다:
      contacts          — 전체 연락처 목록
      contact_ids_by_action — 행동 id별 연락 대상 (시나리오에서 태깅한 것)
      on_event          — 실행 결과를 기록·표시하는 콜백
    """
    mapping: dict[str, Callable] = {}
    for a in actions:
        name = a.get("id")
        if not name:
            continue
        if a.get("kind") == "webhook":
            mapping[name] = _make_webhook_runner(a, context)
        elif name in _BUILTIN_RUNNERS:
            mapping[name] = _BUILTIN_RUNNERS[name](a, context)
    return mapping


def _targets_for(action_id: str, context: dict) -> list[dict]:
    """이 행동의 연락 대상.

    행동 자체에 지정된 대상을 우선한다 ("보호자 알림에는 딸을"처럼 행동 단위로
    정하는 게 자연스럽기 때문). 없으면 이 행동을 쓰는 시나리오에 지정된 대상,
    그것도 없으면 등록된 연락처 전체.
    """
    contacts = {c["id"]: c for c in context.get("contacts", [])}
    for source in (context.get("contact_ids_by_action_own", {}),
                   context.get("contact_ids_by_action", {})):
        ids = source.get(action_id) or []
        targets = [contacts[i] for i in ids if i in contacts]
        if targets:
            return targets
    return list(contacts.values())


def _describe(targets: list[dict]) -> str:
    return ", ".join(f"{t['name']}({t.get('relation', '가족')})" for t in targets)


async def _emit(context: dict, payload: dict):
    on_event = context.get("on_event")
    if on_event:
        await on_event(payload)


# ── 내장 행동 구현 ─────────────────────────────────────────────
def _notify_caregiver(action: dict, context: dict):
    async def run(event_type: str = "", message: str = "") -> str:
        targets = _targets_for(action["id"], context)
        logger.info(f"[TOOL] notify_caregiver event={event_type!r} "
                    f"targets={[t['name'] for t in targets]} message={message!r}")
        await _emit(context, {
            "tool": "notify_caregiver",
            "event_type": event_type,
            "message": message,
            "targets": [{"name": t["name"], "relation": t.get("relation"), "phone": t.get("phone")}
                        for t in targets],
        })
        if not targets:
            # 모델에게 거짓 성공을 돌려주지 않는다 — 그래야 동행이가 사용자에게
            # "연락했어요"라고 잘못 말하지 않고 다른 방법을 안내한다.
            return ("등록된 보호자 연락처가 없어 알리지 못했습니다. "
                    "사용자에게 직접 도움을 요청할 방법을 안내하세요.")
        return f"{_describe(targets)}에게 알림을 전송했습니다."
    return run


def _record_medication(action: dict, context: dict):
    async def run(note: str = "") -> str:
        import memory
        record = memory.record_medication_taken(note=note)
        logger.info(f"[TOOL] record_medication note={note!r}")
        await _emit(context, {"tool": "record_medication", "note": note, "record": record})
        return f"{record['timestamp']} 복용 기록을 남겼습니다."
    return run


def _report_119(action: dict, context: dict):
    async def run(situation: str = "") -> str:
        logger.info(f"[TOOL] report_119 situation={situation!r}")
        await _emit(context, {"tool": "report_119", "situation": situation})
        # 실제 신고 연동은 없다 — 기록만 남기므로 그렇게 말한다.
        return "119 신고가 필요한 상황으로 기록했습니다. 보호자에게도 함께 알리세요."
    return run


_BUILTIN_RUNNERS = {
    "notify_caregiver": _notify_caregiver,
    "record_medication": _record_medication,
    "report_119": _report_119,
}


def _make_webhook_runner(action: dict, context: dict):
    url = (action.get("url") or "").strip()

    async def run(message: str = "") -> str:
        import asyncio
        import urllib.request

        targets = _targets_for(action["id"], context)
        payload = {
            "action": action.get("id"),
            "message": message,
            "targets": [{"name": t["name"], "phone": t.get("phone")} for t in targets],
        }
        await _emit(context, {"tool": action.get("id"), "url": url, "message": message,
                              "targets": payload["targets"]})
        if not url:
            return "연결 주소가 설정되지 않아 실행하지 못했습니다."

        def post():
            req = urllib.request.Request(
                url, data=json.dumps(payload, ensure_ascii=False).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=8) as r:
                return r.status

        try:
            status = await asyncio.get_running_loop().run_in_executor(None, post)
            logger.info(f"[TOOL] webhook {action.get('id')} → {url} ({status})")
            return f"{action.get('name')}을(를) 실행했습니다."
        except Exception as e:
            logger.error(f"[TOOL] webhook 실패 {url}: {type(e).__name__}: {e}")
            return f"{action.get('name')} 실행에 실패했습니다. 다른 방법을 안내하세요."
    return run
