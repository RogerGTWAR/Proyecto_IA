"""Isolated event infrastructure checks; no SQL, network or hardware."""
import concurrent.futures
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from core.event_bus import EventBus
from core.event_store import EventStore
from core.event_logger import EventLogger
from core.system_event import SystemEvent


def evento(**kwargs):
    args = dict(type='STOCK_BAJO', category='INVENTARIO', source='movimientos',
                title='Stock bajo', message='Stock bajo', reference='STOCK_BAJO:REP-007')
    args.update(kwargs)
    return SystemEvent(**args)


class Infraestructura(unittest.TestCase):
    def setUp(self): self.bus = EventBus()
    def tearDown(self): self.bus.flush(); self.bus.close()

    def test_subscribe_publish_multiple_unsubscribe(self):
        a, b = [], []
        sub = self.bus.subscribe('STOCK_BAJO', a.append)
        self.bus.subscribe('*', b.append)
        self.assertTrue(self.bus.publish(evento()))
        self.assertEqual((len(a), len(b)), (1, 1))
        sub.unsubscribe(); self.bus.publish(evento())
        self.assertEqual((len(a), len(b)), (1, 2))

    def test_error_isolated(self):
        def fail(e): raise RuntimeError('consumer error')
        received = []
        self.bus.subscribe('*', fail)
        self.bus.subscribe('*', received.append)
        with self.assertLogs('event_bus', level='ERROR'): self.bus.publish(evento())
        self.assertEqual(len(received), 1)
        self.assertEqual(len(self.bus.store.get_recent_events()), 1)

    def test_concurrent(self):
        received = []
        self.bus.subscribe('*', received.append, asynchronous=True, capacity=512)
        with concurrent.futures.ThreadPoolExecutor(8) as executor:
            list(executor.map(lambda i: self.bus.publish(evento(reference=str(i))), range(200)))
        self.assertTrue(self.bus.flush())
        self.assertEqual(len({e.id for e in received}), 200)

    def test_store_filters_bounded(self):
        store = EventStore(2)
        for severity in ('BAJA', 'MEDIA', 'CRÍTICA'): store.append(evento(severity=severity))
        self.assertEqual(len(store.get_recent_events()), 2)
        self.assertEqual(len(store.get_events_by_severity('CRÍTICO')), 1)
        self.assertEqual(len(store.get_events_by_category('INVENTARIO')), 2)
        self.assertEqual(len(store.get_events_by_type('STOCK_BAJO')), 2)

    def test_dedup_and_transitions_recurrence(self):
        e = evento()
        self.assertTrue(self.bus.publish(e, deduplicate=True))
        self.assertFalse(self.bus.publish(e))
        self.assertFalse(self.bus.publish(evento(), deduplicate=True))
        self.assertTrue(self.bus.publish(evento(), transition='stock:7', state='BAJO'))
        self.assertFalse(self.bus.publish(evento(), transition='stock:7', state='BAJO'))
        self.assertTrue(self.bus.publish(evento(type='STOCK_NORMALIZADO'), transition='stock:7', state='NORMAL'))
        self.assertTrue(self.bus.publish(evento(), transition='stock:7', state='BAJO'))

    def test_immutable_payload_and_frame_ownership(self):
        import numpy as np
        data = {'items': [{'value': 1}]}; frame = np.ones((2, 3, 3), dtype='uint8')
        e = evento(data=data, image=frame)
        data['items'][0]['value'] = 8; frame[:] = 0
        self.assertEqual(e.data['items'][0]['value'], 1)
        with self.assertRaises(TypeError): e.data['items'][0]['value'] = 5
        other = e.image.array(); other[:] = 0
        self.assertTrue(e.image.array().all())
        self.bus.publish(e)
        self.assertIsNone(self.bus.store.get_recent_events()[0].image)

    def test_logger_redaction(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'events.log'; logger = EventLogger(path)
            self.bus.subscribe('*', logger)
            self.bus.publish(evento(message='password=oculto token=secreto rtsp://user:pass@host/camera', data={'password': 'sensible'}))
            logger.close()
            content = path.read_text(encoding='utf-8')
            for word in ('oculto', 'secreto', 'sensible', 'user:pass'): self.assertNotIn(word, content)
            self.assertIn('STOCK_BAJO', content)

    def test_startup_names_are_idempotent(self):
        received = []
        first = self.bus.subscribe('*', received.append, name='consumer')
        second = self.bus.subscribe('*', received.append, name='consumer')
        self.assertIs(first, second)
        self.bus.publish(evento()); self.assertEqual(len(received), 1)

    def test_delayed_transaction_cannot_restore_older_state(self):
        now=datetime.now(timezone.utc)
        self.bus.publish(evento(type='STOCK_NORMALIZADO',timestamp=now),transition='stock:7',state='NORMAL')
        self.assertFalse(self.bus.publish(evento(timestamp=now-timedelta(seconds=1)),transition='stock:7',state='BAJO'))
        self.assertFalse(self.bus.publish(evento(type='STOCK_NORMALIZADO',timestamp=now+timedelta(seconds=2)),transition='stock:7',state='NORMAL'))
        self.assertFalse(self.bus.publish(evento(timestamp=now+timedelta(seconds=1)),transition='stock:7',state='BAJO'))

    def test_async_consumer_does_not_block_publisher(self):
        import threading,time
        entered,release=threading.Event(),threading.Event()
        def slow(e):entered.set();release.wait(2)
        self.bus.subscribe('*',slow,asynchronous=True)
        try:
            start=time.monotonic();self.bus.publish(evento())
            self.assertLess(time.monotonic()-start,.2)
            self.assertTrue(entered.wait(1))
        finally:release.set()


if __name__ == '__main__': unittest.main()
