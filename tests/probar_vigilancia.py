"""Geometría, transiciones, evidencia y Telegram sin cámaras ni envíos reales."""
import contextlib
import io
import json
import tempfile
import time
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, Mock

import cv2
import numpy as np
from core.config_manager import DEFAULTS, validar
from surveillance.vigilancia_yolo import ControlIntrusion, EvidenciaIntrusion, validar_poligono, validar_configuracion, Vigilancia
from integrations.telegram import telegram_service as telegram
from inventory import alertas

POLIGONO=[[.5,.1],[.95,.1],[.95,.95],[.5,.95]]


def setUpModule():
    global _inicio_telegram
    _inicio_telegram=patch('integrations.telegram.telegram_service.servicio_telegram.iniciar')
    _inicio_telegram.start()


def tearDownModule():
    _inicio_telegram.stop()


def persona(dentro, track=7):
    x=60 if dentro else 10
    return dict(track_id=track,bbox=[x,10,x+20,80],confianza=.93)


class Zona(unittest.TestCase):
    def setUp(self):self.c=ControlIntrusion(POLIGONO,2,30,2)
    def mover(self,dentro,t,track=7):return self.c.actualizar([persona(dentro,track)],(100,100,3),t)
    def test_presencia_inicial_dentro_no_inventa_entrada(self):
        self.assertEqual([self.mover(True,t/10) for t in range(10)],[[]]*10)
        self.assertEqual(self.c.tracks[7]['estado'],'DENTRO')
    def test_entrada_confirmada_y_sin_spam(self):
        self.mover(False,0);self.mover(False,.1)
        self.assertFalse(self.mover(True,.2));self.assertEqual(self.c.tracks[7]['estado'],'ENTRANDO')
        self.assertEqual(len(self.mover(True,.3)),1)
        for t in range(4,20):self.assertFalse(self.mover(True,t/10))
        self.mover(False,2);self.assertEqual(self.c.tracks[7]['estado'],'SALIENDO')
        self.mover(False,2.1);self.mover(True,2.2);self.assertFalse(self.mover(True,2.3))
    def test_dos_tracks_independientes(self):
        for t in (0,.1):self.c.actualizar([persona(False,1),persona(False,2)],(100,100,3),t)
        self.c.actualizar([persona(True,1),persona(True,2)],(100,100,3),.2)
        self.assertEqual(len(self.c.actualizar([persona(True,1),persona(True,2)],(100,100,3),.3)),2)
    def test_reentrada_despues_de_cooldown(self):
        for t,d in [(0,False),(.1,False),(.2,True),(.3,True),(31,False),(31.1,False),(31.2,True)]:self.mover(d,t)
        self.assertEqual(len(self.mover(True,31.3)),1)
    def test_track_perdido_no_reutiliza_evidencia_antigua(self):
        self.mover(False,0);self.mover(False,.1);self.mover(True,.2)
        self.assertFalse(self.mover(True,5));self.assertFalse(self.mover(True,5.1))
    def test_punto_inferior_y_no_solapamiento_de_caja(self):
        d=dict(track_id=1,bbox=[10,10,90,99],confianza=.8)
        self.c.actualizar([d],(100,100,3),0)
        self.assertFalse(self.c.tracks[1]['candidato'])
    def test_poligonos_invalidos(self):
        for puntos in [[],[[0,0],[1,1]],[[0,0],[1,1],[0,1],[1,0]],[[0,0],[1,0],[1,float('nan')]],[[0,0],[1,0],[2,1]],[[0,0],[1,0],[1,0]]]:
            with self.subTest(puntos=puntos),self.assertRaises(ValueError):validar_poligono(puntos)
    def test_configuracion_central(self):
        self.assertEqual(validar(deepcopy(DEFAULTS))['vigilancia']['zone_polygon'],[])
        for k,v in [('confidence_threshold',float('nan')),('cooldown_seconds',0),('clip_after_seconds',100),('confirm_frames',True),('camera_source','rtsp://persona:clave@camara/live'),('image_size',641)]:
            c=deepcopy(DEFAULTS['vigilancia']);c[k]=v
            with self.subTest(k=k),self.assertRaises(ValueError):validar_configuracion(c)


