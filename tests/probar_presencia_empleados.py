"""Presencia y aislamiento de cámaras; sin dispositivos, SQL ni envíos reales."""
from copy import deepcopy
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock,patch
import numpy as np

from core.config_manager import DEFAULTS
from surveillance import presencia_empleados as p


def deteccion(i=1,sample=None,known=False,unknown=False):
    d=dict(track_id=i,bbox=[i*30,10,i*30+25,90],confianza=.91,
           estado_identidad='ROSTRO_NO_VISIBLE',identidad_evaluada=False)
    if sample is not None:d.update(face_sample=sample,track_generacion=i)
    if known:d.update(reconocido=True,id_empleado=i,codigo_empleado=f'EMP-{i:03}',
                      nombre=f'Persona {i}',empleado_activo=True,similitud_facial=.8)
    if unknown:d.update(estado_identidad='NO_RECONOCIDO',identidad_evaluada=True)
    return d


def esperar(fn,timeout=4):
    fin=time.monotonic()+timeout
    while time.monotonic()<fin:
        if fn():return
        time.sleep(.01)
    raise AssertionError('El worker no alcanzó el estado esperado.')


class Presencia(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.cfg=deepcopy(DEFAULTS['vigilancia']);self.events=[]
        self.frame=np.zeros((120,180,3),dtype=np.uint8)
        self.r=p.RegistroPresencia(self.cfg,lambda *a,**k:self.events.append((a,k)),self.tmp.name)
        guard=patch('requests.sessions.Session.request',side_effect=AssertionError('HTTP no autorizado en pruebas'));guard.start();self.addCleanup(guard.stop)
        guard=patch('core.database.conectar',side_effect=AssertionError('SQL no autorizado en pruebas'));guard.start();self.addCleanup(guard.stop)

    def confirmar(self,ds):
        for n in range(3):self.r.actualizar(ds,n*.1,self.frame)

    def types(self):return [a[0] for a,k in self.events]

    def test_una_persona_confirmada_no_por_un_frame(self):
        self.r.actualizar([deteccion()],0);self.assertEqual(self.r.conteos()['personas'],0)
        self.confirmar([deteccion()]);self.assertEqual(self.r.conteos()['personas'],1)
        self.assertEqual(self.types().count('PERSONA_ENTRO_HABITACION'),1)

    def test_varios_tracks_sin_duplicar(self):
        self.confirmar([deteccion(1),deteccion(2),deteccion(2),deteccion(3)])
        self.assertEqual(self.r.conteos()['personas'],3)

    def test_rostro_no_visible_no_es_desconocido(self):
        self.confirmar([deteccion()]);self.assertEqual(self.r.conteos()['desconocidos'],0)
        self.assertEqual(self.r.presentes()[0]['estado_identidad'],'SIN EVIDENCIA FACIAL')

    def test_empleado_identificado_por_pipeline_no_cnn(self):
        self.confirmar([deteccion(sample=1,known=True)])
        self.assertEqual(self.r.conteos()['identificados'],1)
        self.assertEqual(self.types().count('EMPLEADO_ENTRO_HABITACION'),1)
        self.assertFalse(next(k['data']['notificar'] for a,k in self.events if a[0]=='EMPLEADO_ENTRO_HABITACION'))

    def test_desconocido_requiere_evaluaciones_nuevas_y_snapshot(self):
        self.confirmar([deteccion(sample=1,unknown=True)])
        for n in range(5):self.r.actualizar([deteccion(sample=1,unknown=True)],.4+n*.1,self.frame)
        self.assertEqual(self.r.conteos()['desconocidos'],0)
        self.r.actualizar([deteccion(sample=2,unknown=True)],1,self.frame)
        self.r.actualizar([deteccion(sample=3,unknown=True)],1.1,self.frame)
        self.assertEqual(self.r.conteos()['desconocidos'],1)
        e=next(k for a,k in self.events if a[0]=='PERSONA_DESCONOCIDA_HABITACION')
        self.assertTrue(Path(e['image']).is_file());self.assertTrue(e['data']['notificar'])
        self.r.actualizar([deteccion(sample=4,unknown=True)],1.2,self.frame)
        self.assertEqual(self.types().count('PERSONA_DESCONOCIDA_HABITACION'),1)

    def test_rostro_no_visible_interrumpe_evidencia_desconocida(self):
        for n in range(2):self.r.actualizar([deteccion(sample=n,unknown=True)],n*.1)
        self.r.actualizar([deteccion(sample=3)],.3)
        self.r.actualizar([deteccion(sample=4,unknown=True)],.4)
        self.assertEqual(self.r.conteos()['desconocidos'],0)

    def test_track_perdido_brevemente_recupera_sin_nueva_entrada(self):
        self.confirmar([deteccion(sample=1,known=True)])
        self.r.actualizar([],1);self.r.actualizar([deteccion()],2)
        self.assertEqual(self.r.conteos()['identificados'],1)
        self.assertNotIn('EMPLEADO_SALIO_HABITACION',self.types())
        self.assertEqual(self.types().count('EMPLEADO_ENTRO_HABITACION'),1)

    def test_timeout_salida_con_duracion(self):
        self.confirmar([deteccion(sample=1,known=True)]);self.r.actualizar([],4)
        self.assertEqual(self.r.conteos()['personas'],0)
        self.assertEqual(self.types().count('EMPLEADO_SALIO_HABITACION'),1)
        e=next(k['data'] for a,k in self.events if a[0]=='EMPLEADO_SALIO_HABITACION')
        self.assertGreaterEqual(e['duracion'],0)

    def test_reaparicion_tras_timeout_no_hereda_identidad(self):
        self.confirmar([deteccion(sample=1,known=True)])
        for n in range(3):self.r.actualizar([deteccion()],5+n*.1)
        self.assertEqual(self.r.conteos()['identificados'],0)
        self.assertEqual(self.types().count('PERSONA_ENTRO_HABITACION')+self.types().count('EMPLEADO_ENTRO_HABITACION'),2)

    def test_identidad_estable_sin_rostro_y_contradiccion_de_un_frame(self):
        self.confirmar([deteccion(sample=1,known=True)])
        self.r.actualizar([deteccion(sample=2)],.4)
        d=deteccion(sample=3,known=True);d['id_empleado']=99;d['nombre']='Otra persona'
        self.r.actualizar([d],.5)
        self.assertEqual(self.r.presentes()[0]['id_empleado'],1)

    def test_ocupacion_solo_cambios_y_no_notifica(self):
        self.confirmar([deteccion()]);before=self.types().count('OCUPACION_CAMBIO')
        self.r.actualizar([deteccion()],.5)
        self.assertEqual(self.types().count('OCUPACION_CAMBIO'),before)
        self.assertFalse(next(k['data']['notificar'] for a,k in self.events if a[0]=='OCUPACION_CAMBIO'))

    def test_caida_no_inventa_salida(self):
        self.confirmar([deteccion()]);self.r.invalidar()
        self.assertNotIn('PERSONA_SALIO_HABITACION',self.types())

    def test_historial_persistido(self):
        self.confirmar([deteccion()]);path=Path(self.tmp.name)/'historial.jsonl'
        self.assertIn('PERSONA_ENTRO_HABITACION',path.read_text(encoding='utf-8'))

    def test_fuente_compartida_rechazada(self):
        from surveillance.fuentes_camara import reservar,liberar
        a,b=object(),object();reservar('fuente-local',a)
        try:
            with self.assertRaises(ValueError):reservar('fuente-local',b)
            liberar('fuente-local',b)
            with self.assertRaises(ValueError):reservar('fuente-local',b)
        finally:liberar('fuente-local',a)

    def test_validaciones(self):
        for key,value in (('camera_source_employees',-1),('presence_face_interval',0),('presence_exit_timeout',float('nan')),
                          ('presence_image_size',481),('presence_notify_unknown',1)):
            with self.subTest(key=key):
                c=dict(self.cfg,**{key:value})
                with self.assertRaises(ValueError):p.validar_configuracion_presencia(c)

    def test_end_to_end_event_bus_snapshot_telegram_jarvis(self):
        from core.event_bus import EventBus
        from core.system_event import SystemEvent
        from core.event_subscribers import consumir_telegram,PRESENCIA_NOTIFICABLES
        bus=EventBus();self.addCleanup(bus.close)
        bus.subscribe(PRESENCIA_NOTIFICABLES,consumir_telegram,name='telegram-presencia',asynchronous=False)
        def publicar(*a,**kw):
            # Mismos eventos inmutables que el publicador central.
            if len(a)==4:a=(*a,a[3])
            bus.publish(SystemEvent(*a,**kw))
        self.r.publicar=publicar
        state=p.PresenciaEmpleados();state.estado='ONLINE';state.registro=self.r
        with patch('integrations.telegram.telegram_service.servicio_telegram.notificar',return_value=True) as telegram,patch.object(p,'servicio_presencia',state):
            for n in range(1,4):
                self.r.actualizar([deteccion(1,n,known=True),deteccion(2,n,known=True),deteccion(3,n,unknown=True)],n*.1,self.frame)
            self.assertEqual(self.r.conteos()['personas'],3)
            self.assertEqual(self.r.conteos()['identificados'],2);self.assertEqual(self.r.conteos()['desconocidos'],1)
            telegram.assert_called_once();self.assertTrue(Path(telegram.call_args.kwargs['imagen']).is_file())
            self.assertIn('Presencia',telegram.call_args.args[2])
            from jarvis.jarvis import procesar
            r=procesar('¿Cuántas personas hay en la habitación?',session_id='presencia-e2e')
            self.assertIn('3 personas',r.respuesta);self.assertIn('2 empleados',r.respuesta);self.assertIn('1 desconocidos',r.respuesta)
            r=procesar('¿Quiénes están?',session_id='presencia-e2e');self.assertIn('Persona 1',r.respuesta)
            from integrations.telegram.telegram_bot_service import TelegramBotService
            bot=TelegramBotService()
            with patch('integrations.telegram.telegram_bot_service._credenciales',return_value=('sin-token-real','1234')),patch.object(bot,'_responder') as responder:
                bot.procesar_actualizacion({'message':{'chat':{'id':1234},'text':'/presentes'}})
                self.assertIn('3 personas',responder.call_args.args[1]);self.assertFalse(bot.sessions['1234']['modo_jarvis'])

    def test_camara_desconectada_no_informa_cero(self):
        state=p.PresenciaEmpleados()
        with patch.object(p,'servicio_presencia',state):
            self.assertIsNone(p.obtener_conteo_actual()['personas'])
            self.assertIn('No puedo confirmar',p.resumen_presencia())

    def test_telegram_ignora_eventos_desactivados(self):
        from core.event_subscribers import consumir_telegram
        from core.system_event import SystemEvent
        e=SystemEvent('EMPLEADO_ENTRO_HABITACION','VIGILANCIA','presencia','Entrada','Presencia confirmada',data={'notificar':False})
        with patch('integrations.telegram.telegram_service.servicio_telegram.notificar') as send:
            consumir_telegram(e);send.assert_not_called()

    def test_consulta_de_producto_dentro_no_se_convierte_en_presencia(self):
        from jarvis.tools.presencia import responder
        self.assertIsNone(responder('que productos hay dentro del estante e03',{}))

    def test_reconexion_reutiliza_un_worker_facial_y_no_inventa_salidas(self):
        attempts=[];face=Mock();face.actualizar.side_effect=lambda f,d,t:d
        class Capture:
            def __init__(self,source,resolution):
                attempts.append(self);self.error=RuntimeError('Sin conexión') if len(attempts)==1 else None;self.num=0
            def iniciar(self):return self
            def leer(inner):inner.num+=1;return inner.num,self.frame
            def cerrar(self):pass
        model=Mock();model.track.return_value=[Mock(boxes=None)];model.predictor=Mock(trackers=[Mock()])
        factory=Mock(return_value=face);s=p.PresenciaEmpleados()
        with patch.object(p,'RegistroPresencia',return_value=self.r):
            try:
                s.iniciar(self.cfg,detector_factory=lambda c:model,captura_factory=Capture,facial_factory=factory)
                esperar(lambda:s.obtener_estado()['estado']=='OFFLINE')
                esperar(lambda:s.obtener_estado()['disponible'],timeout=6)
                self.assertEqual(len(attempts),2);factory.assert_called_once();face.reiniciar_tracks.assert_called_once()
                model.predictor.trackers[0].reset.assert_called_once()
                self.assertNotIn('PERSONA_SALIO_HABITACION',self.types())
            finally:
                s.parar()
                if s.hilo:s.hilo.join(4)

    def test_sface_revalida_sin_ejecutar_en_cada_frame(self):
        from surveillance.identidad_vigilancia import IdentidadPorTrack
        base=Mock();base.galeria.vectores=[1];base.politica={};base.cfg={}
        result=dict(reconocido=True,estado_identidad='EMPLEADO_RECONOCIDO',id_empleado=1,empleado_activo=True)
        with patch('surveillance.identidad_vigilancia.reconocer_empleado_en_frame',return_value=result) as reconocer,patch('surveillance.identidad_vigilancia.SeguimientoFacial'):
            motor=IdentidadPorTrack(ttl=2,pipeline_factory=lambda:base,cache_factory=lambda:{'s':dict(result,subject='s')},intervalo=.02,revalidar=.15)
            try:
                esperar(lambda:motor.disponible is True)
                d=dict(deteccion(),bbox=[0,0,90,100]);motor.actualizar(self.frame,[d],time.monotonic())
                esperar(lambda:reconocer.call_count==1)
                for _ in range(5):motor.actualizar(self.frame,[dict(d)],time.monotonic())
                self.assertEqual(reconocer.call_count,1)
                time.sleep(.18);motor.actualizar(self.frame,[dict(d)],time.monotonic())
                esperar(lambda:reconocer.call_count==2)
            finally:motor.cerrar()

    def test_dos_camaras_independientes_y_caida_segunda(self):
        from surveillance.vigilancia_yolo import Vigilancia
        captures={}
        class Capture:
            def __init__(self,source,resolution):self.source=source;self.error=None;self.num=0;captures[source]=self
            def iniciar(self):return self
            def leer(inner):inner.num+=1;time.sleep(.01);return inner.num,self.frame
            def cerrar(self):pass
        def detector(_):
            m=Mock();m.track.return_value=[Mock(boxes=None)];return m
        def facial(**kwargs):
            m=Mock();m.actualizar.side_effect=lambda f,d,t:d;return m
        a=Vigilancia();b=p.PresenciaEmpleados()
        c=dict(self.cfg,intrusion_enabled=True,zone_polygon=[[0,0],[1,0],[1,1],[0,1]])
        # La evidencia y SFace son sustituidos; la captura de ambas cámaras es independiente.
        with patch('surveillance.vigilancia_yolo.EvidenciaIntrusion'),patch('surveillance.identidad_vigilancia.IdentidadPorTrack',side_effect=facial),patch.object(p,'RegistroPresencia',return_value=self.r):
            try:
                a.iniciar(c,detector_factory=detector,captura_factory=Capture)
                b.iniciar(c,detector_factory=detector,captura_factory=Capture,facial_factory=facial)
                esperar(lambda:a.obtener_estado()['frame'] is not None and b.obtener_estado()['disponible'])
                self.assertIsNot(captures[0],captures[1]);self.assertIsNot(a.hilo,b.hilo)
                captures[1].error=RuntimeError('Desconectada')
                esperar(lambda:b.obtener_estado()['estado']=='OFFLINE')
                self.assertTrue(a.obtener_estado()['activo']);self.assertEqual(a.obtener_estado()['estado'],'Activo')
                self.assertGreater(a.obtener_estado()['fps'],0)
                from core.system_state import state_manager
                self.assertEqual(state_manager.get('CAMARA_1').status,'ONLINE')
                self.assertNotEqual(state_manager.get('CAMARA_2').status,'ONLINE')
            finally:
                a.parar();b.parar()
                if a.hilo:a.hilo.join(4)
                if b.hilo:b.hilo.join(4)
        self.assertFalse(a.hilo.is_alive());self.assertFalse(b.hilo.is_alive())


if __name__=='__main__':unittest.main()
