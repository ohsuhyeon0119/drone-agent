"""관리 콘솔(보호자용) API.

에이전트 런타임(main.py의 /ws/unified)과 같은 프로세스에 얹는다 — 설정 파일을
읽고 쓰는 주체가 하나여야 경쟁 조건이 없고, 배포 직후 메모리 상태를 함께
갱신할 수 있기 때문이다.

인증은 PoC 수준: .env의 ADMIN_EMAIL/ADMIN_PASSWORD 한 계정, 로그인 성공 시
HMAC 토큰을 발급하고 Authorization 헤더로 검증한다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, Header, HTTPException

import accounts
import admin_store
from agent import interviewer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

def require_auth(authorization: str = Header(default="")) -> dict:
    """토큰에서 사용자를 찾아 돌려준다.

    보호자마다 계정이 있고 계정마다 에이전트가 다르므로, 인증은 "맞다/아니다"가
    아니라 **누구인지**를 알아내는 일이다. 이후 모든 조회·수정이 이 사람의
    agent_id로 범위가 좁혀진다.
    """
    token = authorization.removeprefix("Bearer ").strip()
    user_id = accounts.user_id_from_token(token)
    user = accounts.get_user(user_id) if user_id else None
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return user


@router.post("/signup")
async def signup(
    email: str = Body(...), password: str = Body(...), name: str = Body(...),
):
    try:
        user = accounts.signup(email, password, name)
    except accounts.AccountError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "token": accounts.make_token(user["id"]),
            "email": user["email"], "name": user["name"],
            "agent_id": user["agent_id"],
            # 가입 완료 화면에서 바로 보여준다 — 어르신 폰에 넣어야 하는 값이다.
            "pair_code": user["pair_code"]}


@router.post("/login")
async def login(email: str = Body(...), password: str = Body(...)):
    try:
        user = accounts.authenticate(email, password)
    except accounts.AccountError as e:
        raise HTTPException(status_code=401, detail=str(e))
    return {"ok": True, "token": accounts.make_token(user["id"]),
            "email": user["email"], "name": user["name"],
            "agent_id": user["agent_id"]}


@router.get("/me")
async def me(user: dict = Depends(require_auth)):
    """토큰이 아직 유효한지 확인한다.

    콘솔이 화면을 그리기 전에 부른다 — 브라우저에 남아 있는 값만 믿으면
    로그인한 적 없는 사람도 주소만 치면 관리 화면이 열린다.
    """
    # agent_id도 함께 준다 — 노트북을 카메라로 쓸 때 기기가 어느 어르신 곁인지
    # 알려야 하고(/ws/unified?agent=N), 그 값을 화면이 알 방법이 여기밖에 없다.
    # pair_code는 어르신 폰에 넣을 값이라 콘솔이 항상 다시 보여줄 수 있어야 한다.
    return {"ok": True, "email": user["email"], "name": user["name"],
            "agent_id": user["agent_id"],
            "pair_code": admin_store.get_pair_code(user["agent_id"])}


@router.get("/pair-code")
async def pair_code(user: dict = Depends(require_auth)):
    """어르신 폰에 넣을 코드. 가입 화면을 지나친 뒤에도 콘솔에서 다시 볼 수 있어야 한다."""
    return {"pair_code": admin_store.get_pair_code(user["agent_id"])}


@router.post("/pair-code/regenerate")
async def pair_code_regenerate(user: dict = Depends(require_auth)):
    """코드를 새로 발급한다. 기존 코드로 붙어 있던 폰은 다음 연결부터 거부된다."""
    code = admin_store.regenerate_pair_code(user["agent_id"])
    admin_store.log_event("pair_code_regenerated", {"by": user["email"]},
                          agent_id=user["agent_id"])
    return {"ok": True, "pair_code": code}


@router.get("/config")
async def get_config(user: dict = Depends(require_auth)):
    """콘솔이 첫 화면에서 한 번에 받아가는 전체 상태."""
    agent_id = user["agent_id"]
    draft = admin_store.get_draft(agent_id)
    live = admin_store.get_live(agent_id)
    changes = admin_store.diff(draft, live["config"])
    return {
        "draft": draft,
        "live": {"version": live["version"], "published_at": live["published_at"]},
        "changes": changes,
        "versions": admin_store.list_versions(agent_id),
        "builtin_actions": admin_store.BUILTIN_ACTIONS,
    }


@router.put("/draft")
async def put_draft(config: dict = Body(..., embed=True), user: dict = Depends(require_auth)):
    """편집 내용 저장. 내용 오류는 막지 않고 경고만 — 배포 때 최종 검증한다.

    다만 **형태가 아예 다른 것**은 거부한다. 편집 중인 설정을 통째로 덮어쓰는
    경로라, 잘못된 모양을 그대로 저장하면 작업하던 내용이 사라지고 배포도 못 하는
    상태가 된다(요청 형식이 어긋나면 조용히 그렇게 됐다).
    """
    if not any(k in config for k in ("scenarios", "actions", "contacts")):
        raise HTTPException(status_code=400, detail="설정 형식이 올바르지 않습니다.")
    admin_store.save_draft(config, by=user["email"], agent_id=user["agent_id"])
    live = admin_store.get_live(user["agent_id"])
    return {
        "ok": True,
        "changes": admin_store.diff(config, live["config"]),
        "warnings": admin_store.validate(config),
    }


@router.post("/publish")
async def publish(user: dict = Depends(require_auth)):
    result = admin_store.publish(by=user["email"], agent_id=user["agent_id"])
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail={"errors": result["errors"]})
    _apply_live_to_runtime()
    return result


@router.get("/versions/{version}")
async def get_version(version: int, user: dict = Depends(require_auth)):
    """특정 배포 버전의 설정 내용.

    목록(list_versions)은 변경 요약만 주므로, "이 버전을 편집 상태로 불러오기"를
    하려면 내용을 따로 가져와야 한다.
    """
    for v in admin_store.list_versions(user["agent_id"]):
        if v["version"] == version:
            break
    else:
        raise HTTPException(status_code=404, detail="없는 버전입니다.")
    config = admin_store.version_config(version, user["agent_id"])
    if config is None:
        raise HTTPException(status_code=404, detail="없는 버전입니다.")
    return {"version": version, "config": config}


@router.post("/rollback/{version}")
async def rollback(version: int, user: dict = Depends(require_auth)):
    result = admin_store.rollback(version, by=user["email"], agent_id=user["agent_id"])
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail={"errors": result["errors"]})
    _apply_live_to_runtime()
    return result


@router.get("/events")
async def events(limit: int = 100, user: dict = Depends(require_auth)):
    return {"events": admin_store.list_events(limit, user["agent_id"])}


# ──────────────────────────────────────────────────────────────
# 어르신 프로필 / 온보딩 인터뷰
# ──────────────────────────────────────────────────────────────
@router.get("/profile")
async def get_profile(user: dict = Depends(require_auth)):
    """콘솔이 로그인 직후 부른다 — 비어 있으면 온보딩으로 보낸다."""
    profile = admin_store.get_profile(user["agent_id"])
    return {"profile": profile, "onboarded": bool(profile.get("name"))}


@router.put("/profile")
async def put_profile(profile: dict = Body(..., embed=True), user: dict = Depends(require_auth)):
    """프로필은 배포를 거치지 않는다 — 사실을 고치는 데 승인이 필요할 이유가 없다.
    저장 즉시 다음 세션(/ws/unified 재연결)부터 반영된다."""
    admin_store.save_profile(profile, by=user["email"], agent_id=user["agent_id"])
    return {"ok": True, "profile": profile}


@router.get("/onboarding/start")
async def onboarding_start(user: dict = Depends(require_auth)):
    return interviewer.opening()


@router.post("/onboarding/answer")
async def onboarding_answer(
    answers: dict = Body(default={}),
    slot: str = Body(default=""),
    text: str = Body(default=""),
    followup_key: str = Body(default=""),
    user: dict = Depends(require_auth),
):
    """답변 하나를 받아 다음 질문을 돌려준다.

    대화 상태(answers)를 서버에 두지 않고 매번 주고받는다 — 인터뷰는 한 번
    쓰고 버리는 흐름이라 세션 저장소를 만들 이유가 없고, 새로고침해도
    프런트가 들고 있는 상태로 이어갈 수 있다.
    """
    return await interviewer.advance(answers, slot, text, followup_key)


@router.post("/onboarding/finish")
async def onboarding_finish(
    # embed=True가 없으면 FastAPI가 본문 전체를 answers로 본다 — Body 파라미터가
    # 하나뿐일 때의 기본 동작이라, {"answers": {...}}가 통째로 들어가 값이 다 사라진다.
    answers: dict = Body(default={}, embed=True),
    user: dict = Depends(require_auth),
):
    """인터뷰 답변을 프로필로 바꿔 저장한다.

    인터뷰 원문은 저장하지 않는다 — 필요한 건 추출된 사실이고, 건강 관련
    대화를 그대로 쌓아둘 이유가 없다 (요약기와 같은 방침).
    """
    profile = interviewer.to_profile(answers)
    admin_store.save_profile(profile, by=user["email"], agent_id=user["agent_id"])
    return {"ok": True, "profile": profile}


def _apply_live_to_runtime():
    """배포 직후 실행 중인 세션에 반영할 수 있는 것만 반영한다.

    지금은 yaml을 내보내는 것으로 "다음 대화부터" 반영이 보장된다. 대화 중인
    세션에 즉시 반영하는 것(공유 CONFIG 참조 + 지침 주입)은 감지 루프 쪽
    수정이 필요해 다음 단계로 남겨둔다.
    """
    logger.info("[admin_api] 배포 반영: agent/scenarios/*.yaml 갱신됨 (다음 세션부터 적용)")
