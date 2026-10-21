"""Immutable envelopes and owned visual evidence. No device or network access."""
from dataclasses import dataclass, field, replace
from datetime import datetime
from collections.abc import Mapping
from types import MappingProxyType
from uuid import uuid4
from core.event_types import EventType, Category, severidad, normalizar


def freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(freeze(v) for v in value)
    if hasattr(value, 'shape') and hasattr(value, 'tobytes'):
        return FrameSnapshot(tuple(value.shape), str(value.dtype), value.tobytes())
    if isinstance(value, bytearray): return bytes(value)
    if value is None or isinstance(value, (str, int, float, bool, bytes, datetime, FrameSnapshot)):
        return value
    # Decimal, date and Path become immutable, lossless representations.
    return str(value)


def thaw(value):
    if isinstance(value, Mapping): return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, tuple): return [thaw(v) for v in value]
    return value


@dataclass(frozen=True)
class FrameSnapshot:
    shape: tuple
    dtype: str
    content: bytes = field(repr=False)

    def array(self):
        import numpy as np
        return np.frombuffer(self.content, dtype=self.dtype).reshape(self.shape).copy()


@dataclass(frozen=True)
class SystemEvent:
    type: str
    category: str
    source: str
    title: str
    message: str
    severity: str = 'INFO'
    reference: str = ''
    data: object = field(default_factory=dict)
    image: object = None
    video: object = None
    metadata: object = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now().astimezone())
    correlation_id: str = ''
    operation_id: str = ''
    parent_operation_id: str = ''
    origin: str = ''
    session_id: str = ''

    def __post_init__(self):
        from core.audit_service import current_context, AuditContext
        context = current_context() or AuditContext(origin='automatic' if str(self.category) in ('FACIAL','VIGILANCIA') else 'system')
        for name, value in dict(correlation_id=self.correlation_id or context.correlation_id,
                operation_id=self.operation_id or str(uuid4()),
                parent_operation_id=self.parent_operation_id or context.operation_id,
                origin=self.origin or context.origin, session_id=self.session_id or context.session_id).items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, 'type', EventType(normalizar(self.type)).value)
        object.__setattr__(self, 'category', Category(normalizar(self.category)).value)
        object.__setattr__(self, 'severity', severidad(self.severity))
        if self.timestamp.tzinfo is None: raise ValueError('Event timestamp must include timezone')
        for name in ('data', 'metadata', 'image', 'video'):
            object.__setattr__(self, name, freeze(getattr(self, name)))

    def record(self):
        """Bounded store retains evidence paths, never camera buffers."""
        def compact(value):
            if isinstance(value, FrameSnapshot): return {'shape':value.shape,'raw_retained':False}
            if isinstance(value, Mapping): return {k:compact(v) for k,v in value.items()}
            if isinstance(value, tuple): return tuple(compact(v) for v in value)
            return value
        return replace(self, image=None if isinstance(self.image, FrameSnapshot) else self.image,
                       data=compact(self.data),metadata=compact(self.metadata))

    def to_dict(self):
        result={name: (self.timestamp.isoformat() if name == 'timestamp' else thaw(getattr(self, name)))
                for name in self.__dataclass_fields__ if name not in ('image', 'video')}
        result.update(image=self.image if isinstance(self.image,str) else None,
                      video=self.video if isinstance(self.video,str) else None)
        return result
