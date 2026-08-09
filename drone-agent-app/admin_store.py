"""에이전트 설정의 버전 관리 저장소 (SQLite).

설계 원칙:
  - 진실의 원천은 이 DB. 에이전트 런타임이 읽는 파일(agent/scenarios/*.yaml,
    config/live.json)은 배포 시 DB에서 내보내는 산출물이다.
  - 배포된 버전(config_versions)은 불변 — UPDATE/DELETE 하지 않는다.
    롤백도 "예전 스냅샷을 새 버전으로 다시 배포"하는 방식이라 이력이 선형으로 남는다.
  - 델타가 아니라 전체 스냅샷을 저장한다 (설정이 수 KB라 저장 비용이 무의미하고
    복원이 단순하다).
  - 검증은 저장 전에. 실패하면 배포를 거부한다 — yaml이 깨졌을 때 조용히
    기본값으로 폴백하는 기존 동작(편집자가 "적용됐다"고 착각하는 최악의 실패)을
    콘솔 경로에서는 허용하지 않는다.

설정 번들 스키마:
  {
    "scenarios": [{key, name, enabled, detect_prompt, cooldown, min_confidence,
                   nudge_template, instructions[]}],
    "actions":   [{id, name, description, params[], kind, url?, needs_contacts,
                   notify_contact_ids[]}],
    "contacts":  [{id, name, relation, phone}]
  }

지침(instructions)은 {text, action?} 형태다. 행동은 시나리오가 아니라 **개별
지침**에 붙는다 — "낙상 시나리오가 알림을 보낸다"가 아니라 "응답이 없을 때라는
지침이 알림을 보낸다"가 실제 구조이기 때문이다. 모든 지침에 행동이 붙을 필요는
없다(대부분은 말하는 방식에 대한 것이다). 연락 대상은 행동에만 둔다 — 같은 값이
두 곳에 있으면 어느 쪽이 맞는지 알 수 없어진다.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime

import yaml

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.getenv("ADMIN_DB_PATH", os.path.join(DATA_DIR, "console.db"))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
SCENARIOS_ROOT = os.path.join(BASE_DIR, "agent", "scenarios")

DEFAULT_AGENT_ID = 1


def scenarios_dir(agent_id: int = DEFAULT_AGENT_ID) -> str:
    """에이전트별 시나리오 디렉토리.

    보호자마다 계정이 생기면서 한 디렉토리를 공유할 수 없게 됐다 — 두 계정이
    배포하면 서로의 yaml을 덮어쓴다. agent_id로 나눠 담는다.
    """
    return os.path.join(SCENARIOS_ROOT, str(agent_id))


def live_json_path(agent_id: int = DEFAULT_AGENT_ID) -> str:
    return os.path.join(CONFIG_DIR, f"live-{agent_id}.json")

# 에이전트가 실제로 실행할 수 있는 내장 행동. 콘솔에서 임의로 만들 수 있는 것은
# 웹훅(kind="webhook")뿐이고, 내장 행동은 코드에 구현체가 있어야 하므로 목록이 고정이다.
BUILTIN_ACTIONS = [
    {
        "id": "notify_caregiver",
        "name": "보호자 알림",
        "description": "낙상 등 위급 상황이 감지되어 보호자에게 알려야 할 때",
        "params": [
            {"name": "상황 종류", "desc": "감지된 상황의 종류"},
            {"name": "전달 내용", "desc": "보호자에게 전달할 요약"},
        ],
        "kind": "builtin",
        "needs_contacts": True,
        "notify_contact_ids": [],
    },
    {
        # 카메라로 확인된 복용은 감지 루프가 직접 기록하므로, 이 행동은 사용자가
        # "약 먹었어요"라고 말로 알렸을 때를 위한 것이다 (중복 기록 방지).
        "id": "record_medication",
        "name": "복약 기록",
        "description": "사용자가 약을 먹었다고 말로 알렸을 때 기록을 남깁니다. "
                       "카메라로 이미 확인된 경우에는 호출하지 마세요.",
        "params": [{"name": "기록 내용", "desc": "남길 내용"}],
        "kind": "builtin",
        "needs_contacts": False,
    },
]

SCHEMA = """
-- pair_code: 어르신 폰(앱)이 입력하는 6자 코드. 보호자 로그인과 별개다 —
-- 어르신에게 이메일·비밀번호를 치게 할 수는 없기 때문이다.
CREATE TABLE IF NOT EXISTS agents (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  pair_code   TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_pair_code
  ON agents(pair_code) WHERE pair_code IS NOT NULL;

-- 배포된 버전 = 불변 스냅샷
CREATE TABLE IF NOT EXISTS config_versions (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_id          INTEGER NOT NULL REFERENCES agents(id),
  version           INTEGER NOT NULL,
  config_json       TEXT NOT NULL,
  changes_json      TEXT NOT NULL,
  published_at      TEXT NOT NULL,
  published_by      TEXT,
  rolled_back_from  INTEGER,
  UNIQUE (agent_id, version)
);

-- 편집 중 (agent당 1행)
CREATE TABLE IF NOT EXISTS config_drafts (
  agent_id    INTEGER PRIMARY KEY REFERENCES agents(id),
  config_json TEXT NOT NULL,
  updated_at  TEXT NOT NULL,
  updated_by  TEXT
);

-- 어르신 프로필 (agent당 1행)
--
-- config_versions에 넣지 않는다. 프로필은 "설정"이 아니라 "사실"이라서,
-- 귀가 어두우시다는 걸 뒤늦게 알고 고칠 때 배포 승인을 거치게 하면 안 된다.
-- 저장 즉시 다음 세션부터 반영되고, 변경 이력은 events에 남긴다.
CREATE TABLE IF NOT EXISTS profiles (
  agent_id     INTEGER PRIMARY KEY REFERENCES agents(id),
  profile_json TEXT NOT NULL,
  updated_at   TEXT NOT NULL,
  updated_by   TEXT
);

-- 활동 로그 (append only)
CREATE TABLE IF NOT EXISTS events (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_id     INTEGER NOT NULL,
  ts           TEXT NOT NULL,
  kind         TEXT NOT NULL,
  payload_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_agent_ts ON events(agent_id, ts);
"""


def normalize_instructions(raw) -> list[dict]:
    """지침을 {text, action} 형태로 맞춘다.

    예전 설정은 지침이 문자열 리스트였다. 저장된 값을 그대로 두면 화면과 페르소나
    양쪽에서 형태를 매번 따져야 하므로, 읽는 지점에서 한 번 정규화한다.
    """
    out: list[dict] = []
    for item in raw or []:
        if isinstance(item, str):
            out.append({"text": item, "action": None})
        elif isinstance(item, dict) and item.get("text"):
            out.append({"text": item["text"], "action": item.get("action") or None})
    return out


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _connect() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


class _BlockDumper(yaml.SafeDumper):
    """여러 줄 문자열을 블록 스타일(|)로 내보낸다 — 감지 프롬프트가 한 줄로
    뭉쳐서 사람이 읽을 수 없게 되는 것을 막기 위함."""


def _str_representer(dumper, data):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_BlockDumper.add_representer(str, _str_representer)


def _write_atomic(path: str, text: str):
    """반쯤 쓰인 파일을 에이전트가 읽는 사고를 막는다."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


# ──────────────────────────────────────────────────────────────
# 초기화 / 이관
# ──────────────────────────────────────────────────────────────
def _bundle_from_defaults() -> dict:
    """새로 가입한 계정이 시작할 기본 설정. 파일이 아니라 코드 기본값에서 만든다."""
    from agent.scenarios import DEFAULT_SCENARIOS

    return _bundle_from(DEFAULT_SCENARIOS)


def _bundle_from_yaml() -> dict:
    """기존 agent/scenarios/1/*.yaml을 읽어 초기 설정 번들(v1)을 만든다."""
    from agent.scenarios import load_scenarios

    return _bundle_from(load_scenarios(DEFAULT_AGENT_ID))


def _bundle_from(source: dict) -> dict:
    scenarios = []
    for key, s in source.items():
        scenarios.append({
            "key": key,
            "name": s.get("name", key),
            "enabled": True,
            "detect_prompt": s.get("detect_prompt", ""),
            "cooldown": float(s.get("cooldown", 10.0)),
            "min_confidence": float(s.get("min_confidence", 0.7)),
            "nudge_template": s.get("nudge_template", ""),
            "instructions": normalize_instructions(s.get("instructions")),
            "target_event": s.get("target_event", "event"),
        })
    return {
        "scenarios": scenarios,
        "actions": [dict(a) for a in BUILTIN_ACTIONS],
        "contacts": [],
    }


def _migrate_flat_scenarios():
    """예전 구조(agent/scenarios/*.yaml)를 agent/scenarios/1/로 옮긴다.

    계정마다 에이전트가 생기면서 시나리오 파일을 agent_id 하위로 나눴다.
    이미 돌고 있던 설치본의 파일이 사라지면 기본값으로 되돌아가 버리므로,
    한 번만 옮겨준다.
    """
    if not os.path.isdir(SCENARIOS_ROOT):
        return
    stray = [n for n in os.listdir(SCENARIOS_ROOT) if n.endswith(".yaml")]
    if not stray:
        return
    target = scenarios_dir(DEFAULT_AGENT_ID)
    os.makedirs(target, exist_ok=True)
    for name in stray:
        os.replace(os.path.join(SCENARIOS_ROOT, name), os.path.join(target, name))
    logger.info(f"[admin_store] 시나리오 파일 {len(stray)}개를 agent/scenarios/1/로 이관")


def seed_agent(conn: sqlite3.Connection, agent_id: int, source: dict | None = None):
    """새 에이전트에 초기 설정(v1)과 draft를 만들어준다.

    가입 직후 설정이 하나도 없으면 콘솔이 빈 화면이 되고, 배포할 것도 없어서
    무엇부터 해야 할지 알 수 없다. 기본 시나리오를 깔아둔 상태로 시작한다.
    """
    row = conn.execute(
        "SELECT COUNT(*) c FROM config_versions WHERE agent_id=?", (agent_id,)
    ).fetchone()
    if row["c"]:
        return
    bundle = source if source is not None else _bundle_from_defaults()
    payload = json.dumps(bundle, ensure_ascii=False)
    conn.execute(
        """INSERT INTO config_versions
           (agent_id, version, config_json, changes_json, published_at, published_by)
           VALUES (?, 1, ?, ?, ?, ?)""",
        (agent_id, payload,
         # 변경 목록은 항상 {text, tier} 형태 — 콘솔이 한 가지 형식만 다루게 한다
         json.dumps([{"text": "초기 설정", "tier": "instant"}], ensure_ascii=False),
         _now(), "system"),
    )
    conn.execute(
        """INSERT INTO config_drafts (agent_id, config_json, updated_at, updated_by)
           VALUES (?, ?, ?, ?)""",
        (agent_id, payload, _now(), "system"),
    )
    _export_live(conn, agent_id)
    logger.info(f"[admin_store] agent {agent_id} 초기 설정 생성")


def init_db():
    """테이블 생성 + 최초 실행 시 yaml에서 v1 스냅샷 이관."""
    _migrate_flat_scenarios()
    with closing(_connect()) as conn, conn:
        _migrate_pair_code(conn)
        conn.executescript(SCHEMA)
        row = conn.execute("SELECT COUNT(*) c FROM agents").fetchone()
        if row["c"] == 0:
            conn.execute(
                "INSERT INTO agents (id, name, created_at) VALUES (?, ?, ?)",
                (DEFAULT_AGENT_ID, "기본 에이전트", _now()),
            )
        seed_agent(conn, DEFAULT_AGENT_ID, source=_bundle_from_yaml())

        # 기존 에이전트들의 내보내기 파일을 최신 상태로 맞춘다
        for r in conn.execute("SELECT DISTINCT agent_id FROM config_versions").fetchall():
            _export_live(conn, r["agent_id"])

        # 코드가 없는 에이전트(마이그레이션 이전에 만들어진 것)에 하나씩 채운다
        for r in conn.execute(
            "SELECT id FROM agents WHERE pair_code IS NULL OR pair_code=''"
        ).fetchall():
            ensure_pair_code(conn, r["id"])


# ──────────────────────────────────────────────────────────────
# 페어링 코드 — 어르신 폰이 입력하는 6자
# ──────────────────────────────────────────────────────────────
# 눈으로 읽고 손으로 옮겨 적는 코드라 헷갈리는 글자를 뺀다: I/1/L, O/0.
PAIR_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
PAIR_CODE_LENGTH = 6


def _migrate_pair_code(conn: sqlite3.Connection):
    """이미 만들어진 agents 테이블에 컬럼을 덧붙인다 (CREATE TABLE IF NOT EXISTS는
    기존 테이블을 고치지 않는다)."""
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(agents)").fetchall()}
    if columns and "pair_code" not in columns:
        conn.execute("ALTER TABLE agents ADD COLUMN pair_code TEXT")
        logger.info("[admin_store] agents.pair_code 컬럼 추가")


def _random_pair_code() -> str:
    return "".join(secrets.choice(PAIR_CODE_ALPHABET) for _ in range(PAIR_CODE_LENGTH))


def ensure_pair_code(conn: sqlite3.Connection, agent_id: int) -> str:
    """이미 있으면 그대로, 없으면 유일한 코드를 만들어 저장하고 돌려준다."""
    row = conn.execute("SELECT pair_code FROM agents WHERE id=?", (agent_id,)).fetchone()
    if row and row["pair_code"]:
        return row["pair_code"]

    for _ in range(20):
        code = _random_pair_code()
        taken = conn.execute("SELECT 1 FROM agents WHERE pair_code=?", (code,)).fetchone()
        if taken:
            continue
        conn.execute("UPDATE agents SET pair_code=? WHERE id=?", (code, agent_id))
        logger.info(f"[admin_store] agent {agent_id} 페어링 코드 발급")
        return code
    raise RuntimeError("페어링 코드를 생성하지 못했습니다.")


def get_pair_code(agent_id: int) -> str | None:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT pair_code FROM agents WHERE id=?", (agent_id,)).fetchone()
    return row["pair_code"] if row else None


def regenerate_pair_code(agent_id: int) -> str:
    """코드가 유출됐을 때 새로 발급한다. 기존 코드로 페어링한 기기는 즉시 무효가 된다."""
    with closing(_connect()) as conn, conn:
        conn.execute("UPDATE agents SET pair_code=NULL WHERE id=?", (agent_id,))
        return ensure_pair_code(conn, agent_id)


def agent_by_pair_code(code: str) -> dict | None:
    """코드로 에이전트를 찾는다. 대소문자·공백·하이픈은 무시한다."""
    normalized = (code or "").strip().upper().replace("-", "").replace(" ", "")
    if not normalized:
        return None
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT id, name FROM agents WHERE pair_code=?", (normalized,)
        ).fetchone()
    return {"agent_id": row["id"], "agent_name": row["name"]} if row else None


# ──────────────────────────────────────────────────────────────
# 어르신 프로필
# ──────────────────────────────────────────────────────────────
def get_profile(agent_id: int = DEFAULT_AGENT_ID) -> dict:
    """저장된 프로필. 아직 없으면 빈 dict.

    빈 dict를 돌려주는 게 중요하다 — 온보딩을 건너뛴 사용자도 페르소나가
    지금과 똑같이 조립돼야 하고, 호출부가 없음을 따로 처리하지 않아도 되게.
    """
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT profile_json FROM profiles WHERE agent_id=?", (agent_id,)
        ).fetchone()
    if not row:
        return {}
    try:
        data = json.loads(row["profile_json"])
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        logger.warning("[admin_store] 프로필 JSON이 깨져 빈 값으로 대체")
        return {}


