"""
약 복용 시나리오용 초경량 메모리 저장소.

JSON 파일 하나에 사용자 프로필(가정 데이터)과 복용 기록을 저장한다.
대시보드에서 "메모리가 실제로 업데이트됐다"는 걸 보여주기 위한 용도라
DB 없이 파일 하나로 충분하다.
"""

import json
import os
from datetime import datetime

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory.json")

# 데모용 가정 데이터 — 이미 이 노인에 대한 처방 정보가 있다고 가정
PATIENT_PROFILE = {
    "name": "오수현",
    "medication": "혈압약",
    "scheduled_time": "20:00",
}


def _load() -> dict:
    if not os.path.isfile(_PATH):
        return {"profile": PATIENT_PROFILE, "logs": []}
    with open(_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict):
    with open(_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_profile() -> dict:
    return _load()["profile"]


def get_logs() -> list:
    return _load()["logs"]


def record_medication_taken(note: str = "") -> dict:
    """복용 확인 시 메모리에 기록하고, 새로 추가된 레코드를 반환한다."""
    data = _load()
    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "medication": data["profile"]["medication"],
        "taken": True,
        "note": note,
    }
    data["logs"].append(record)
    _save(data)
    return record
