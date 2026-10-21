"""Central availability contracts; no network, audio, SQL or physical devices."""
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from unittest.mock import patch,Mock
from core.system_state import SystemStateManager,ServiceState,SERVICES,format_service_state
from core.event_bus import EventBus


def aislar_estado(case):
    """Reset the shared object's observations without creating service managers."""
    from core.system_state import state_manager
    for field,value in (('_states',{s:ServiceState(s) for s in SERVICES}),('_subscribers',{}),('_resources',{}),('shutting_down',False)):
        p=patch.object(state_manager,field,value);p.start();case.addCleanup(p.stop)


class EstadoCentral(unittest.TestCase):
    def setUp(self):
        self.manager=SystemStateManager();self.bus=EventBus()
        p=patch('core.event_bus.event_bus',self.bus);p.start();self.addCleanup(p.stop)
        self.addCleanup(self.bus.close)

    def test_initial_get_and_allowed_status(self):
        self.assertEqual(self.manager.get('Cámara').status,'UNVERIFIED')
        self.assertFalse(self.manager.is_available('SQL'))
        with self.assertRaises(ValueError):self.manager.update('SQL','Disponible')

    def test_snapshot_and_details_immutable(self):
        data={'items':[{'ready':True}],'token':'oculto','url':'rtsp://user:pwd@host'}
        self.manager.update('SFACE','ONLINE',details=data)
        data['items'][0]['ready']=False
        copy=self.manager.snapshot();copy['SFACE']['details']['items'][0]['ready']=False
        value=self.manager.get('SFACE')
        self.assertTrue(value.details['items'][0]['ready'])
        self.assertNotIn('token',value.details)
        self.assertNotIn('pwd',str(value.details))
        with self.assertRaises(TypeError):value.details['change']=True

    def test_sql_sequence_exact_events_no_repeats(self):
        for status in ('STARTING','ONLINE','ONLINE','OFFLINE','OFFLINE','ONLINE'):
            self.manager.update('SQL',status)
        types=[e.type for e in reversed(self.bus.store.get_recent_events()) if e.type.startswith('SQL_')]
        self.assertEqual(types,['SQL_CONECTADO','SQL_DESCONECTADO','SQL_CONECTADO'])

    def test_activity_does_not_reconnect(self):
        for status,activity in (('ONLINE','IDLE'),('ONLINE','STREAMING'),('ONLINE','IDLE'),('OFFLINE','IDLE')):
            self.manager.update('CAMARA',status,activity=activity)
        types=[e.type for e in reversed(self.bus.store.get_recent_events())]
        self.assertEqual(types,['CAMARA_CONECTADA','CAMARA_DESCONECTADA'])

    def test_observers_error_isolated_and_unsubscribe(self):
        received=[]
        def fail(state):raise RuntimeError()
        self.manager.subscribe_all(fail)
        token=self.manager.subscribe('SQL',received.append)
        with self.assertLogs('system_state',level='ERROR'):
            self.manager.update('SQL','ONLINE');self.manager.update('SQL','ONLINE')
        self.assertEqual(len(received),1)
        self.manager.unsubscribe(token)
        with self.assertLogs('system_state',level='ERROR'):self.manager.update('SQL','OFFLINE')
        self.assertEqual(len(received),1)

    def test_concurrent_observations(self):
        with ThreadPoolExecutor(10) as executor:
            list(executor.map(lambda i:self.manager.update('SQL','ONLINE',details={'check':i}),range(100)))
        self.assertEqual(self.manager.get('SQL').revision,100)
        self.assertEqual(len(self.bus.store.get_events_by_type('SQL_CONECTADO')),1)

    def test_error_recovery_and_activity_preserves_error(self):
        self.manager.update('SQL','ERROR',error='SQL_FAILURE')
        first=self.manager.get('SQL').last_error
        self.manager.set_activity('SQL','IDLE')
        self.assertEqual(self.manager.get('SQL').error,'SQL_FAILURE')
        self.assertEqual(self.manager.get('SQL').last_error,first)
        self.manager.update('SQL','ONLINE')
        self.assertIsNone(self.manager.get('SQL').error)
        self.assertIsNotNone(self.manager.get('SQL').last_success)

    def test_shutdown_suppresses_connection_events(self):
        self.manager.update('SQL','ONLINE');self.manager.begin_shutdown()
        self.manager.update('SQL','OFFLINE')
        self.assertFalse(self.bus.store.get_events_by_type('SQL_DESCONECTADO'))

    def test_simulation_and_presentation(self):
        value=self.manager.update('ARDUINO','DEGRADED',available=True,details={'mode':'SIMULATION'},activity='SIMULATION')
        self.assertTrue(value.available);self.assertNotEqual(value.status,'ONLINE')
        self.assertIn('Simulación',format_service_state(value)['text'])
        self.assertFalse(self.bus.store.get_events_by_type('ARDUINO_CONECTADO'))

    def test_model_lifetime_is_independent_of_camera(self):
        class Resource:pass
        first,second=Resource(),Resource()
        self.manager.track_resource('SFACE',first,available=True,message='Listo',details={'model_loaded':True})
        self.manager.track_resource('SFACE',second,available=True,message='Listo',details={'model_loaded':True})
        self.manager.update('CAMARA','OFFLINE',expected=True)
        self.assertEqual(self.manager.get('SFACE').status,'ONLINE')
        del first
        self.assertEqual(self.manager.get('SFACE').status,'ONLINE')
        del second
        self.assertEqual(self.manager.get('SFACE').status,'OFFLINE')

    def test_incomplete_gallery_does_not_hide_another_ready_instance(self):
        class Resource:pass
        ready,incomplete=Resource(),Resource()
        self.manager.track_resource('SFACE',ready,available=True,message='Listo',details={'embeddings':5,'calibrated':True})
        self.manager.track_resource('SFACE',incomplete,available=False,message='Sin galería',details={'embeddings':0,'calibrated':False})
        self.assertTrue(self.manager.get('SFACE').available)
        self.assertEqual(self.manager.get('SFACE').details['embeddings'],5)
        del ready
        self.assertEqual(self.manager.get('SFACE').status,'DEGRADED')
        self.assertFalse(self.manager.get('SFACE').available)