def save_profile(profile: dict, by: str | None = None,
                 agent_id: int = DEFAULT_AGENT_ID) -> dict:
    """프로필을 통째로 저장한다 (부분 수정은 호출부에서 병합한 뒤 넘긴다)."""
    payload = json.dumps(profile, ensure_ascii=False)
    with closing(_connect()) as conn, conn:
        conn.execute(
            """INSERT INTO profiles (agent_id, profile_json, updated_at, updated_by)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(agent_id) DO UPDATE SET
                 profile_json=excluded.profile_json,
                 updated_at=excluded.updated_at,
                 updated_by=excluded.updated_by""",
            (agent_id, payload, _now(), by),
        )
    log_event("profile.updated", {"name": profile.get("name", "")}, agent_id)
    return profile


# ──────────────────────────────────────────────────────────────
# 검증
# ──────────────────────────────────────────────────────────────
PHONE_RE = re.compile(r"^01[0-9]-?\d{3,4}-?\d{4}$")


def validate(bundle: dict) -> list[str]:
    """설정 번들을 검증해 오류 메시지 목록을 돌려준다 (빈 목록 = 통과)."""
    errors: list[str] = []
    if not isinstance(bundle, dict):
        return ["설정 형식이 올바르지 않습니다."]

    actions = bundle.get("actions")
    if not isinstance(actions, list):
        errors.append("행동 목록이 없습니다.")
        actions = []
    action_ids = set()
    for i, a in enumerate(actions):
        label = f"행동 {i + 1}"
        if not isinstance(a, dict):
            errors.append(f"{label}: 형식이 올바르지 않습니다.")
            continue
        if not str(a.get("id", "")).strip():
            errors.append(f"{label}: 식별자가 비어 있습니다.")
        if not str(a.get("name", "")).strip():
            errors.append(f"{label}: 이름이 비어 있습니다.")
        if not str(a.get("description", "")).strip():
            errors.append(f"{a.get('name', label)}: 실행 조건이 비어 있습니다.")
        if a.get("kind") == "webhook" and not str(a.get("url", "")).strip().startswith("http"):
            errors.append(f"{a.get('name', label)}: 연결 주소가 http로 시작해야 합니다.")
        for cid in a.get("notify_contact_ids") or []:
            if cid not in {c.get("id") for c in (bundle.get("contacts") or [])}:
                errors.append(f"{a.get('name', label)}: 연락 대상 중 삭제된 연락처가 있습니다.")
                break
        action_ids.add(a.get("id"))

    contacts = bundle.get("contacts")
    if not isinstance(contacts, list):
        errors.append("연락처 목록이 없습니다.")
        contacts = []
    contact_ids = set()
    for i, c in enumerate(contacts):
        label = f"연락처 {i + 1}"
        if not isinstance(c, dict):
            errors.append(f"{label}: 형식이 올바르지 않습니다.")
            continue
        if not str(c.get("name", "")).strip():
            errors.append(f"{label}: 이름이 비어 있습니다.")
        if not PHONE_RE.match(str(c.get("phone", "")).strip()):
            errors.append(f"{c.get('name', label)}: 전화번호 형식이 올바르지 않습니다.")
        contact_ids.add(c.get("id"))

    scenarios = bundle.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        errors.append("시나리오가 하나도 없습니다.")
        scenarios = []
    seen_keys = set()
    for i, s in enumerate(scenarios):
        label = f"시나리오 {i + 1}"
        if not isinstance(s, dict):
            errors.append(f"{label}: 형식이 올바르지 않습니다.")
            continue
        name = s.get("name", label)
        key = str(s.get("key", "")).strip()
        if not re.fullmatch(r"[a-z0-9_]+", key or ""):
            errors.append(f"{name}: 식별자는 영문 소문자·숫자·밑줄만 쓸 수 있습니다.")
        if key in seen_keys:
            errors.append(f"{name}: 식별자 '{key}'가 중복됩니다.")
        seen_keys.add(key)
        if not str(name).strip():
            errors.append(f"{label}: 이름이 비어 있습니다.")
        if not str(s.get("detect_prompt", "")).strip():
            errors.append(f"{name}: 감지 프롬프트가 비어 있습니다.")
        try:
            cd = float(s.get("cooldown"))
            if not (1 <= cd <= 600):
                errors.append(f"{name}: 재판정 간격은 1~600초 사이여야 합니다.")
        except (TypeError, ValueError):
            errors.append(f"{name}: 재판정 간격이 숫자가 아닙니다.")
        ins = normalize_instructions(s.get("instructions"))
        if not ins:
            errors.append(f"{name}: 지침이 하나도 없습니다.")
        if any(not str(x["text"]).strip() for x in ins):
            errors.append(f"{name}: 빈 지침이 있습니다.")
        for x in ins:
            if x.get("action") and x["action"] not in action_ids:
                errors.append(f"{name}: 지침에 연결된 행동 '{x['action']}'을 찾을 수 없습니다.")
    return errors


