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
    "scenarios": [{key, name, enabled, detect_prompt, cooldown, nudge_template,
                   instructions[], action, notify_contact_ids[]}],
    "actions":   [{id, name, description, params[], kind, url?, needs_contacts}],
    "contacts":  [{id, name, relation, phone}]
  }
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime

import yaml

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.getenv("ADMIN_DB_PATH", os.path.join(DATA_DIR, "console.db"))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
LIVE_JSON_PATH = os.path.join(CONFIG_DIR, "live.json")
SCENARIOS_DIR = os.path.join(BASE_DIR, "agent", "scenarios")

DEFAULT_AGENT_ID = 1

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
    },
    {
        "id": "record_medication",
        "name": "복약 기록",
        "description": "복약이 확인되어 기록을 남길 때",
        "params": [{"name": "기록 내용", "desc": "남길 내용"}],
        "kind": "builtin",
        "needs_contacts": False,
    },
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL,
  created_at  TEXT NOT NULL
);

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
def _bundle_from_yaml() -> dict:
    """기존 agent/scenarios/*.yaml을 읽어 초기 설정 번들(v1)을 만든다."""
    from agent.scenarios import load_scenarios

    scenarios = []
    for key, s in load_scenarios().items():
        scenarios.append({
            "key": key,
            "name": s.get("name", key),
            "enabled": True,
            "detect_prompt": s.get("detect_prompt", ""),
            "cooldown": float(s.get("cooldown", 10.0)),
            "nudge_template": s.get("nudge_template", ""),
            "instructions": list(s.get("instructions", [])),
            "action": s.get("action"),
            "notify_contact_ids": [],
            "target_event": s.get("target_event", "event"),
        })
    return {
        "scenarios": scenarios,
        "actions": [dict(a) for a in BUILTIN_ACTIONS],
        "contacts": [],
    }


def init_db():
    """테이블 생성 + 최초 실행 시 yaml에서 v1 스냅샷 이관."""
    with closing(_connect()) as conn, conn:
        conn.executescript(SCHEMA)
        row = conn.execute("SELECT COUNT(*) c FROM agents").fetchone()
        if row["c"] == 0:
            conn.execute(
                "INSERT INTO agents (id, name, created_at) VALUES (?, ?, ?)",
                (DEFAULT_AGENT_ID, "기본 에이전트", _now()),
            )
        row = conn.execute(
            "SELECT COUNT(*) c FROM config_versions WHERE agent_id=?", (DEFAULT_AGENT_ID,)
        ).fetchone()
        if row["c"] == 0:
            bundle = _bundle_from_yaml()
            payload = json.dumps(bundle, ensure_ascii=False)
            conn.execute(
                """INSERT INTO config_versions
                   (agent_id, version, config_json, changes_json, published_at, published_by)
                   VALUES (?, 1, ?, ?, ?, ?)""",
                (DEFAULT_AGENT_ID, payload,
                 # 변경 목록은 항상 {text, tier} 형태 — 콘솔이 한 가지 형식만 다루게 한다
                 json.dumps([{"text": "초기 설정 (agent/scenarios/*.yaml에서 이관)",
                              "tier": "instant"}], ensure_ascii=False),
                 _now(), "system"),
            )
            conn.execute(
                """INSERT INTO config_drafts (agent_id, config_json, updated_at, updated_by)
                   VALUES (?, ?, ?, ?)""",
                (DEFAULT_AGENT_ID, payload, _now(), "system"),
            )
            logger.info("[admin_store] yaml에서 v1 스냅샷 이관 완료")
        _export_live(conn)


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
        ins = s.get("instructions")
        if not isinstance(ins, list) or not ins:
            errors.append(f"{name}: 지침이 하나도 없습니다.")
        elif any(not str(x).strip() for x in ins):
            errors.append(f"{name}: 빈 지침이 있습니다.")
        act = s.get("action")
        if act and act not in action_ids:
            errors.append(f"{name}: 연결된 행동 '{act}'을 찾을 수 없습니다.")
        for cid in s.get("notify_contact_ids") or []:
            if cid not in contact_ids:
                errors.append(f"{name}: 연락 대상 중 삭제된 연락처가 있습니다.")
                break
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
        for ins in s.get("instructions", []):
            if ins not in ls.get("instructions", []):
                out.append({"text": f"지침 추가됨 ({s['name']}) — “{ins}”", "tier": "next"})
        for ins in ls.get("instructions", []):
            if ins not in s.get("instructions", []):
                out.append({"text": f"지침 삭제됨 ({s['name']}) — “{ins}”", "tier": "next"})
        if s.get("detect_prompt") != ls.get("detect_prompt"):
            out.append({"text": f"{s['name']} 감지 기준 변경됨", "tier": "instant"})
        if float(s.get("cooldown", 0)) != float(ls.get("cooldown", 0)):
            out.append({"text": f"{s['name']} 재판정 간격 {s.get('cooldown')}초로 변경됨",
                        "tier": "instant"})
        if s.get("nudge_template") != ls.get("nudge_template"):
            out.append({"text": f"{s['name']} 감지 시 안내 문구 변경됨", "tier": "instant"})
        if (s.get("action") or None) != (ls.get("action") or None):
            out.append({"text": f"{s['name']}의 감지 시 행동이 변경됨", "tier": "next"})
        if (s.get("notify_contact_ids") or []) != (ls.get("notify_contact_ids") or []):
            out.append({"text": f"{s['name']} 연락 대상 변경됨 — "
                                f"{contact_names(s.get('notify_contact_ids')) or '없음'}",
                        "tier": "instant"})
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
    _write_atomic(LIVE_JSON_PATH, json.dumps(
        {"version": row["version"], "published_at": row["published_at"], "config": bundle},
        ensure_ascii=False, indent=1,
    ))

    for s in bundle.get("scenarios", []):
        if not s.get("enabled", True):
            continue  # 꺼진 시나리오는 yaml을 갱신하지 않는다 (에이전트에 on/off 개념이 아직 없음)
        doc = {
            "key": s["key"],
            "name": s["name"],
            "target_event": s.get("target_event", "event"),
            "cooldown": float(s.get("cooldown", 10.0)),
            "detect_prompt": s.get("detect_prompt", ""),
            "nudge_template": s.get("nudge_template", ""),
            "instructions": list(s.get("instructions", [])),
            "action": s.get("action"),
        }
        header = (
            "# 이 파일은 관리 콘솔이 배포할 때 자동으로 씁니다 (원천: data/console.db).\n"
            f"# 배포 버전 v{row['version']} · {row['published_at']}\n"
            "# 손으로 고쳐도 동작하지만, 다음 배포 때 덮어써집니다.\n"
        )
        _write_atomic(
            os.path.join(SCENARIOS_DIR, f"{s['key']}.yaml"),
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
