"""Internal tracing. Observation never participates in business transactions."""
from core.paths import PROJECT_ROOT
import atexit
from collections import deque
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, asdict
from datetime import datetime
from functools import wraps
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
from pathlib import Path
import queue
import re
import threading
import time
import traceback
from uuid import uuid4

ROOT = PROJECT_ROOT
_context = ContextVar('technical_audit_context', default=None)
_SESSION = str(uuid4())
_SECRET = re.compile(r'password|passwd|pwd|token|secret|authorization|credential|api[_-]?key|connection[_ -]?string|contrase\u00f1a|access[_-]?key', re.I)
_BIOMETRIC = re.compile(r'embedding|landmark|biometric|raw_frame|^frame$|^vector$|^audio$', re.I)
_STATUSES = frozenset('STARTED SUCCESS FAILED CANCELLED SKIPPED CONFIRMATION_REQUIRED CONFIRMED REJECTED'.split())


def _known_secrets():
    values = dict(os.environ)
    try:
        from dotenv import dotenv_values
        values.update(dotenv_values(ROOT/'.env', encoding='utf-8'))
    except (ImportError, OSError, ValueError): pass
    return tuple(sorted({str(v) for k,v in values.items() if v and len(str(v)) >= 6 and _SECRET.search(k)}, key=len, reverse=True))


_KNOWN_SECRETS = _known_secrets()


@dataclass(frozen=True)
class AuditContext:
    correlation_id: str = ''
    operation_id: str = ''
    parent_operation_id: str = ''
    origin: str = 'system'
    session_id: str = _SESSION

    def __post_init__(self):
        if not self.correlation_id: object.__setattr__(self, 'correlation_id', str(uuid4()))
        origin = {'voz':'voice','escritorio':'desktop'}.get(self.origin,self.origin)
        if origin not in ('desktop','voice','telegram','automatic','system','worker'): origin='system'
        object.__setattr__(self,'origin',origin)


def current_context():
    return _context.get()


def capture_context():
    return asdict(current_context() or AuditContext())


@contextmanager
def use_context(context=None, *, origin='system', session_id=None):
    if isinstance(context, Mapping):
        context = AuditContext(**{k: context[k] for k in AuditContext.__dataclass_fields__
                                  if isinstance(context.get(k),str)})
    elif context is not None and not isinstance(context,AuditContext): context=None
    context = context or current_context() or AuditContext(origin=origin, session_id=session_id or _SESSION)
    token = _context.set(context)
    try: yield context
    finally: _context.reset(token)


def run_in_context(context, fn, *args, **kwargs):
    with use_context(context): return fn(*args, **kwargs)