# ──────────────────────────────────────────────────────────────
# 조회
# ──────────────────────────────────────────────────────────────
def get_draft(agent_id: int = DEFAULT_AGENT_ID) -> dict:
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT config_json FROM config_drafts WHERE agent_id=?", (agent_id,)
        ).fetchone()
        return json.loads(row["config_json"]) if row else _bundle_from_yaml()


def get_live(agent_id: int = DEFAULT_AGENT_ID) -> dict:
    with closing(_connect()) as conn:
        row = conn.execute(
            """SELECT version, config_json, published_at FROM config_versions
               WHERE agent_id=? ORDER BY version DESC LIMIT 1""", (agent_id,)
        ).fetchone()
    if not row:
        return {"version": 0, "published_at": None, "config": _bundle_from_yaml()}
    return {
        "version": row["version"],
        "published_at": row["published_at"],
        "config": json.loads(row["config_json"]),
    }


def list_versions(agent_id: int = DEFAULT_AGENT_ID) -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            """SELECT version, changes_json, published_at, published_by, rolled_back_from
               FROM config_versions WHERE agent_id=? ORDER BY version""", (agent_id,)
        ).fetchall()
    return [{
        "version": r["version"],
        "changes": json.loads(r["changes_json"]),
        "published_at": r["published_at"],
        "published_by": r["published_by"],
        "rolled_back_from": r["rolled_back_from"],
    } for r in rows]


