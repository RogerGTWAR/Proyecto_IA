"""Thread-safe recent history for the current application process."""
from collections import deque
from threading import RLock
from core.event_types import normalizar, severidad


class EventStore:
    def __init__(self, maxlen=500):
        self._events = deque(maxlen=maxlen)
        self._lock = RLock()

    def append(self, event):
        with self._lock: self._events.append(event.record())

    def get_recent_events(self, limit=20, type=None, category=None, severity=None):
        limit = max(0, min(int(limit), self._events.maxlen))
        with self._lock:
            return [e for e in reversed(self._events)
                    if (type is None or e.type == normalizar(type))
                    and (category is None or e.category == normalizar(category))
                    and (severity is None or e.severity == severidad(severity))][:limit]

    def get_events_by_type(self, type, limit=20): return self.get_recent_events(limit, type=type)
    def get_events_by_category(self, category, limit=20): return self.get_recent_events(limit, category=category)
    def get_events_by_severity(self, severity, limit=20): return self.get_recent_events(limit, severity=severity)
