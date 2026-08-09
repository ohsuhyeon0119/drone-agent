"""보호자 계정 (회원가입 / 로그인).

설정과 같은 SQLite 파일을 쓴다 — 계정과 에이전트가 1:1로 묶여 있어서, 둘을
다른 저장소에 두면 가입 도중 실패했을 때 계정만 있고 에이전트는 없는 상태가
생긴다. 한 트랜잭션 안에서 함께 만든다.

비밀번호는 원문으로 저장하지 않는다. 외부 의존성 없이 표준 라이브러리의
pbkdf2_hmac(sha256)을 쓴다 — bcrypt/argon2가 더 낫지만 새 패키지 없이
쓸 수 있는 것 중에서는 이게 적절하다.

토큰에 사용자 id를 담는다. 예전에는 토큰이 이메일의 HMAC 하나뿐이라 "누가
로그인했는지"를 구분할 수 없었고, 그래서 계정이 여러 개일 수 없었다.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime

import admin_store

logger = logging.getLogger(__name__)

_SECRET = os.getenv("ADMIN_SECRET", "donghaeng-console-secret")

PBKDF2_ROUNDS = 200_000
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 8

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  email         TEXT NOT NULL UNIQUE,
  name          TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  agent_id      INTEGER NOT NULL,
  created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
"""


class AccountError(Exception):
    """가입/로그인 실패 — 사용자에게 그대로 보여줄 수 있는 메시지를 담는다."""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _connect() -> sqlite3.Connection:
    os.makedirs(admin_store.DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(admin_store.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with closing(_connect()) as conn, conn:
        conn.executescript(SCHEMA)


# ──────────────────────────────────────────────────────────────
# 비밀번호
# ──────────────────────────────────────────────────────────────
def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_hex, digest_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


# ──────────────────────────────────────────────────────────────
# 토큰
# ──────────────────────────────────────────────────────────────
def make_token(user_id: int) -> str:
    """`<user_id>.<서명>` — 서버가 서명으로 위조를 걸러낸다.

    만료가 없다는 점은 그대로 남는 한계다(PoC). 서명이 없으면 사용자 id만
    바꿔서 남의 계정으로 들어갈 수 있으므로 서명은 반드시 필요하다.
    """
    sig = hmac.new(_SECRET.encode(), str(user_id).encode(), hashlib.sha256).hexdigest()
    return f"{user_id}.{sig}"


def user_id_from_token(token: str) -> int | None:
    if not token or "." not in token:
        return None
    raw_id, _, sig = token.partition(".")
    if not raw_id.isdigit():
        return None
    expected = hmac.new(_SECRET.encode(), raw_id.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    return int(raw_id)


# ──────────────────────────────────────────────────────────────
# 가입 / 조회
# ──────────────────────────────────────────────────────────────
def _validate(email: str, password: str, name: str):
    if not EMAIL_RE.match(email):
        raise AccountError("이메일 형식이 올바르지 않습니다.")
    if len(password) < MIN_PASSWORD:
        raise AccountError(f"비밀번호는 {MIN_PASSWORD}자 이상이어야 합니다.")
    if not name.strip():
        raise AccountError("이름을 입력해 주세요.")


def signup(email: str, password: str, name: str) -> dict:
    """계정과 그 계정 전용 에이전트를 함께 만든다.

    보호자마다 돌보는 어르신이 다르므로 프로필·시나리오·연락처가 섞이면 안 된다.
    가입 시점에 에이전트를 하나 만들고, 이후 모든 설정은 그 에이전트에 붙는다.
    """
    email = (email or "").strip().lower()
    name = (name or "").strip()
    _validate(email, password, name)

    with closing(_connect()) as conn, conn:
        exists = conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone()
        if exists:
            raise AccountError("이미 가입된 이메일입니다.")

        cur = conn.execute(
            "INSERT INTO agents (name, created_at) VALUES (?, ?)",
            (f"{name}님의 에이전트", _now()),
        )
        agent_id = cur.lastrowid
        cur = conn.execute(
            """INSERT INTO users (email, name, password_hash, agent_id, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (email, name, hash_password(password), agent_id, _now()),
        )
        user_id = cur.lastrowid
        admin_store.seed_agent(conn, agent_id)

    logger.info(f"[accounts] 가입: {email} (agent_id={agent_id})")
    return {"id": user_id, "email": email, "name": name, "agent_id": agent_id}


def authenticate(email: str, password: str) -> dict:
    email = (email or "").strip().lower()
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT id, email, name, password_hash, agent_id FROM users WHERE email=?",
            (email,),
        ).fetchone()
    # 계정이 없을 때도 해시 검증을 한 번 돌려, 응답 시간으로 가입 여부를
    # 알아내지 못하게 한다.
    stored = row["password_hash"] if row else hash_password("dummy")
    if not verify_password(password, stored) or not row:
        raise AccountError("이메일 또는 비밀번호가 올바르지 않습니다.")
    return {"id": row["id"], "email": row["email"], "name": row["name"],
            "agent_id": row["agent_id"]}


def get_user(user_id: int) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT id, email, name, agent_id FROM users WHERE id=?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def count_users() -> int:
    with closing(_connect()) as conn:
        return conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
