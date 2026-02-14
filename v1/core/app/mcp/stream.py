from __future__ import annotations

import asyncio
import json
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass(slots=True)
class SseEvent:
    id: str
    event: str
    data: dict


class StreamManager:
    def __init__(self, replay_limit: int = 500):
        self._replay_limit = replay_limit
        self._events: dict[str, deque[SseEvent]] = defaultdict(lambda: deque(maxlen=self._replay_limit))
        self._counters: dict[str, int] = defaultdict(int)
        self._subscribers: dict[str, list[asyncio.Queue[SseEvent]]] = defaultdict(list)

    def append_event(self, session_id: str, event: str, data: dict) -> str:
        self._counters[session_id] += 1
        event_id = str(self._counters[session_id])
        payload = SseEvent(id=event_id, event=event, data=data)
        self._events[session_id].append(payload)

        for queue in list(self._subscribers[session_id]):
            if not queue.full():
                queue.put_nowait(payload)
        return event_id

    def replay_from(self, session_id: str, last_event_id: str | None) -> list[SseEvent]:
        if not last_event_id:
            return []
        try:
            cursor = int(last_event_id)
        except ValueError:
            return []
        return [evt for evt in self._events[session_id] if int(evt.id) > cursor]

    async def subscribe(self, session_id: str) -> AsyncIterator[SseEvent]:
        queue: asyncio.Queue[SseEvent] = asyncio.Queue(maxsize=100)
        self._subscribers[session_id].append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            subscribers = self._subscribers[session_id]
            if queue in subscribers:
                subscribers.remove(queue)


def format_sse(event: SseEvent) -> str:
    wire = []
    wire.append(f"id: {event.id}")
    wire.append(f"event: {event.event}")
    wire.append(f"data: {json.dumps(event.data, separators=(',', ':'))}")
    wire.append("")
    return "\n".join(wire) + "\n"
