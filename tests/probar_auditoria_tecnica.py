"""Technical traces with isolated persistence, transport and devices."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from core import audit_service as tracing
from core.event_bus import EventBus
from core.system_event import SystemEvent


class AuditFixture(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.service=tracing.AuditService(self.tmp.name)
        self.addCleanup(self.service.close)
        self.patch=patch.object(tracing.audit,'record',side_effect=self.service.record)
        self.patch.start();self.addCleanup(self.patch.stop)

    def rows(self):
        self.assertTrue(self.service.flush())
        path=Path(self.tmp.name)/'audit.jsonl'
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []


class Central(AuditFixture):
    def test_json_utf8_before_after_and_fields(self):
        with tracing.operation('MOVIMIENTOS','SALIDA',origin='desktop',entity_code='TOR-001') as r:
            r.update(before={'stock':Decimal('166.00')},after={'stock':Decimal('161.00')},data={'producto':'Tornillo galvanizado, ubicación'})
        rows=self.rows();self.assertEqual(len(rows),2)
        self.assertEqual(rows[-1]['before']['stock'],'166.00')
        self.assertEqual(rows[-1]['after']['stock'],'161.00')
        self.assertEqual(rows[0]['operation_id'],rows[1]['operation_id'])
        self.assertEqual(rows[-1]['origin'],'desktop')
        self.assertIsNotNone(rows[-1]['duration_ms'])
        self.assertIn('ubicación',(Path(self.tmp.name)/'audit.jsonl').read_text(encoding='utf-8'))
        self.assertIn('user_context',rows[-1])

    def test_nested_parent_and_context_reset(self):
        self.assertIsNone(tracing.current_context())
        with tracing.operation('JARVIS','COMMAND'):
            parent=tracing.capture_context()
            with tracing.operation('MOVIMIENTOS','CREATE'):
                child=tracing.capture_context()
        self.assertEqual(parent['correlation_id'],child['correlation_id'])
        self.assertEqual(parent['operation_id'],child['parent_operation_id'])
        self.assertIsNone(tracing.current_context())

    def test_errors_rethrow_original_and_sanitize_stack(self):
        original=ValueError('password=hidden-token https://api.telegram.org/bot123456:token/message')
        with self.assertRaises(ValueError) as raised:
            with tracing.operation('PREDICCION','CALCULATE'):raise original
        self.assertIs(raised.exception,original)
        row=self.rows()[-1]
        self.assertEqual(row['status'],'FAILED');self.assertEqual(row['error_type'],'ValueError')
        errors=(Path(self.tmp.name)/'errors.log').read_text(encoding='utf-8')
        self.assertIn('Traceback',errors);self.assertNotIn('hidden-token',errors)
        self.assertNotIn('api.telegram.org',errors)

    def test_recursive_secrets_biometrics_and_paths(self):
        data=tracing.sanitize_sensitive_data({'TELEGRAM_BOT_TOKEN':'sensitive',
            'nested':{'api_key':'sensitive2','connection_string':'Driver=x;PWD=abcd',
                      'embedding':[1,2,3]},'frame':b'raw',
            'message':'pwd=abcd Bearer xyzzzz AKIAABCDEFGHIJKLMNOP',
            'path':str(tracing.ROOT/'outputs'/'file.jpg')})
        text=json.dumps(data)
        for secret in ('sensitive','sensitive2','abcd','xyzzzz','AKIAABCDEFGHIJKLMNOP',str(tracing.ROOT)):
            self.assertNotIn(secret,text)
        self.assertEqual(data['nested']['embedding'],'[omitted]')
        self.assertEqual(data['path'],'outputs\\file.jpg')

    def test_rotation_json_valid_and_bounded(self):
        local=tracing.AuditService(Path(self.tmp.name)/'rotation',max_bytes=1800,backups=2)
        try:
            for i in range(30):local.record('SYSTEM','RECORD',data={'i':i})
            self.assertTrue(local.flush())
            paths=list(local.directory.glob('audit.jsonl*'))
            self.assertEqual(len(paths),3)
            for path in paths:
                for line in path.read_text(encoding='utf-8').splitlines():json.loads(line)
        finally:local.close()

    def test_thread_safety_and_isolated_contexts(self):
        def send(i):
            with tracing.use_context(tracing.AuditContext(origin='worker')):
                for j in range(10):tracing.audit.record('SYSTEM','CONCURRENT',data={'worker':i})
        with ThreadPoolExecutor(max_workers=6) as pool:list(pool.map(send,range(6)))
        rows=self.rows();self.assertEqual(len(rows),60)
        groups={i:{r['correlation_id'] for r in rows if r['data']['worker']==i} for i in range(6)}
        self.assertTrue(all(len(ids)==1 for ids in groups.values()))
        self.assertEqual(len({next(iter(ids)) for ids in groups.values()}),6)

    def test_disk_failure_never_breaks_operation(self):
        path=Path(self.tmp.name)/'unavailable';path.write_text('occupied')
        local=tracing.AuditService(path)
        try:
            with patch.object(tracing.audit,'record',side_effect=local.record):
                with tracing.operation('MOVIMIENTOS','SALIDA'):result=161
            self.assertTrue(local.flush());self.assertEqual(result,161)
            self.assertEqual(len(local.fallback),2);self.assertEqual(local.dropped,2)
        finally:local.close()

    def test_write_error_after_open_is_contained(self):
        local=tracing.AuditService(Path(self.tmp.name)/'disk')
        local._open()
        try:
            with patch.object(local.handlers['audit.jsonl'],'handle',side_effect=OSError('disk full')):
                local.record('SYSTEM','WRITE')
                self.assertTrue(local.flush())
            self.assertEqual(local.diagnostics()['unwritten'],1)
            self.assertEqual(len(local.fallback),1)
        finally:local.close()

    def test_consultation_filters_rotated_history(self):
        from tools.consultar_auditoria import consultar
        from argparse import Namespace
        from contextlib import redirect_stdout
        from io import StringIO
        with tracing.use_context(tracing.AuditContext(origin='voice')):
            correlation=tracing.capture_context()['correlation_id']
            tracing.audit.record('JARVIS','VOICE',entity_code='TOR-001')
        tracing.audit.record('SYSTEM','UNRELATED')
        self.rows()
        args=Namespace(archivo=str(Path(self.tmp.name)/'audit.jsonl'),correlation=correlation,
            source='JARVIS',action=None,status='SUCCESS',entity_code='TOR-001',category=None,
            desde=None,hasta=None,json=True)
        with redirect_stdout(StringIO()) as output:rows=consultar(args)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['origin'],'voice')
        self.assertEqual(json.loads(output.getvalue())['correlation_id'],correlation)

    def test_bus_async_derived_parent_context(self):
        bus=EventBus();self.addCleanup(bus.close)
        def derived(event):
            bus.publish(SystemEvent('STOCK_BAJO','INVENTARIO','stock','Stock bajo','Stock bajo'))
        bus.subscribe('MOVIMIENTO_REGISTRADO',derived,name='derived',asynchronous=True)
        with tracing.operation('MOVIMIENTOS','CREATE'):
            event=SystemEvent('MOVIMIENTO_REGISTRADO','MOVIMIENTOS','movimientos','Confirmado','Confirmado')
            bus.publish(event)
        self.assertTrue(bus.flush())
        derived=bus.store.get_events_by_type('STOCK_BAJO')[0]
        self.assertEqual(event.correlation_id,derived.correlation_id)
        self.assertEqual(event.operation_id,derived.parent_operation_id)
        self.assertEqual(event.correlation_id,event.record().correlation_id)
        self.assertIn('correlation_id',event.to_dict())

    def test_subscriber_failure_isolated_and_correlated(self):
        bus=EventBus();self.addCleanup(bus.close)
        bus.subscribe('*',Mock(side_effect=ValueError('pwd=secret')),name='broken')
        event=SystemEvent('STOCK_BAJO','INVENTARIO','stock','Stock bajo','Stock bajo')
        self.assertTrue(bus.publish(event));self.assertEqual(bus.errors,1)
        failed=[r for r in self.rows() if r['status']=='FAILED'][0]
        self.assertEqual(failed['correlation_id'],event.correlation_id)
        self.assertEqual(failed['data']['subscriber'],'broken')

    def test_optional_payload_does_not_break_delivery(self):
        bus=EventBus();self.addCleanup(bus.close)
        callback=Mock();bus.subscribe('*',callback,name='consumer')
        event=SystemEvent('STOCK_BAJO','INVENTARIO','stock','Stock bajo','Stock bajo',data=None)
        self.assertTrue(bus.publish(event));callback.assert_called_once_with(event)

    def test_committed_movement_and_rollback(self):
        from inventory import movimientos
        from core import event_bus
        bus=EventBus();self.addCleanup(bus.close)
        c=Mock()
        def write(q):
            event_bus.emitir('MOVIMIENTO_REGISTRADO','MOVIMIENTOS','movimientos','Salida',
                data={'stock_anterior':166,'stock_nuevo':161,'id_producto':15,'codigo':'TOR-001'})
            return 7
        with patch.object(event_bus,'event_bus',bus),patch.object(movimientos,'conectar',return_value=c):
            self.assertEqual(movimientos._transaccion(write),7)
            c.commit.side_effect=ValueError('commit unavailable')
            with self.assertRaises(ValueError):movimientos._transaccion(write)
        rows=[r for r in self.rows() if r['action']=='MOVIMIENTO_REGISTRADO']
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['before'],{'stock':166})
        self.assertEqual(rows[0]['after'],{'stock':161});self.assertEqual(c.rollback.call_count,1)

    def test_prediction_queue_error_trace_and_coalescence(self):
        from core.automatizacion_inventario import AutomatizacionInventario,ResultadosPrediccion
        from tests.probar_system_state import aislar_estado
        aislar_estado(self)
        bus=EventBus();self.addCleanup(bus.close)
        worker=AutomatizacionInventario(bus,ResultadosPrediccion(Path(self.tmp.name)/'predictions.json'))
        first=tracing.AuditContext(origin='telegram');second=tracing.AuditContext(origin='desktop')
        with tracing.use_context(first):worker.programar(15)
        with tracing.use_context(second):worker.programar(15)
        with patch('ai.prediction.prediccion_stock.predecir_agotamiento',side_effect=RuntimeError('model unavailable')):
            self.assertFalse(worker.procesar_prediccion(15))
        rows=self.rows()
        failed=[r for r in rows if r['source']=='PREDICCION' and r['status']=='FAILED']
        self.assertTrue(failed);self.assertTrue(all(r['correlation_id']==second.correlation_id for r in failed))
        self.assertTrue(any(r['action']=='RECALCULATION_LINKED' and r['correlation_id']==first.correlation_id for r in rows))
        self.assertIn(15,worker.pendientes)

    def test_telegram_queue_context_and_http_failure(self):
        from integrations.telegram import telegram_service as telegram
        service=telegram.ServicioTelegram()
        with tracing.use_context(tracing.AuditContext(origin='telegram')):
            context=tracing.capture_context()
            service.notificar('inventario','Stock','Stock bajo',referencia='audit:15')
        event=service.cola.get_nowait()
        self.assertEqual(event['_audit_context']['correlation_id'],context['correlation_id'])
        with patch.object(service,'_procesar_evento_observado',side_effect=lambda e:tracing.audit.record('TELEGRAM','IN_WORKER')):
            service._procesar_evento(event)
        with tracing.use_context(context),patch.object(telegram,'_enviar_observado',return_value={'enviado':False,'http':403}):
            self.assertFalse(telegram._enviar('sendMessage',{'text':'private'})['enviado'])
        rows=self.rows()
        self.assertTrue(all(r['correlation_id']==context['correlation_id'] for r in rows))
        self.assertEqual(rows[-1]['status'],'FAILED')
        self.assertNotIn('private',json.dumps(rows))

    def test_durable_telegram_context_survives_retry_and_commit_failure(self):
        from integrations.telegram import telegram_service as telegram
        service=telegram.ServicioTelegram()
        original=tracing.AuditContext(origin='telegram')
        payload={'titulo':'Stock','mensaje':'Stock bajo','datos':{},'imagen':None,'video':None,
                 'referencia':'audit:durable','_audit_context':tracing.asdict(original)}
        connection=Mock();cursor=connection.cursor.return_value
        def execute(sql,*args):
            result=Mock()
            result.fetchone.return_value=('inventario','ALTA','PENDIENTE',json.dumps(payload)) if sql.startswith('SELECT tipo') else (90,)
            return result
        cursor.execute.side_effect=execute
        observed=[]
        def transport(data,save):
            observed.append(tracing.current_context().correlation_id)
            return {'enviado':True,'http':200,'detalle':'Confirmed'}
        # First commit claims the notification; the second fails after HTTP success.
        connection.commit.side_effect=[None,RuntimeError('SQL write failed')]
        with patch('core.database.conectar',return_value=connection),patch.object(telegram,'_filtro_evento',return_value=None), \
             patch.object(telegram,'_entregar_contenido',side_effect=transport):
            with self.assertRaises(RuntimeError):service.entregar('audit:durable')
        self.assertEqual(observed,[original.correlation_id])
        failed=[r for r in self.rows() if r['action']=='NOTIFICATION_DELIVERY' and r['status']=='FAILED']
        self.assertEqual(len(failed),1)
        self.assertEqual(failed[0]['correlation_id'],original.correlation_id)
        connection.rollback.assert_called_once()


class JarvisTrace(AuditFixture):
    def setUp(self):
        super().setUp()
        from tests.probar_orquestador_jarvis import Orquestador
        from tests.probar_system_state import aislar_estado
        Orquestador.setUp(self);aislar_estado(self)

    def test_real_prepare_confirm_execute_same_trace(self):
        from jarvis import jarvis
        with patch('inventory.movimientos.registrar_salida',return_value=1001) as movement:
            prepared=jarvis.procesar('Registra salida de 5 TOR-001 por EMP-008',origen='telegram')
            self.assertTrue(prepared.requiere_confirmacion)
            confirmed=jarvis.procesar('Sí',origen='telegram')
            self.assertEqual(confirmed.intent,'accion_confirmada');movement.assert_called_once()
        rows=[r for r in self.rows() if r['source']=='JARVIS']
        self.assertEqual(len({r['correlation_id'] for r in rows}),1)
        self.assertTrue(any(r['status']=='CONFIRMATION_REQUIRED' for r in rows))
        self.assertTrue(any(r['status']=='CONFIRMED' for r in rows))
        self.assertTrue(any(r['action']=='TOOL_EXECUTE' and r['status']=='SUCCESS' for r in rows))

    def test_cancel_and_independent_request(self):
        from jarvis import jarvis
        first=jarvis.procesar('Registra salida de 5 TOR-001 por EMP-008')
        cancelled=jarvis.procesar('Cancelar')
        second=jarvis.procesar('Hola')
        self.assertEqual(first.extras['audit_context']['correlation_id'],cancelled.extras['audit_context']['correlation_id'])
        self.assertNotEqual(first.extras['audit_context']['correlation_id'],second.extras['audit_context']['correlation_id'])
        self.assertTrue(any(r['status']=='CANCELLED' for r in self.rows()))

    def test_desktop_voice_share_pending_trace_and_identify_origin(self):
        from jarvis import jarvis
        prepared=jarvis.procesar('Registra salida de 5 TOR-001 por EMP-008')
        with tracing.use_context(origin='voice'),patch('inventory.movimientos.registrar_salida',return_value=1001):
            confirmed=jarvis.procesar('Sí')
        self.assertEqual(prepared.extras['audit_context']['correlation_id'],confirmed.extras['audit_context']['correlation_id'])
        row=[r for r in self.rows() if r['status']=='CONFIRMED'][-1]
        self.assertEqual(row['origin'],'voice')

    def test_telegram_confirmation_to_automatic_delivery_end_to_end(self):
        from core import event_bus as core
        from inventory import movimientos
        from integrations.telegram import telegram_bot_service as bot
        from integrations.telegram import telegram_service as telegram
        from core.automatizacion_inventario import AutomatizacionInventario,ResultadosPrediccion
        bus=EventBus();self.addCleanup(bus.close)
        engine=AutomatizacionInventario(bus,ResultadosPrediccion(Path(self.tmp.name)/'predictions.json'))
        sender=telegram.ServicioTelegram();sender.directorio=Path(self.tmp.name)/'outbound'
        listener=bot.TelegramBotService()
        listener.sessions['1234']={'modo_jarvis':True,'jarvis_session_id':'telegram:1234'}
        from jarvis import agente_inventario as agente
        agente.reiniciar_contexto('telegram:1234')
        bus.subscribe('MOVIMIENTO_REGISTRADO',engine.movimiento,name='automation',asynchronous=True)
        def notify(event):
            sender.notificar('inventario','Stock bajo','Stock bajo',referencia=event.id)
        bus.subscribe('STOCK_BAJO',notify,name='notification')
        def movement(*args,**kwargs):
            def committed(q):
                core.emitir('MOVIMIENTO_REGISTRADO','MOVIMIENTOS','movimientos','Salida confirmada',
                    data={'id_movimiento':90,'id_producto':1,'stock_anterior':43,'stock_nuevo':5,
                          'stock_minimo':10,'tipo_movimiento':'Salida','codigo':'TOR-001','cantidad':38})
                return 90
            return movimientos._transaccion(committed)
        def anomalies(*args):
            with tracing.operation('ANOMALIAS','ANOMALY_ANALYSIS'):
                core.emitir('ANOMALIA_DETECTADA','ANOMALIAS','deteccion_anomalias','Cantidad inusual',
                            data={'id_movimiento':90,'id_producto':1})
        def message(text):return listener.procesar_actualizacion({'message':{'chat':{'id':1234},'text':text}})
        with patch.object(core,'event_bus',bus),patch.object(bot,'_credenciales',return_value=('token','1234')), \
             patch.object(bot,'enviar_respuesta_chat',return_value={'enviado':True}), \
             patch.object(movimientos,'conectar',return_value=Mock()), \
             patch.object(movimientos,'registrar_salida',side_effect=movement), \
             patch('ai.anomalies.deteccion_anomalias.evaluar_movimiento_incremental',side_effect=anomalies), \
             patch('ai.prediction.prediccion_stock.predecir_agotamiento',return_value={'riesgo':'ALTO','datos_suficientes':True,'stock_actual':5}):
            message('Registra salida de 38 TOR-001 por EMP-008')
            expected=agente.obtener_contexto('telegram:1234')['confirmacion_pendiente']['_audit_context']['correlation_id']
            message('Sí');self.assertTrue(bus.flush())
            self.assertTrue(engine.procesar_prediccion(1))
            event=sender.cola.get_nowait()
            def deliver(reference):return telegram._enviar('sendMessage',{'text':'Stock bajo'})
            with patch.object(sender,'_guardar'),patch.object(sender,'entregar',side_effect=deliver), \
                 patch.object(telegram,'_enviar_observado',return_value={'enviado':True,'http':200,'ok':True}):
                sender._procesar_evento(event)
        rows=self.rows()
        steps=['JARVIS_CONFIRMATION','TOOL_EXECUTE','MOVIMIENTO_REGISTRADO','STOCK_BAJO',
               'ANOMALIA_DETECTADA','PREDICTION_UPDATE','NOTIFICATION_ENQUEUED','sendMessage']
        for step in steps:
            selected=[r for r in rows if r['action']==step]
            self.assertTrue(selected,step)
            self.assertTrue(all(r['correlation_id']==expected for r in selected),step)


if __name__=='__main__':unittest.main()
