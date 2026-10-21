"""Rotating JSON-lines log; no payloads, images, tokens or credentials."""
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def limpiar(value):
    from core.audit_service import sanitize_sensitive_data
    return sanitize_sensitive_data(str(value))[:1000]


class EventLogger:
    def __init__(self, path=None):
        # The bus now writes the central audit. Explicit paths retain export compatibility.
        self.handler = None
        if path is None: return
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.handler = RotatingFileHandler(str(path), maxBytes=2_000_000, backupCount=3, encoding='utf-8')
        self.handler.setFormatter(logging.Formatter('%(message)s'))

    def __call__(self, event):
        if self.handler is None: return
        record = {key: limpiar(getattr(event, key)) for key in
                  ('id', 'type', 'category', 'severity', 'source', 'reference', 'message')}
        record['timestamp'] = event.timestamp.isoformat()
        self.handler.handle(logging.LogRecord('events', logging.INFO, '', 0,
                            json.dumps(record, ensure_ascii=False), (), None))

    def close(self):
        if self.handler: self.handler.close()