def sanitize_sensitive_data(value, _depth=0):
    """Bounded, recursive, JSON-safe; excludes buffers and biometric payloads."""
    if _depth > 8: return '[depth omitted]'
    if isinstance(value, Mapping):
        return {str(k)[:120]: ('[redacted]' if _SECRET.search(str(k)) else
                '[omitted]' if _BIOMETRIC.search(str(k)) else sanitize_sensitive_data(v, _depth+1))
                for k, v in list(value.items())[:80]}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [sanitize_sensitive_data(v, _depth+1) for v in list(value)[:80]]
    if isinstance(value, (bytes, bytearray, memoryview)) or hasattr(value, 'shape'):
        return '[buffer omitted]'
    if value is None or isinstance(value, (bool, int)): return value
    if isinstance(value, float): return value if math.isfinite(value) else None
    if not isinstance(value, (str, Path, datetime)):
        from decimal import Decimal
        if not isinstance(value, Decimal): return '['+type(value).__name__+']'
    text = value.isoformat() if isinstance(value, datetime) else str(value)
    for secret in _KNOWN_SECRETS: text=text.replace(secret,'[redacted]')
    text = text.replace(str(ROOT)+'\\', '').replace(str(ROOT)+'/', '')
    text = re.sub(r'(?i)C:[\\/]Users[\\/][^\\/\s\"\']+', 'C:/Users/[private]', text)
    # Entire connection strings are unnecessary, even after password redaction.
    text = re.sub(r'(?i)(?:DRIVER|SERVER|DSN)\s*=.*', '[connection omitted]', text)
    text = re.sub(r'(?i)(?:https?|rtsp)://[^\s\"\']+', '[address omitted]', text)
    text = re.sub(r'(?i)(?:[\w-]*(?:password|pwd|token|secret|api[_-]?key|authorization|credential|access[_-]?key)[\w-]*)\s*[=:]\s*(?:\"[^\"]*\"|\x27[^\x27]*\x27|[^\s;,]+)', '[redacted]', text)
    text = re.sub(r'\b\d{5,}:[A-Za-z0-9_-]{15,}', '[redacted]', text)
    text = re.sub(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b', '[redacted]', text)
    text = re.sub(r'(?i)Bearer\s+\S+', '[redacted]', text)
    return text[:2000]


class AuditService:
    def __init__(self, directory=None, max_bytes=10*1024*1024, backups=5, capacity=4096):
        self.directory = Path(directory) if directory else ROOT/'logs'
        self.max_bytes, self.backups = max_bytes, backups
        self.queue = queue.Queue(capacity)
        self.fallback = deque(maxlen=100)
        self.lock = threading.RLock()
        self.handlers = None
        self.worker = None
        self.closed = False
        self.dropped = 0

    def _open(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        handlers = {}
        try:
            for name in ('audit.jsonl', 'system.log', 'errors.log'):
                handler = RotatingFileHandler(str(self.directory/name), maxBytes=self.max_bytes,
                                              backupCount=self.backups, encoding='utf-8')
                handler.setFormatter(logging.Formatter('%(message)s'))
                # StreamHandler otherwise swallows disk errors and prints unsanitized diagnostics.
                def failed(record): raise OSError('Audit write unavailable')
                handler.handleError = failed
                handlers[name] = handler
        except Exception:
            for handler in handlers.values(): handler.close()
            raise
        self.handlers = handlers

    def record(self, source, action, status='SUCCESS', *, level='INFO', error=None, **fields):
        try:
            context = current_context() or AuditContext()
            record = dict(timestamp=datetime.now().astimezone().isoformat(),
                correlation_id=context.correlation_id, operation_id=str(uuid4()),
                parent_operation_id=context.operation_id, source=source.upper(), origin=context.origin,
                action=action, category='', entity_type=None, entity_id=None, entity_code=None,
                status=status, before=None, after=None, data={}, duration_ms=None,
                error_type=type(error).__name__ if error else None,
                error_message=str(error) if error else None,
                thread=threading.current_thread().name, session_id=context.session_id,
                user_context=None, level=level)
            record.update(fields)
            record['status'] = record['status'] if record['status'] in _STATUSES else 'FAILED'
            if record['status']=='FAILED' and record['level'] not in ('ERROR','CRITICAL'):record['level']='ERROR'
            clean = sanitize_sensitive_data(record)
            stack = sanitize_sensitive_data(''.join(traceback.format_exception(type(error), error, error.__traceback__))) if error else None
            with self.lock:
                if self.closed: return
                if self.worker is None:
                    self.worker = threading.Thread(target=self._run, name='technical-audit', daemon=True)
                    self.worker.start()
                try: self.queue.put_nowait((clean, stack))
                except queue.Full:
                    self.dropped += 1; self.fallback.append((clean, stack))
        except Exception:
            # Observability must not replace or mask the application's exception.
            with self.lock: self.dropped += 1

    def _run(self):
        retry_at = 0
        while not self.closed or not self.queue.empty():
            try: item = self.queue.get(timeout=.1)
            except queue.Empty: continue
            try:
                if self.handlers is None:
                    if time.monotonic() < retry_at: raise OSError('Audit retry delayed')
                    self._open()
                record, stack = item
                line = json.dumps(record, ensure_ascii=False, allow_nan=False)
                self.handlers['audit.jsonl'].handle(logging.makeLogRecord({'msg':line,'levelno':logging.INFO}))
                if record['level'] != 'DEBUG':
                    human = '{timestamp} {level} {source} {action} {status} correlation={correlation_id} operation={operation_id}'.format(**record)
                    self.handlers['system.log'].handle(logging.makeLogRecord({'msg':human,'levelno':logging.INFO}))
                if stack or record['status'] == 'FAILED':
                    self.handlers['errors.log'].handle(logging.makeLogRecord({'msg':line+'\n'+(stack or ''),'levelno':logging.ERROR}))
            except Exception:
                with self.lock: self.fallback.append(item); self.dropped += 1
                if self.handlers:
                    for handler in self.handlers.values():
                        try: handler.close()
                        except Exception: pass
                self.handlers = None; retry_at = time.monotonic()+5
            finally: self.queue.task_done()

    def flush(self, timeout=3):
        end = time.monotonic()+timeout
        while self.queue.unfinished_tasks and time.monotonic() < end: time.sleep(.01)
        return not self.queue.unfinished_tasks

    def diagnostics(self):
        with self.lock:
            return {'pending':self.queue.qsize(),'unwritten':self.dropped,
                    'retained_in_memory':len(self.fallback),'closed':self.closed}

    def close(self):
        with self.lock: self.closed = True
        if self.worker and self.worker is not threading.current_thread(): self.worker.join(timeout=3)
        if self.handlers and (not self.worker or not self.worker.is_alive()):
            for handler in self.handlers.values(): handler.close()


audit = AuditService()
atexit.register(audit.close)


@contextmanager
def operation(source, action, *, origin='system', session_id=None, **fields):
    parent = current_context() or AuditContext(origin=origin, session_id=session_id or _SESSION)
    context = AuditContext(parent.correlation_id, str(uuid4()), parent.operation_id, parent.origin, parent.session_id)
    result = dict(fields)
    started = time.monotonic()
    with use_context(context):
        audit.record(source, action, 'STARTED', operation_id=context.operation_id,
                     parent_operation_id=context.parent_operation_id, **fields)
        try: yield result
        except BaseException as error:
            result.pop('status', None)
            result.pop('level', None)
            audit.record(source, action, 'CANCELLED' if isinstance(error, (KeyboardInterrupt, SystemExit)) else 'FAILED',
                operation_id=context.operation_id, parent_operation_id=context.parent_operation_id,
                error=error, level='ERROR', duration_ms=round((time.monotonic()-started)*1000, 3), **result)
            raise
        else:
            status = result.pop('status', 'SUCCESS')
            audit.record(source, action, status, operation_id=context.operation_id,
                parent_operation_id=context.parent_operation_id,
                duration_ms=round((time.monotonic()-started)*1000, 3), **result)


def audit_action(source, action, origin='system'):
    def decorate(fn):
        @wraps(fn)
        def traced(*args, **kwargs):
            with operation(source, action, origin=origin): return fn(*args, **kwargs)
        return traced
    return decorate


def event_context(event):
    return AuditContext(event.correlation_id, event.operation_id, event.parent_operation_id,
                        event.origin, event.session_id)


def record_event(event):
    try: _record_event(event)
    except Exception:
        # A malformed optional payload cannot prevent delivery to subscribers.
        pass


def _record_event(event):
    """Committed domain events, with no raw evidence retained."""
    data = dict(event.data) if isinstance(event.data,Mapping) else {}
    data.pop('_audit_context',None)
    if event.type == 'SERVICIO_ESTADO_CAMBIADO' and data.get('anterior') == data.get('estado'): return
    source = event.category.upper()
    source = {'RECONOCIMIENTO_FACIAL':'SFACE', 'FACIAL':'SFACE', 'LED':'ARDUINO',
              'SISTEMA':'SYSTEM', 'CONTEO':'INVENTARIO'}.get(source, source)
    if event.type in ('SFACE_ERROR','SFACE_DISPONIBLE','FACIAL_NO_DISPONIBLE'):source='SFACE'
    if event.type in ('YOLO_ERROR','YOLO_DISPONIBLE'):source='YOLO'
    before = {'stock':data['stock_anterior']} if 'stock_anterior' in data else None
    after = {'stock':data['stock_nuevo']} if 'stock_nuevo' in data else None
    if 'anterior' in data and 'estado' in data:
        before, after = {'estado':data['anterior']}, {'estado':data['estado']}
    entity_type,entity_id=None,None
    for kind,key in (('producto','id_producto'),('conteo','id_conteo'),('alerta','id_alerta'),
                     ('empleado','id_empleado'),('movimiento','id_movimiento'),('intrusion','id_evento'),('servicio','componente')):
        if data.get(key) is not None:
            entity_type,entity_id=kind,data[key];break
    with use_context(event_context(event)):
        audit.record(source, event.type, 'FAILED' if event.type.endswith('_ERROR') else 'SUCCESS',
            operation_id=event.operation_id, parent_operation_id=event.parent_operation_id,
            category=event.category, entity_type=entity_type,
            entity_id=entity_id, entity_code=data.get('codigo',data.get('codigo_empleado')), before=before, after=after,
            data=dict(data, event_id=event.id, reference=event.reference,
                      part=event.metadata.get('parte'),severity=event.severity,
                      image=event.image if isinstance(event.image, str) else None,
                      video=event.video if isinstance(event.video, str) else None),
            error_type=data.get('error') if event.type.endswith('_ERROR') else None,
            error_message=event.message if event.type.endswith('_ERROR') else None,
            level='CRITICAL' if event.type=='SQL_DESCONECTADO' and not event.metadata.get('esperado') else
                  'ERROR' if event.type.endswith('_ERROR') else 'WARNING' if event.severity in ('ALTA','CRITICA') else 'INFO')
