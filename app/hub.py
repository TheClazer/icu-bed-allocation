"""WebSocket broadcast hub.

Worker threads (bookings, demos, background watchers) call hub.emit(msg) at any
time. Messages are handed to the asyncio loop thread-safely and sent to every
connected browser tab.
"""
import asyncio
import json
import threading
from collections import deque


class Hub:
    def __init__(self):
        self.loop = None
        self.queue = None
        self.clients = set()
        self.sql_history = deque(maxlen=300)
        self.event_history = deque(maxlen=100)
        self._lock = threading.Lock()

    def attach(self, loop):
        self.loop = loop
        self.queue = asyncio.Queue()

    def emit(self, msg):
        kind = msg.get("type")
        with self._lock:
            if kind == "sql" and msg.get("phase") == "end":
                self.sql_history.append(msg)
            elif kind == "event":
                self.event_history.append(msg)
        if self.loop is not None and self.queue is not None:
            try:
                self.loop.call_soon_threadsafe(self.queue.put_nowait, msg)
            except RuntimeError:
                pass  # loop closed during shutdown

    def history(self):
        with self._lock:
            return list(self.sql_history), list(self.event_history)

    async def pump(self):
        while True:
            msg = await self.queue.get()
            data = json.dumps(msg, default=str)
            for ws in list(self.clients):
                try:
                    await ws.send_text(data)
                except Exception:
                    self.clients.discard(ws)


hub = Hub()
