"""One local bus. Slow consumers have independent bounded FIFO workers."""
import logging
import queue
import threading
import time
from collections import OrderedDict
from contextvars import ContextVar
from core.event_store import EventStore
from core.system_event import SystemEvent
from core.event_types import normalizar
from core.audit_service import audit, use_context, event_context, record_event

LOG = logging.getLogger('event_bus')
_outbox = ContextVar('event_transaction', default=None)


class Subscription:
    def __init__(self, owner, key, types, callback, asynchronous, capacity):
        self.owner, self.key, self.types, self.callback = owner, key, types, callback
        self.queue = queue.Queue(capacity) if asynchronous else None
        self.closed = threading.Event()
        if self.queue is not None:
            self.worker = threading.Thread(target=self._run, name='events-'+key, daemon=True)
            self.worker.start()

    def _call(self, event):
        try:
            with use_context(event_context(event)):
                self.callback(event)
            LOG.debug('delivered consumer=%s type=%s', self.key, event.type)
        except Exception as error:
            with use_context(event_context(event)):
                audit.record('EVENT_BUS', 'SUBSCRIBER_FAILED', 'FAILED', level='ERROR', error=error,
                             data={'subscriber':self.key, 'event_id':event.id, 'event_type':event.type})
            with self.owner._lock: self.owner.errors += 1
            # Exception strings may contain credentials; log only the class.
            LOG.error('subscriber_error consumer=%s type=%s error=%s', self.key, event.type, type(error).__name__)

    def deliver(self, event):
        if self.closed.is_set(): return
        if self.queue is None: self._call(event)
        else:
            try: self.queue.put_nowait(event)
            except queue.Full:
                with use_context(event_context(event)):
                    audit.record('EVENT_BUS', 'SUBSCRIBER_QUEUE_FULL', 'FAILED', level='ERROR',
                                 data={'subscriber':self.key, 'event_id':event.id})
                with self.owner._lock: self.owner.errors += 1
                LOG.error('subscriber_queue_full consumer=%s event=%s', self.key, event.id)

    def _run(self):
        while not self.closed.is_set() or not self.queue.empty():
            try: event = self.queue.get(timeout=.1)
            except queue.Empty: continue
            try: self._call(event)
            finally: self.queue.task_done()

    def unsubscribe(self): self.owner.unsubscribe(self)


class EventBus:
    def __init__(self, store=None):
        self.store = store if store is not None else EventStore()
        self._lock = threading.RLock()
        self._subscriptions = {}
        self._seen, self._references, self._states, self._state_times = OrderedDict(), OrderedDict(), OrderedDict(), OrderedDict()
        self.errors = 0

    def subscribe(self, event_type, callback, *, name=None, asynchronous=False, capacity=256):
        types = frozenset(normalizar(t) for t in (event_type if isinstance(event_type, (list, tuple, set)) else [event_type]))
        key = name or str(id(callback))
        with self._lock:
            if key in self._subscriptions: return self._subscriptions[key]
            sub = Subscription(self, key, types, callback, asynchronous, capacity)
            self._subscriptions[key] = sub
            return sub

    def unsubscribe(self, subscription):
        with self._lock:
            key = getattr(subscription, 'key', subscription)
            if isinstance(subscription, Subscription) and self._subscriptions.get(key) is not subscription: return
            sub = self._subscriptions.pop(key, None)
            if sub: sub.closed.set()

    def seed_state(self, key, state):
        """A baseline is not an event and never overwrites a live transition."""
        with self._lock:
            if key not in self._states: self._bounded(self._states, key, state)

    @staticmethod
    def _bounded(mapping, key, value):
        mapping[key] = value
        mapping.move_to_end(key)
        while len(mapping) > 4096: mapping.popitem(last=False)

    def publish(self, event, *, transition=None, state=None, deduplicate=False):
        if not isinstance(event, SystemEvent): raise TypeError('publish requires SystemEvent')
        with self._lock:
            if event.id in self._seen: return False
            if transition is not None and transition in self._state_times and event.timestamp<self._state_times[transition]: return False
            if transition is not None and self._states.get(transition, object()) == state:
                self._bounded(self._state_times, transition, event.timestamp)
                return False
            # Transitions allow recurrence after recovery, even with the same semantic reference.
            if transition is None and deduplicate and event.reference and event.reference in self._references: return False
            if transition is not None:
                self._bounded(self._states, transition, state)
                self._bounded(self._state_times, transition, event.timestamp)
            if event.reference: self._bounded(self._references, event.reference, event.id)
            self._bounded(self._seen, event.id, True)
            self.store.append(event)
            subscribers = list(self._subscriptions.values())
        LOG.debug('published id=%s type=%s source=%s subscribers=%s', event.id, event.type, event.source, len(subscribers))
        with use_context(event_context(event)):
            audit.record('EVENT_BUS', 'EVENT_PUBLISHED', level='DEBUG', category=event.category,
                         data={'event_id':event.id, 'event_type':event.type, 'source':event.source,
                               'reference':event.reference,
                               'subscriber_count':sum('*' in s.types or event.type in s.types for s in subscribers)})
        record_event(event)
        for sub in subscribers:
            if '*' in sub.types or event.type in sub.types: sub.deliver(event)
        return True

    def flush(self, timeout=5):
        end = time.monotonic()+timeout
        while time.monotonic()<end:
            with self._lock: pending = any(s.queue and s.queue.unfinished_tasks for s in self._subscriptions.values())
            if not pending: return True
            time.sleep(.01)
        return False

    def close(self):
        with self._lock:
            for sub in list(self._subscriptions.values()): self.unsubscribe(sub)


event_bus = EventBus()
event_store = event_bus.store


def emitir(type, category, source, title, message='', severity='INFO', reference='', data=None,
           image=None, video=None, metadata=None, transition=None, state=None, deduplicate=False):
    """Publish, or stage until the enclosing inventory transaction commits."""
    event = SystemEvent(type, category, source, title, message or title, severity, reference,
                        data or {}, image, video, metadata or {})
    options = dict(transition=transition, state=state, deduplicate=deduplicate)
    pending = _outbox.get()
    if pending is not None: pending.append((event, options)); return event
    event_bus.publish(event, **options)
    return event


def confirmar_eventos(pending):
    for event, options in pending: event_bus.publish(event, **options)
