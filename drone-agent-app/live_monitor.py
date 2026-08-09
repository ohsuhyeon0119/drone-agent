"""관리 콘솔이 실행 중인 세션을 들여다보기 위한 관전 채널.

에이전트 세션의 이벤트는 전부 기기(폰/브라우저)와 연결된 웹소켓 하나로만
나간다. 보호자가 콘솔에서 "지금 무슨 일이 일어나고 있는지"를 보려면 그 흐름을
복사해 줄 곳이 필요하다.

관전자는 **읽기만 한다.** 여기로 들어온 것이 세션에 영향을 주지 않는다 —
콘솔을 열어둔 것 때문에 어르신과의 대화가 달라지면 안 된다.

이벤트는 링 버퍼에 담아둔다. 콘솔을 나중에 열어도 직전 상황부터 볼 수 있어야
하고, 무한히 쌓이면 오래 켜둔 서버의 메모리를 먹기 때문이다.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from datetime import datetime

logger = logging.getLogger(__name__)

# 관전자에게 보낼 필요가 없는 것들. 오디오 청크처럼 양이 많고 로그로서 의미가
# 없는 이벤트를 걸러야 로그가 읽을 수 있는 상태로 남는다.
_SKIP_TYPES = {"audio", "audio_chunk"}

MAX_EVENTS = 120
# 관전자 큐가 이만큼 밀리면 그 관전자는 따라오지 못하는 것으로 본다.
# 무한히 쌓아두면 창을 열어둔 채 방치된 탭 하나가 서버 메모리를 먹는다.
MAX_QUEUE = 200


class LiveMonitor:
    def __init__(self):
        self._events: dict[int, deque] = defaultdict(lambda: deque(maxlen=MAX_EVENTS))
        self._subs: dict[int, set[asyncio.Queue]] = defaultdict(set)
        self._sessions: dict[int, dict] = {}

    # ── 세션 쪽에서 부르는 것 ───────────────────────────────────
    def session_started(self, agent_id: int, frames: dict):
        """frames는 세션이 매 프레임 갱신하는 버퍼다 (복사하지 않고 참조만 둔다)."""
        self._sessions[agent_id] = {"frames": frames, "since": _now()}
        self.publish(agent_id, {"type": "session", "state": "started"})

    def session_ended(self, agent_id: int):
        self._sessions.pop(agent_id, None)
        self.publish(agent_id, {"type": "session", "state": "ended"})

    def publish(self, agent_id: int, event: dict):
        if not isinstance(event, dict) or event.get("type") in _SKIP_TYPES:
            return
        record = {**event, "ts": _now()}
        self._events[agent_id].append(record)
        for q in list(self._subs[agent_id]):
            if q.qsize() >= MAX_QUEUE:
                continue
            q.put_nowait(record)

    # ── 관전자 쪽에서 부르는 것 ─────────────────────────────────
    def subscribe(self, agent_id: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subs[agent_id].add(q)
        return q

    def unsubscribe(self, agent_id: int, q: asyncio.Queue):
        self._subs[agent_id].discard(q)

    def recent(self, agent_id: int) -> list[dict]:
        return list(self._events[agent_id])

    def frame(self, agent_id: int):
        session = self._sessions.get(agent_id)
        return session["frames"].get("data") if session else None

    def frame_seq(self, agent_id: int) -> int:
        """장면이 바뀔 때마다 올라가는 번호. 관전자가 같은 장면을 다시 받지 않게 한다."""
        session = self._sessions.get(agent_id)
        return session["frames"].get("seq", 0) if session else -1

    def status(self, agent_id: int) -> dict:
        session = self._sessions.get(agent_id)
        return {"connected": bool(session), "since": session["since"] if session else None}


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


monitor = LiveMonitor()


class MirroredSocket:
    """세션 웹소켓에 보내는 이벤트를 관전 채널에도 그대로 흘린다.

    send_json 호출부가 여러 곳(감지 루프, 도구 콜백, Gemini 이벤트 중계)에
    흩어져 있어서, 각각에 한 줄씩 넣으면 새 이벤트를 추가할 때마다 빠뜨리기
    쉽다. 소켓을 감싸면 지나가는 모든 이벤트가 자동으로 복사된다.
    """

    def __init__(self, ws, agent_id: int):
        self._ws = ws
        self._agent_id = agent_id

    async def send_json(self, data):
        monitor.publish(self._agent_id, data)
        await self._ws.send_json(data)

    def __getattr__(self, name):
        # receive / send_bytes / close 등은 원래 소켓으로 그대로 넘긴다
        return getattr(self._ws, name)