class IntegracionEstado(unittest.TestCase):
    def setUp(self):
        aislar_estado(self)
        self.bus=EventBus();p=patch('core.event_bus.event_bus',self.bus);p.start();self.addCleanup(p.stop)

    def test_tts_real_fallback_flow_does_not_disable_jarvis(self):
        from jarvis import asistente_voz as voice
        from core.system_state import state_manager
        state_manager.update('JARVIS','ONLINE')
        with patch.object(voice,'edge_tts_disponible',True),patch.object(voice,'_hablar_edge'),patch.object(voice,'_hablar_pyttsx3'):
            voice._evento_detener_voz.clear();voice._reproducir_tts('Localizado.')
            self.assertEqual(state_manager.get('TTS').status,'ONLINE')
        with patch.object(voice,'edge_tts_disponible',True),patch.object(voice,'_hablar_edge',side_effect=RuntimeError()),patch.object(voice,'_hablar_pyttsx3'):
            voice._reproducir_tts('Localizado.')
            self.assertEqual(state_manager.get('TTS').status,'DEGRADED')
            self.assertTrue(state_manager.get('TTS').available)
            self.assertEqual(state_manager.get('TTS').details['provider'],'pyttsx3')
        with patch.object(voice,'edge_tts_disponible',False),patch.object(voice,'_hablar_pyttsx3',side_effect=RuntimeError()):
            with self.assertRaises(RuntimeError):voice._reproducir_tts('Localizado.')
            self.assertEqual(state_manager.get('TTS').status,'OFFLINE')
            self.assertEqual(state_manager.get('JARVIS').status,'ONLINE')

    def test_views_are_readers_and_never_probe(self):
        from jarvis import jarvis_consultas
        from core import estado_sistema
        from core.system_state import state_manager
        state_manager.update('CAMARA','ONLINE',activity='STREAMING')
        with patch('core.database.conectar',side_effect=AssertionError('No SQL health check in views')), \
             patch('jarvis.asistente_voz.obtener_ruta_modelo',side_effect=AssertionError('No filesystem/model probe')):
            snapshot=state_manager.snapshot()
            self.assertEqual(jarvis_consultas.obtener_estado_sistema(),snapshot)
            self.assertEqual(estado_sistema.obtener_estado_sistema()['snapshot'],snapshot)
            self.assertIn('Transmitiendo',jarvis_consultas.estado()['Cámara'])

    def test_health_cache_and_stop(self):
        from core import health_monitor as health
        monitor=health.HealthMonitor();check=Mock()
        monitor.register('SQL',check,30)
        for _ in range(20):monitor.check('SQL')
        self.assertEqual(check.call_count,1)
        monitor.check('SQL',force=True);self.assertEqual(check.call_count,2)
        monitor.start();monitor.close()
        self.assertFalse(monitor.thread.is_alive())

    def test_sql_check_uses_real_service_contract_mocked_connection(self):
        from core.health_monitor import _sql
        from core.system_state import state_manager
        with patch('core.database.conectar',return_value=Mock()):_sql()
        self.assertEqual(state_manager.get('SQL').status,'ONLINE')
        with patch('core.database.conectar',side_effect=ConnectionError()):_sql()
        self.assertEqual(state_manager.get('SQL').status,'OFFLINE')

    def test_manual_tts_diagnostic_preserves_local_fallback(self):
        from core.system_state import state_manager
        from core import estado_sistema
        def reproduce(text):
            state_manager.update('TTS','DEGRADED',available=True,details={'provider':'pyttsx3','fallback':True})
            return 'pyttsx3'
        with patch('jarvis.asistente_voz.hablar',side_effect=reproduce):
            result=estado_sistema.comprobar('Motor TTS')
        self.assertEqual(result['estado'],'DEGRADED')
        self.assertTrue(state_manager.get('TTS').available)

    def test_telegram_transient_failure_and_recovery_are_central(self):
        from core.system_state import state_manager
        from integrations.telegram import telegram_service
        with patch.object(telegram_service.servicio_telegram,'hilo',Mock()),patch('core.config_manager.obtener',return_value=True):
            telegram_service._reportar_transporte(True,'Confirmado')
            success=state_manager.get('TELEGRAM').last_success
            telegram_service._reportar_transporte(False,'Sin respuesta',temporary=True)
            state=state_manager.get('TELEGRAM')
            self.assertEqual(state.status,'DEGRADED');self.assertTrue(state.available)
            self.assertEqual(state.last_success,success)
            telegram_service._reportar_transporte(False,'Rechazado')
            self.assertEqual(state_manager.get('TELEGRAM').status,'ERROR')
            telegram_service._reportar_transporte(True,'Confirmado')
            self.assertEqual(state_manager.get('TELEGRAM').status,'ONLINE')

    def test_tk_header_dashboard_estado_and_jarvis_share_camera_state(self):
        import ast,threading,tkinter as tk
        from tkinter import ttk
        from pathlib import Path
        from core.system_state import state_manager,health_summary
        from ui.service_state_ui import StateBinding
        from ui.ui_theme import configurar_estilos
        from ui.interfaz import _tabla
        from ui.dashboard import Dashboard
        from ui.estado_ui import EstadoUI
        from jarvis import jarvis_consultas
        try:root=tk.Tk()
        except tk.TclError as error:self.skipTest('Tk no disponible: '+str(error))
        root.withdraw();configurar_estilos(root)
        dashboard=None;estado=None;binding=None
        try:
            # Exercise the actual header formatter function, without starting the app.
            tree=ast.parse(Path('ui/interfaz.py').read_text(encoding='utf-8'))
            startup=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='iniciar_aplicacion')
            header=next(n for n in startup.body if isinstance(n,ast.FunctionDef) and n.name=='actualizar_badges')
            badges={n:ttk.Label(root) for n in ('Base de datos','JARVIS','Cámara','Sistema')}
            env=dict(format_service_state=format_service_state,health_summary=health_summary,badges=badges,estado_footer=ttk.Label(root))
            exec(compile(ast.Module(body=[header],type_ignores=[]),'ui/interfaz.py','exec'),env)
            binding=StateBinding(root,env['actualizar_badges'],root)
            dashboard=Dashboard(ttk.Frame(root),root,_tabla,[],tk.StringVar(root),tk.StringVar(root))
            estado=EstadoUI(ttk.Frame(root),root)
            with patch.object(dashboard,'actualizar'),patch('core.database.conectar',side_effect=AssertionError('View must not check SQL')):
                def transmitir():
                    state_manager.update('CAMARA','ONLINE',activity='STREAMING')
                    state_manager.update('CAMARA_1','ONLINE',activity='STREAMING')
                    state_manager.update('CAMARA_2','OFFLINE',activity='IDLE',expected=True)
                worker=threading.Thread(target=transmitir)
                worker.start();worker.join(1)
                root.after(350,root.quit);root.mainloop()
                view=format_service_state(state_manager.get('CAMARA'))['text']
                self.assertIn('CAMARA_1: ONLINE',badges['Cámara'].estado_detalle)
                self.assertIn('CAMARA_2: OFFLINE',badges['Cámara'].estado_detalle)
                self.assertEqual(badges['Cámara'].cget('text'),'Cámaras 1/2 ONLINE')
                self.assertEqual(dashboard.estados_servicio['CAMARA'].get(),view)
                self.assertIn(view,estado.t.item('Cámara','values')[1])
                self.assertTrue(estado.t.exists('Cámara 1 · Intrusión'))
                self.assertTrue(estado.t.exists('Cámara 2 · Presencia'))
                self.assertEqual(jarvis_consultas.estado()['Cámara'],view)
        finally:
            if binding:binding.close()
            if estado:estado.binding.close()
            if dashboard:dashboard.cerrar()
            root.destroy()


if __name__=='__main__':unittest.main()
