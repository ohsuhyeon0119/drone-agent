"""관리 콘솔(보호자용) API.

에이전트 런타임(main.py의 /ws/unified)과 같은 프로세스에 얹는다 — 설정 파일을
읽고 쓰는 주체가 하나여야 경쟁 조건이 없고, 배포 직후 메모리 상태를 함께
갱신할 수 있기 때문이다.

인증은 PoC 수준: .env의 ADMIN_EMAIL/ADMIN_PASSWORD 한 계정, 로그인 성공 시
HMAC 토큰을 발급하고 Authorization 헤더로 검증한다.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os

from fastapi import APIRouter, Body, Depends, Header, HTTPException

import admin_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@donghaeng.kr")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "donghaeng")
_SECRET = os.getenv("ADMIN_SECRET", "donghaeng-console-secret")


def _token_for(email: str) -> str:
    return hmac.new(_SECRET.encode(), email.encode(), hashlib.sha256).hexdigest()


def require_auth(authorization: str = Header(default="")) -> str:
    token = authorization.removeprefix("Bearer ").strip()
    if not token or not hmac.compare_digest(token, _token_for(ADMIN_EMAIL)):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return ADMIN_EMAIL


@router.post("/login")
async def login(email: str = Body(...), password: str = Body(...)):
    ok = hmac.compare_digest(email.strip().lower(), ADMIN_EMAIL.lower()) and \
        hmac.compare_digest(password, ADMIN_PASSWORD)
    if not ok:
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")
    return {"ok": True, "token": _token_for(ADMIN_EMAIL), "email": ADMIN_EMAIL}


@router.get("/config")
async def get_config(_: str = Depends(require_auth)):
    """콘솔이 첫 화면에서 한 번에 받아가는 전체 상태."""
    draft = admin_store.get_draft()
    live = admin_store.get_live()
    changes = admin_store.diff(draft, live["config"])
    return {
        "draft": draft,
        "live": {"version": live["version"], "published_at": live["published_at"]},
        "changes": changes,
        "versions": admin_store.list_versions(),
        "builtin_actions": admin_store.BUILTIN_ACTIONS,
    }


@router.put("/draft")
async def put_draft(config: dict = Body(...), user: str = Depends(require_auth)):
    """편집 내용 저장. 저장 단계에서는 막지 않고 경고만 — 배포 때 최종 검증한다."""
    admin_store.save_draft(config, by=user)
    live = admin_store.get_live()
    return {
        "ok": True,
        "changes": admin_store.diff(config, live["config"]),
        "warnings": admin_store.validate(config),
    }


@router.post("/publish")
async def publish(user: str = Depends(require_auth)):
    result = admin_store.publish(by=user)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail={"errors": result["errors"]})
    _apply_live_to_runtime()
    return result


@router.post("/rollback/{version}")
async def rollback(version: int, user: str = Depends(require_auth)):
    result = admin_store.rollback(version, by=user)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail={"errors": result["errors"]})
    _apply_live_to_runtime()
    return result


@router.get("/events")
async def events(limit: int = 100, _: str = Depends(require_auth)):
    return {"events": admin_store.list_events(limit)}


def _apply_live_to_runtime():
    """배포 직후 실행 중인 세션에 반영할 수 있는 것만 반영한다.

    지금은 yaml을 내보내는 것으로 "다음 대화부터" 반영이 보장된다. 대화 중인
    세션에 즉시 반영하는 것(공유 CONFIG 참조 + 지침 주입)은 감지 루프 쪽
    수정이 필요해 다음 단계로 남겨둔다.
    """
    logger.info("[admin_api] 배포 반영: agent/scenarios/*.yaml 갱신됨 (다음 세션부터 적용)")
