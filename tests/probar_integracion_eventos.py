"""Event pipelines with isolated persistence, transport and camera evidence."""
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch
import numpy as np
from core import event_bus as core
from core.event_logger import EventLogger
from core.event_subscribers import iniciar_eventos
from core.eventos_servicios import (publicar_stock, publicar_vigilancia,
    publicar_rostro_desconocido, publicar_reconocimiento_empleado,
    informar_estado_componente, publicar_prediccion)


class Integracion(unittest.TestCase):
    def setUp(self):
        from tests.probar_system_state import aislar_estado
        aislar_estado(self)
        self.bus = core.EventBus()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'events.log'
        self.logger = EventLogger(self.path)
        self.patchers = [patch('core.event_bus.event_bus', self.bus),
            patch('inventory.alertas.verificar_alertas_stock'),
            patch('inventory.alertas.registrar_alerta_intrusion', return_value={'id_alerta': 7, 'creada': True}),
            patch('inventory.alertas.registrar_alerta_empleado_no_reconocido', return_value={'id_alerta': 8}),
            patch('integrations.telegram.telegram_service.servicio_telegram.notificar', return_value={'estado':'PENDIENTE'}),
            patch('integrations.telegram.telegram_service.enviar_evento', return_value={'enviado':False,'detalle':'En cola'}),
            patch('integrations.telegram.telegram_service.notificar_rostro_desconocido'),
            patch('integrations.telegram.telegram_service.notificar_reconocimiento_empleado'),
            patch('ai.prediction.prediccion_stock._actualizar_alerta')]
        self.mocks = [p.start() for p in self.patchers]
        iniciar_eventos(self.bus, self.logger)

    def tearDown(self):
        self.bus.flush(); self.bus.close(); self.logger.close()
        for p in reversed(self.patchers): p.stop()
        self.tmp.cleanup()

    def flush(self): self.assertTrue(self.bus.flush())

    def test_stock_real_transaction_entrypoint_one_transition(self):
        from inventory import movimientos as mov
        connection = Mock(); order = []
        connection.cursor.return_value.execute.return_value.fetchone.return_value=('Filtro','FIL-001',Decimal(5),Decimal(4),'Ana',__import__('datetime').datetime.now())
        connection.commit.side_effect = lambda: order.append('commit')
        def stock(p, **kwargs):
            self.assertFalse(self.bus.store.get_recent_events())
            publicar_stock(p, Decimal(4), Decimal(5), 'Filtro')
        self.bus.subscribe('STOCK_BAJO', lambda e: order.append('event'), name='order')
        from core.automatizacion_inventario import AutomatizacionInventario
        servicio=AutomatizacionInventario(self.bus)
        self.bus.subscribe('MOVIMIENTO_REGISTRADO',servicio.movimiento)
        with patch('ai.anomalies.deteccion_anomalias.evaluar_movimiento_incremental'), patch.object(servicio,'programar'), \
             patch.object(mov,'conectar',return_value=connection), \
             patch.object(mov,'_bloquear_producto'), patch.object(mov,'_validar_entidades',return_value=False), \
             patch.object(mov,'_saldo',return_value=Decimal(10)), patch.object(mov,'_poner_saldo'), \
             patch.object(mov,'_crear_movimiento',return_value=42), patch.object(mov,'_guardar_detalle'), \
             patch.object(mov,'evaluar_salida_para_alertas'), patch.object(mov,'verificar_alertas_stock',side_effect=stock), \
             patch('inventory.lotes_service.actualizar_alertas_vencimiento'):
            self.assertEqual(mov.registrar_salida(2, 7, 3, 6),42)
        publicar_stock(7, Decimal(4), Decimal(5), 'Filtro')
        self.flush()
        self.assertEqual(order,['commit','event'])
        self.mocks[1].assert_called_once_with(7, publicar_stock_evento=False)
        self.mocks[4].assert_called_once()
        self.assertEqual(len(self.bus.store.get_events_by_type('STOCK_BAJO')),1)
        self.assertEqual(len(self.bus.store.get_events_by_type('MOVIMIENTO_REGISTRADO')),1)
        self.assertIn('STOCK_BAJO',self.path.read_text(encoding='utf-8'))

    def test_rollback_discards_all_events_and_state(self):
        from inventory import movimientos as mov
        connection = Mock()
        def operation(q):
            publicar_stock(7,0,5)
            raise ValueError('Rejected operation')
        with patch.object(mov,'conectar',return_value=connection):
            with self.assertRaises(ValueError): mov._transaccion(operation)
        connection.rollback.assert_called_once()
        self.assertFalse(self.bus.store.get_recent_events())
        publicar_stock(7,0,5);self.flush()
        self.assertEqual(len(self.bus.store.get_recent_events(type='STOCK_AGOTADO')),1)

    def test_committed_stock_alert_is_not_recalculated_by_consumer(self):
        publicar_stock(7,4,5,alertas_actualizadas=True);self.flush()
        self.mocks[1].assert_not_called()
        self.mocks[4].assert_called_once()

    def test_intrusion_snapshot_and_clip_one_domain_event(self):
        data=dict(id_evento='ab12',tipo_evento='INTRUSIÓN',camara='Almacén',zona='Acceso',
                  captura='snapshot.jpg',clip='clip.mp4',nivel='ALTA',track_id=4)
        publicar_vigilancia(data)
        publicar_vigilancia(data)
        publicar_vigilancia(data,'video');self.flush()
        self.mocks[2].assert_called_once()
        self.assertEqual(self.mocks[5].call_count,2)
        self.assertEqual(self.mocks[5].call_args_list[0].args[1],'snapshot.jpg')
        self.assertTrue(self.mocks[5].call_args_list[1].kwargs['video'])
        self.assertEqual(len(self.bus.store.get_events_by_type('INTRUSION_DETECTADA')),1)
        self.assertIn('INTRUSION_DETECTADA',self.path.read_text(encoding='utf-8'))

    def test_unknown_valid_sface_with_snapshot_one_alert(self):
        frame=np.ones((8,8,3),dtype='uint8')
        result=dict(estado_identidad='NO_RECONOCIDO',identidad_evaluada=True,motor='sface')
        publicar_rostro_desconocido(result,frame,referencia='track:8')
        publicar_rostro_desconocido(result,frame,referencia='track:8');self.flush()
        self.mocks[3].assert_called_once()
        self.mocks[6].assert_called_once()
        self.assertFalse(self.mocks[6].call_args.kwargs['crear_alerta'])
        self.assertTrue((self.mocks[6].call_args.args[1]==frame).all())
        self.assertEqual(len(self.bus.store.get_events_by_type('ROSTRO_NO_RECONOCIDO')),1)
        self.assertIn('ROSTRO_NO_RECONOCIDO',self.path.read_text(encoding='utf-8'))

    def test_no_face_or_bad_quality_is_not_unknown(self):
        for result in (dict(estado_identidad='ROSTRO_NO_VISIBLE'),
                       dict(estado_identidad='NO_RECONOCIDO',identidad_evaluada=False),
                       dict(estado='DESCONOCIDO',calidad_estado='BAJA_CALIDAD'),
                       dict(estado='DESCONOCIDO',motor='cnn')):
            self.assertIsNone(publicar_rostro_desconocido(result,None))
        self.assertFalse(self.bus.store.get_recent_events())

    def test_telegram_failure_does_not_break_alert_store_or_log(self):
        self.mocks[4].side_effect=RuntimeError('Transport failure')
        with self.assertLogs('event_bus',level='ERROR'):
            publicar_stock(7,1,5);self.flush()
        self.mocks[1].assert_called_once()
        self.assertEqual(len(self.bus.store.get_recent_events()),1)
        self.assertIn('STOCK_BAJO',self.path.read_text(encoding='utf-8'))

    def test_services_transitions_not_polling_spam(self):
        with ThreadPoolExecutor(8) as executor:
            list(executor.map(lambda _: informar_estado_componente('SQL',False,'No disponible'),range(40)))
        informar_estado_componente('SQL',True,'Restablecido')
        informar_estado_componente('SQL',False,'Nueva caída');self.flush()
        self.assertEqual(len(self.bus.store.get_events_by_type('SQL_DESCONECTADO')),2)
        self.assertEqual(self.mocks[4].call_count,2)

    def test_risk_transition_and_passive_calculations(self):
        r=dict(riesgo='CRÍTICO',datos_suficientes=True,explicacion='Cobertura de dos días.',producto='Filtro',dias_restantes_promedio=2)
        for _ in range(3):publicar_prediccion(7,r,notificar=True)
        publicar_prediccion(8,r,notificar=False);self.flush()
        self.assertEqual(self.mocks[4].call_count,1)
        self.assertEqual(len(self.bus.store.get_events_by_type('PREDICCION_GENERADA')),4)
        self.assertEqual(self.bus.errors,0)

    def test_ui_and_startup_subscriptions_not_duplicated(self):
        iniciar_eventos(self.bus,self.logger)
        publicar_stock(7,0,5);self.flush()
        self.mocks[1].assert_called_once();self.mocks[4].assert_called_once()

    def test_real_evidence_worker_publishes_snapshot_without_camera(self):
        from copy import deepcopy
        from core.config_manager import DEFAULTS
        from surveillance.vigilancia_yolo import EvidenciaIntrusion
        cfg=deepcopy(DEFAULTS['vigilancia'])
        cfg.update(clip_before_seconds=0,clip_after_seconds=0,zone_polygon=[[0,0],[1,0],[1,1],[0,1]])
        evidence=EvidenciaIntrusion(cfg,self.tmp.name)
        try:
            original=evidence.registrar(dict(track_id=3,bbox=[10,10,200,300],confianza=.9),np.zeros((480,640,3),dtype='uint8'),0)
            evidence.disco.join();evidence.red.join();self.flush()
            event=self.bus.store.get_events_by_type('INTRUSION_DETECTADA')[0]
            self.assertEqual(event.data['id_evento'],original['id_evento'])
            self.assertTrue(Path(event.image).is_file())
            self.mocks[2].assert_called_once()
            self.mocks[5].assert_called_once()
        finally:
            evidence.cerrar()
            for worker in evidence.hilos:worker.join(2)

    def test_led_publishes_only_after_ack_and_labels_simulation(self):
        from copy import deepcopy
        from core.config_manager import DEFAULTS
        from integrations.arduino.led_service import ServicioLED
        from tests.probar_led_service import Puerto
        cfg=deepcopy(DEFAULTS['arduino']);port=Puerto()
        led=ServicioLED(lambda:cfg,lambda **kwargs:port)
        led.encender_led(2)
        self.assertEqual(self.bus.store.get_events_by_type('LED_ACTIVADO')[0].data['modo'],'simulacion')
        cfg.update(modo='hardware',habilitado=True,puerto='COM7',timeout=.2)
        port.respuestas=[b'PONG\n']
        with patch('integrations.arduino.led_service.time.sleep'):led.conectar()
        port.respuestas=[b'ERROR:OUTPUT_NOT_CONFIGURED\n']
        with self.assertRaises(ValueError):led.encender_led(3)
        self.assertEqual(len(self.bus.store.get_events_by_type('LED_ACTIVADO')),1)
        self.flush()

    def test_new_anomaly_subscriber_uses_idempotent_alert_service(self):
        from core.eventos_servicios import publicar_anomalia
        with patch('inventory.alertas.registrar_alerta_anomalia_evento',return_value={'id_alerta':9,'creada':True}) as registrar:
            data=dict(id_anomalia=4,id_detalle=8,id_producto=7,id_movimiento=42,nivel='CRÍTICA',motivo='Cantidad inusual')
            publicar_anomalia(data);publicar_anomalia(data);self.flush()
            registrar.assert_called_once()
            self.mocks[4].assert_called_once()
            self.assertEqual(len(self.bus.store.get_events_by_type('ALERTA_CREADA')),1)

    def test_anomaly_persistence_publishes_only_new_committed_rows(self):
        from ai.anomalies import deteccion_anomalias as anomaly
        connection=Mock();cursor=connection.cursor.return_value
        data=dict(id_detalle=8,tipo_anomalia='Cantidad inusual',nivel='ALTA',score=.8,
                  motivo='Cantidad inusual',referencia_historica='Historial disponible')
        # First insert produces a real persisted ID; the repeat returns NULL.
        cursor.fetchone.side_effect=[(9,),(None,)]
        with patch.object(anomaly,'conectar',return_value=connection), \
             patch('inventory.alertas.registrar_alerta_anomalia_evento',return_value=None):
            anomaly.guardar_hallazgos([data]);anomaly.guardar_hallazgos([data]);self.flush()
        self.assertEqual(connection.commit.call_count,2)
        self.assertEqual(len(self.bus.store.get_events_by_type('ANOMALIA_DETECTADA')),1)

    def test_jarvis_queries_current_store_no_sql(self):
        from jarvis.tools import eventos
        with patch.object(eventos,'event_store',self.bus.store):
            self.assertIn('No hay intrusiones',eventos.responder_eventos('hubo alguna intrusion')[1])
            publicar_stock(7,0,5);self.flush()
            self.assertEqual(eventos.obtener_ultimo_evento()['type'],'STOCK_AGOTADO')
            self.assertEqual(len(eventos.obtener_eventos_categoria('INVENTARIO')),1)
            self.assertEqual(len(eventos.responder_eventos('hay algo critico')[0]),1)
            self.assertEqual(len(eventos.responder_eventos('que acaba de pasar')[0]),1)

    def test_dashboard_event_worker_never_updates_tk(self):
        import threading
        import tkinter as tk
        from tkinter import ttk
        from ui.dashboard import Dashboard
        from ui.ui_theme import configurar_estilos
        from ui.interfaz import _tabla
        try:root=tk.Tk()
        except tk.TclError as error:self.skipTest('Tk no disponible: '+str(error))
        root.withdraw();configurar_estilos(root)
        dashboard=None
        try:
            dashboard=Dashboard(ttk.Frame(root),root,_tabla,[],tk.StringVar(root),tk.StringVar(root))
            called=[]
            with patch.object(dashboard,'actualizar',side_effect=lambda:called.append(threading.get_ident())):
                worker=threading.Thread(target=lambda:publicar_stock(7,0,5))
                worker.start();worker.join(1)
                self.assertFalse(called)
                root.after(150,root.quit);root.mainloop()
                self.assertEqual(called,[threading.get_ident()])
            dashboard.cerrar()
            self.assertTrue(dashboard.suscripcion_eventos.closed.is_set())
        finally:
            if dashboard and not dashboard.cerrado:dashboard.cerrar()
            root.destroy()


if __name__=='__main__':unittest.main()