class Evidencia(unittest.TestCase):
    def test_buffer_previo_limitado_por_tiempo_y_no_solo_por_fps(self):
        cfg=deepcopy(DEFAULTS['vigilancia']);cfg['clip_before_seconds']=1
        with tempfile.TemporaryDirectory() as carpeta:
            e=EvidenciaIntrusion(cfg,carpeta)
            for t in (0,.5,1,1.5,2,2.5):e.frame(np.zeros((20,20,3),np.uint8),t)
            self.assertTrue(all(t>=1.5 for t,f in e.buffer))
            e.cerrar()
            for h in e.hilos:h.join(2)
    def test_bloqueo_compartido_impide_abrir_camara_dos_veces(self):
        from ai.facial.reconocimiento_cnn import _bloqueo_camara
        v=Vigilancia();fabrica=Mock();cfg=deepcopy(DEFAULTS['vigilancia'])
        with _bloqueo_camara:
            v.iniciar(cfg,preview=True,captura_factory=fabrica);v.hilo.join(2)
        fabrica.assert_not_called();self.assertEqual(v.obtener_estado()['estado'],'Error')
    def test_worker_usa_solo_person_cpu_y_tracking_persistente(self):
        class Captura:
            error=None
            def iniciar(self):return self
            def leer(self):time.sleep(.015);return time.monotonic(),np.zeros((100,100,3),np.uint8)
            def cerrar(self):pass
        cfg=deepcopy(DEFAULTS['vigilancia']);cfg.update(intrusion_enabled=True,zone_polygon=POLIGONO)
        modelo=Mock();resultado=Mock();resultado.boxes.id=None;modelo.track.return_value=[resultado]
        with patch('surveillance.vigilancia_yolo.EvidenciaIntrusion') as evidencia:
            v=Vigilancia();v.iniciar(cfg,detector_factory=lambda c:modelo,captura_factory=lambda *a:Captura())
            limite=time.monotonic()+2
            while not modelo.track.called and time.monotonic()<limite:time.sleep(.01)
            v.parar();v.hilo.join(2)
            self.assertTrue(modelo.track.called)
            args=modelo.track.call_args.kwargs
            self.assertEqual(args['classes'],[0]);self.assertEqual(args['device'],'cpu');self.assertTrue(args['persist'])
            evidencia.return_value.registrar.assert_not_called();evidencia.return_value.cerrar.assert_called_once()
    @patch('core.config_manager.obtener',new=lambda s,k: False)
    def test_foto_recorte_clip_sql_pendiente_y_telegram_off(self):
        cfg=deepcopy(DEFAULTS['vigilancia']);cfg.update(zone_polygon=POLIGONO,clip_before_seconds=.5,clip_after_seconds=.5)
        with tempfile.TemporaryDirectory() as carpeta:
            sql=Mock(side_effect=RuntimeError('SQL no disponible'));notificar=Mock()
            e=EvidenciaIntrusion(cfg,carpeta,registrar_sql=sql,notificar=notificar)
            frame=np.full((100,100,3),100,np.uint8)
            for t in (0,.2,.4):e.frame(frame,t)
            evento=e.registrar(persona(True),frame,.4)
            for t in (.6,.8,1.):e.frame(frame,t)
            e.cerrar()
            for h in e.hilos:h.join(4)
            self.assertTrue(all(not h.is_alive() for h in e.hilos))
            registro=json.loads(Path(evento['metadata']).read_text(encoding='utf-8'))
            self.assertEqual(registro['sql_estado'],'pendiente');self.assertEqual(registro['telegram_foto'],'Telegram desactivado.')
            self.assertIsNone(registro['identidad']);self.assertFalse(registro['identidad_evaluada'])
            self.assertTrue(Path(registro['captura']).is_file());self.assertTrue(Path(registro['recorte']).is_file())
            self.assertTrue(Path(registro['clip']).is_file());self.assertGreater(registro['clip_despues_real'],0)
            self.assertEqual(cv2.imread(registro['recorte']).shape[:2],(70,20))
            self.assertEqual(sql.call_count,1);notificar.assert_not_called()
    @patch('core.config_manager.obtener',new=lambda s,k: True)
    def test_telegram_configurado_recibe_evento_sin_identidad_inventada(self):
        cfg=deepcopy(DEFAULTS['vigilancia']);cfg.update(telegram_enabled=True,clip_before_seconds=0,clip_after_seconds=0)
        with tempfile.TemporaryDirectory() as carpeta:
            enviar=Mock(return_value={'detalle':'Envío confirmado por Telegram.'})
            e=EvidenciaIntrusion(cfg,carpeta,registrar_sql=Mock(return_value={'id_alerta':77}),notificar=enviar)
            evento=e.registrar(persona(True),np.zeros((100,100,3),np.uint8),1)
            e.cerrar()
            for h in e.hilos:h.join(4)
            self.assertEqual(evento['id_alerta'],77);self.assertEqual(enviar.call_count,1)
            self.assertIsNone(enviar.call_args.args[0]['identidad'])
    def test_no_abrir_camara_deshabilitado_o_sin_zona(self):
        v=Vigilancia();c=deepcopy(DEFAULTS['vigilancia'])
        with self.assertRaises(ValueError):v.iniciar(c)
        c['intrusion_enabled']=True
        with self.assertRaises(ValueError):v.iniciar(c)