def version_config(version: int, agent_id: int = DEFAULT_AGENT_ID) -> dict | None:
    """특정 버전의 설정 스냅샷. 없으면 None."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT config_json FROM config_versions WHERE agent_id=? AND version=?",
            (agent_id, version),
        ).fetchone()
    return json.loads(row["config_json"]) if row else None


def save_draft(bundle: dict, by: str | None = None, agent_id: int = DEFAULT_AGENT_ID):
    with closing(_connect()) as conn, conn:
        conn.execute(
            """INSERT INTO config_drafts (agent_id, config_json, updated_at, updated_by)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(agent_id) DO UPDATE SET
                 config_json=excluded.config_json,
                 updated_at=excluded.updated_at,
                 updated_by=excluded.updated_by""",
            (agent_id, json.dumps(bundle, ensure_ascii=False), _now(), by),
        )


# ──────────────────────────────────────────────────────────────
# 변경 목록 (사람이 읽는 diff) + 반영 등급
# ──────────────────────────────────────────────────────────────
#   instant  : 감지 루프가 다음 틱에 읽으므로 대화 중에도 즉시 반영
#   next     : Gemini 세션 시작 시 고정되는 값 → 다음 대화부터
def diff(draft: dict, live: dict) -> list[dict]:
    out: list[dict] = []

    def action_name(aid):
        if not aid:
            return None
        pool = {a["id"]: a for a in (live.get("actions") or [])}
        pool.update({a["id"]: a for a in (draft.get("actions") or [])})
        return pool.get(aid, {}).get("name", aid)

    def contact_names(ids):
        pool = {c["id"]: c for c in (draft.get("contacts") or [])}
        pool.update({c["id"]: c for c in (live.get("contacts") or [])})
        return ", ".join(pool[i]["name"] for i in (ids or []) if i in pool)

    live_s = {s["key"]: s for s in (live.get("scenarios") or [])}
    draft_s = {s["key"]: s for s in (draft.get("scenarios") or [])}

    for key, s in draft_s.items():
        ls = live_s.get(key)
        if ls is None:
            out.append({"text": f"시나리오 추가됨 — {s['name']}", "tier": "next"})
            continue
        if bool(s.get("enabled", True)) != bool(ls.get("enabled", True)):
            out.append({"text": f"{s['name']} {'켜짐' if s.get('enabled', True) else '꺼짐'}",
                        "tier": "instant"})
        d_ins = normalize_instructions(s.get("instructions"))
        l_ins = normalize_instructions(ls.get("instructions"))
        d_texts = {x["text"]: x for x in d_ins}
        l_texts = {x["text"]: x for x in l_ins}
        for text, x in d_texts.items():
            if text not in l_texts:
                out.append({"text": f"지침 추가됨 ({s['name']}) — “{text}”", "tier": "next"})
            elif x.get("action") != l_texts[text].get("action"):
                label = action_name(x.get("action")) or "없음"
                out.append({"text": f"지침의 행동 변경됨 ({s['name']}) — “{text}” → {label}",
                            "tier": "next"})
        for text in l_texts:
            if text not in d_texts:
                out.append({"text": f"지침 삭제됨 ({s['name']}) — “{text}”", "tier": "next"})
        if s.get("detect_prompt") != ls.get("detect_prompt"):
            out.append({"text": f"{s['name']} 감지 기준 변경됨", "tier": "instant"})
        if float(s.get("cooldown", 0)) != float(ls.get("cooldown", 0)):
            out.append({"text": f"{s['name']} 재판정 간격 {s.get('cooldown')}초로 변경됨",
                        "tier": "instant"})
        if s.get("nudge_template") != ls.get("nudge_template"):
            out.append({"text": f"{s['name']} 감지 시 안내 문구 변경됨", "tier": "instant"})
    for key, ls in live_s.items():
        if key not in draft_s:
            out.append({"text": f"시나리오 삭제됨 — {ls['name']}", "tier": "next"})

    live_a = {a["id"]: a for a in (live.get("actions") or [])}
    draft_a = {a["id"]: a for a in (draft.get("actions") or [])}
    for aid, a in draft_a.items():
        if aid not in live_a:
            out.append({"text": f"행동 추가됨 — {a['name']}", "tier": "next"})
        elif a != live_a[aid]:
            out.append({"text": f"행동 수정됨 — {a['name']}", "tier": "next"})
    for aid, a in live_a.items():
        if aid not in draft_a:
            out.append({"text": f"행동 삭제됨 — {a['name']}", "tier": "next"})

    live_c = {c["id"]: c for c in (live.get("contacts") or [])}
    draft_c = {c["id"]: c for c in (draft.get("contacts") or [])}
    for cid, c in draft_c.items():
        if cid not in live_c:
            out.append({"text": f"연락처 등록됨 — {c['name']} ({c.get('relation', '가족')})",
                        "tier": "instant"})
    for cid, c in live_c.items():
        if cid not in draft_c:
            out.append({"text": f"연락처 삭제됨 — {c['name']}", "tier": "instant"})
    return out


# ──────────────────────────────────────────────────────────────
# 내보내기 (DB → 에이전트가 읽는 파일)
# ──────────────────────────────────────────────────────────────
def _export_live(conn: sqlite3.Connection, agent_id: int = DEFAULT_AGENT_ID):
    """live 스냅샷을 config/live.json과 agent/scenarios/*.yaml로 내보낸다.

    yaml까지 쓰는 이유: 현재 에이전트(main.py의 ws_unified)는 연결마다
    load_scenarios()로 yaml을 읽는다. 여기에 내보내두면 에이전트 코드를 고치지
    않아도 배포한 지침·감지 기준이 다음 대화부터 그대로 적용된다.
    """
    row = conn.execute(
        """SELECT version, config_json, published_at FROM config_versions
           WHERE agent_id=? ORDER BY version DESC LIMIT 1""", (agent_id,)
    ).fetchone()
    if not row:
        return
    bundle = json.loads(row["config_json"])
    _write_atomic(live_json_path(agent_id), json.dumps(
        {"version": row["version"], "published_at": row["published_at"], "config": bundle},
        ensure_ascii=False, indent=1,
    ))

    target_dir = scenarios_dir(agent_id)
    os.makedirs(target_dir, exist_ok=True)

    # 설정에 없는 yaml은 지운다 — 콘솔에서 삭제한 시나리오가 파일로 남아 되살아나지 않게.
    keep = {f"{s['key']}.yaml" for s in bundle.get("scenarios", []) if s.get("key")}
    for name in os.listdir(target_dir):
        if name.endswith(".yaml") and name not in keep:
            os.remove(os.path.join(target_dir, name))
            logger.info(f"[admin_store] 삭제된 시나리오 파일 정리: {agent_id}/{name}")

    for s in bundle.get("scenarios", []):
        doc = {
            "key": s["key"],
            "name": s["name"],
            # 꺼진 시나리오도 파일로 남긴다 — 지운 것과 잠시 끈 것은 다르다
            "enabled": bool(s.get("enabled", True)),
            "target_event": s.get("target_event", "event"),
            "cooldown": float(s.get("cooldown", 10.0)),
            # 이 값 미만의 확신도는 트리거하지 않는다 — 빠지면 기본값에 의존하게 되므로
            # 실제로 무슨 값이 쓰이는지 파일에서 바로 보이도록 함께 내보낸다
            "min_confidence": float(s.get("min_confidence", 0.7)),
            "detect_prompt": s.get("detect_prompt", ""),
            "nudge_template": s.get("nudge_template", ""),
            # 행동은 시나리오가 아니라 개별 지침에 붙는다
            "instructions": [
                {"text": x["text"], **({"action": x["action"]} if x.get("action") else {})}
                for x in normalize_instructions(s.get("instructions"))
            ],
        }
        header = (
            "# 이 파일은 관리 콘솔이 배포할 때 자동으로 씁니다 (원천: data/console.db).\n"
            f"# 배포 버전 v{row['version']} · {row['published_at']}\n"
            "# 손으로 고쳐도 동작하지만, 다음 배포 때 덮어써집니다.\n"
        )
        _write_atomic(
            os.path.join(target_dir, f"{s['key']}.yaml"),
            header + yaml.dump(doc, Dumper=_BlockDumper, allow_unicode=True,
                               sort_keys=False, width=100, default_flow_style=False),
        )


# ──────────────────────────────────────────────────────────────
# 배포 / 롤백
# ──────────────────────────────────────────────────────────────
def publish(by: str | None = None, agent_id: int = DEFAULT_AGENT_ID) -> dict:
    draft = get_draft(agent_id)
    errors = validate(draft)
    if errors:
        return {"ok": False, "errors": errors}

    live = get_live(agent_id)
    changes = diff(draft, live["config"])

    with closing(_connect()) as conn, conn:
        version = (conn.execute(
            "SELECT COALESCE(MAX(version), 0) v FROM config_versions WHERE agent_id=?",
            (agent_id,)).fetchone()["v"]) + 1
        conn.execute(
            """INSERT INTO config_versions
               (agent_id, version, config_json, changes_json, published_at, published_by)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (agent_id, version, json.dumps(draft, ensure_ascii=False),
             json.dumps(changes or [{"text": "변경 없음", "tier": "instant"}], ensure_ascii=False),
             _now(), by),
        )
        conn.execute(
            "INSERT INTO events (agent_id, ts, kind, payload_json) VALUES (?, ?, 'deploy', ?)",
            (agent_id, datetime.now().isoformat(timespec="seconds"),
             json.dumps({"version": version, "changes": changes}, ensure_ascii=False)),
        )
        _export_live(conn, agent_id)

    logger.info(f"[admin_store] v{version} 배포됨 (변경 {len(changes)}건)")
    return {
        "ok": True,
        "version": version,
        "changes": changes,
        "instant": [c for c in changes if c["tier"] == "instant"],
        "next_session": [c for c in changes if c["tier"] == "next"],
    }


def rollback(version: int, by: str | None = None, agent_id: int = DEFAULT_AGENT_ID) -> dict:
    """예전 스냅샷을 새 버전으로 다시 배포한다 (이력은 지우지 않는다)."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT config_json FROM config_versions WHERE agent_id=? AND version=?",
            (agent_id, version)).fetchone()
    if not row:
        return {"ok": False, "errors": [f"v{version}을 찾을 수 없습니다."]}

    snapshot = json.loads(row["config_json"])
    live = get_live(agent_id)
    changes = diff(snapshot, live["config"])
    save_draft(snapshot, by, agent_id)

    with closing(_connect()) as conn, conn:
        new_version = (conn.execute(
            "SELECT COALESCE(MAX(version), 0) v FROM config_versions WHERE agent_id=?",
            (agent_id,)).fetchone()["v"]) + 1
        conn.execute(
            """INSERT INTO config_versions
               (agent_id, version, config_json, changes_json, published_at, published_by,
                rolled_back_from)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (agent_id, new_version, json.dumps(snapshot, ensure_ascii=False),
             json.dumps([{"text": f"v{version} 설정으로 롤백", "tier": "next"}] + changes,
                        ensure_ascii=False),
             _now(), by, version),
        )
        conn.execute(
            "INSERT INTO events (agent_id, ts, kind, payload_json) VALUES (?, ?, 'deploy', ?)",
            (agent_id, datetime.now().isoformat(timespec="seconds"),
             json.dumps({"version": new_version, "rolled_back_from": version}, ensure_ascii=False)),
        )
        _export_live(conn, agent_id)

    logger.info(f"[admin_store] v{version} → v{new_version} 롤백 배포됨")
    return {"ok": True, "version": new_version, "rolled_back_from": version, "changes": changes}


def log_event(kind: str, payload: dict | None = None, agent_id: int = DEFAULT_AGENT_ID):
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO events (agent_id, ts, kind, payload_json) VALUES (?, ?, ?, ?)",
            (agent_id, datetime.now().isoformat(timespec="seconds"), kind,
             json.dumps(payload or {}, ensure_ascii=False)),
        )


def list_events(limit: int = 100, agent_id: int = DEFAULT_AGENT_ID) -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT ts, kind, payload_json FROM events WHERE agent_id=? ORDER BY id DESC LIMIT ?",
            (agent_id, limit)).fetchall()
    return [{"ts": r["ts"], "kind": r["kind"], "payload": json.loads(r["payload_json"] or "{}")}
            for r in rows]