class Telegram(unittest.TestCase):
    def test_sin_credenciales_no_hay_red(self):
        with patch.object(telegram,'_credenciales',return_value=('','')),patch('requests.post') as post:
            self.assertFalse(telegram._enviar('sendMessage',{'text':'Prueba de conexión - Sistema Inteligente de Inventario'})['enviado']);post.assert_not_called()
    def test_mensaje_de_prueba_exacto_y_confirmacion(self):
        respuesta=Mock(status_code=200);respuesta.json.return_value={'ok':True}
        with patch.object(telegram,'_credenciales',return_value=('token_privado','chat')),patch('requests.post',return_value=respuesta) as post:
            self.assertTrue(telegram._enviar('sendMessage',{'text':'Prueba de conexión - Sistema Inteligente de Inventario'})['enviado'])
            self.assertEqual(post.call_args.kwargs['data']['text'],'Prueba de conexión - Sistema Inteligente de Inventario')
            self.assertEqual(post.call_args.kwargs['timeout'],(5,20))
    def test_error_no_expone_token(self):
        captura=io.StringIO()
        with contextlib.redirect_stdout(captura),contextlib.redirect_stderr(captura),patch.object(telegram,'_credenciales',return_value=('secreto_no_publicar','chat')),patch('requests.post',side_effect=RuntimeError('URL con secreto_no_publicar')):
            r=telegram._enviar('sendMessage',{'text':'Prueba de conexión - Sistema Inteligente de Inventario'})
        self.assertNotIn('secreto_no_publicar',str(r)+captura.getvalue());self.assertFalse(r['enviado'])
    def test_http_403_no_se_presenta_como_exito(self):
        with patch.object(telegram,'_credenciales',return_value=('x','y')),patch('requests.post',return_value=Mock(status_code=403)):
            self.assertIn('403',telegram._enviar('sendMessage',{'text':'Prueba de conexión - Sistema Inteligente de Inventario'})['detalle'])


class RegistroSQL(unittest.TestCase):
    def test_idempotencia_por_evento_sin_escribir_sql_real(self):
        class Cursor:
            def __init__(self):self.fila=None;self.id=None;self.inserts=0
            def execute(self,sql,*args):
                if 'sp_getapplock' in sql:self.fila=(0,)
                elif 'LEFT(mensaje' in sql:self.fila=(self.id,) if self.id else None
                elif 'INSERT dbo.alertas' in sql:self.inserts+=1;self.id=91;self.fila=(91,)
                return self
            def fetchone(self):return self.fila
        q=Cursor();c=Mock();c.cursor.return_value=q
        evento=dict(id_evento='a'*32,fecha_hora=datetime.now(timezone.utc).isoformat(),camara='Principal',zona='Almacén',track_id=7,confianza=.9)
        with patch.object(alertas,'conectar',return_value=c),patch.object(alertas,'obtener_tipo_alerta',return_value=12):
            self.assertTrue(alertas.registrar_alerta_intrusion(evento)['creada'])
            self.assertFalse(alertas.registrar_alerta_intrusion(evento)['creada'])
        self.assertEqual(q.inserts,1);self.assertEqual(c.commit.call_count,2)


if __name__=='__main__':unittest.main()
