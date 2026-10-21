"""Integración SFace por track, enriquecimiento y mensajes sin cámaras ni envíos."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from copy import deepcopy
from unittest.mock import Mock, patch

import numpy as np
from core.config_manager import DEFAULTS
from surveillance.identidad_vigilancia import reconocer_empleado_en_frame, IdentidadPorTrack, texto_identidad
from integrations.telegram.telegram_service import mensaje_evento
from surveillance.vigilancia_yolo import EvidenciaIntrusion
from inventory import alertas


def setUpModule():
    global _inicio_telegram
    _inicio_telegram=patch('integrations.telegram.telegram_service.servicio_telegram.iniciar')
    _inicio_telegram.start()


def tearDownModule():
    _inicio_telegram.stop()


EMPLEADO=dict(id_empleado=101,codigo_empleado='EMP-101',nombre='Ana Ruiz',cargo='Mecánica',empleado_activo=True)


def conocido():
    return dict(estado='RECONOCIDO',reconocido=True,etiqueta='subject101',id_empleado=101,
                similitud=.78,caja=(5,6,40,40),calidad_estado='CALIDAD_OK')


def esperar(condicion):
    fin=time.monotonic()+3
    while not condicion() and time.monotonic()<fin:time.sleep(.01)
    assert condicion()


class Adaptacion(unittest.TestCase):
    def setUp(self):self.frame=np.zeros((200,300,3),np.uint8)
    def ejecutar(self,resultados,cache=None,roi=(40,20,140,170)):
        p=Mock();p.procesar.return_value=resultados
        r=reconocer_empleado_en_frame(self.frame,roi,pipeline=p,empleados=cache or {'subject101':EMPLEADO})
        return r,p
    def test_roi_bgr_y_coordenadas_originales(self):
        self.frame[20:170,40:140,0]=230
        r,p=self.ejecutar([conocido()])
        roi=p.procesar.call_args.args[0]
        self.assertEqual(roi.shape,(150,100,3));self.assertEqual(roi[0,0].tolist(),[230,0,0])
        self.assertEqual(r['caja_rostro'],[45,26,40,40]);self.assertEqual(r['nombre'],'Ana Ruiz')
    def test_sin_rostro_no_es_desconocido(self):
        r,_=self.ejecutar([])
        self.assertEqual(r['estado_identidad'],'ROSTRO_NO_VISIBLE');self.assertFalse(r['identidad_evaluada'])
    def test_multiples_rostros_no_asignan_identidad(self):
        r,_=self.ejecutar([conocido(),conocido()]);self.assertFalse(r['reconocido'])
    def test_desconocido_valido(self):
        r,_=self.ejecutar([dict(estado='DESCONOCIDO',reconocido=False,similitud=.2,calidad_estado='CALIDAD_OK')])
        self.assertEqual(r['estado_identidad'],'NO_RECONOCIDO');self.assertTrue(r['identidad_evaluada'])
    def test_baja_calidad_no_es_desconocido(self):
        r,_=self.ejecutar([dict(estado='VERIFICANDO',calidad_estado='IMAGEN_BORROSA')])
        self.assertEqual(r['estado_identidad'],'ROSTRO_NO_VISIBLE')
    def test_inactivo_se_distingue_sin_cambiar_cache_original(self):
        e=dict(EMPLEADO,empleado_activo=False)
        r,_=self.ejecutar([conocido()],{'subject101':e})
        self.assertEqual(r['estado_identidad'],'EMPLEADO_INACTIVO');self.assertFalse(e['empleado_activo'])
    def test_no_acepta_empleado_de_otra_relacion(self):
        r,_=self.ejecutar([dict(conocido(),id_empleado=900)])
        self.assertFalse(r['reconocido']);self.assertIsNone(r['subject'])
    def test_roi_fuera_de_imagen_no_infiere(self):
        r,p=self.ejecutar([],roi=(400,300,450,350));p.procesar.assert_not_called()


class Worker(unittest.TestCase):
    def setUp(self):
        self.base=Mock();self.base.galeria.vectores=np.ones((5,128));self.base.politica={'threshold':.7}
        self.base.cfg={'timeout_track_s':1}
        self.worker=IdentidadPorTrack(pipeline_factory=lambda:self.base,cache_factory=lambda:{'subject101':EMPLEADO})
        self.frame=np.zeros((200,300,3),np.uint8)
    def tearDown(self):self.worker.cerrar();self.worker.hilo.join(3)
    def deteccion(self,i=7):return dict(track_id=i,bbox=[10,10,110,190],confianza=.9)
    def test_confirmado_no_repite_inferencia_y_track_nuevo_no_hereda(self):
        resultado=dict(estado_identidad='EMPLEADO_RECONOCIDO',reconocido=True,subject='subject101',**EMPLEADO)
        with patch('surveillance.identidad_vigilancia.reconocer_empleado_en_frame',return_value=resultado) as reconocer:
            self.worker.actualizar(self.frame,[self.deteccion()],time.monotonic())
            esperar(lambda:self.worker.tracks[7]['resultado'].get('reconocido'))
            for _ in range(6):self.worker.actualizar(self.frame,[self.deteccion()],time.monotonic());time.sleep(.07)
            self.assertEqual(reconocer.call_count,1)
            d=self.deteccion(8);self.worker.actualizar(self.frame,[d],time.monotonic())
            self.assertNotEqual(d.get('subject'),'subject101')
    def test_worker_lento_no_bloquea_y_resultado_tardio_no_se_pega_a_track_nuevo(self):
        import threading
        entrada=threading.Event();soltar=threading.Event()
        llamadas=[]
        def lento(*a,**kw):
            llamadas.append(1)
            if len(llamadas)>1:return dict(reconocido=False,estado_identidad='ROSTRO_NO_VISIBLE')
            entrada.set();soltar.wait(2)
            return dict(reconocido=True,estado_identidad='EMPLEADO_RECONOCIDO',subject='subject101')
        with patch('surveillance.identidad_vigilancia.reconocer_empleado_en_frame',side_effect=lento):
            inicio=time.monotonic();self.worker.actualizar(self.frame,[self.deteccion()],inicio)
            self.assertLess(time.monotonic()-inicio,.1);self.assertTrue(entrada.wait(2))
            g=self.worker.tracks[7]['generacion']
            self.worker.actualizar(self.frame,[],inicio+3)
            self.worker.actualizar(self.frame,[self.deteccion()],inicio+3)
            self.assertNotEqual(g,self.worker.tracks[7]['generacion'])
            soltar.set();time.sleep(.1)
            self.assertFalse(self.worker.tracks[7]['resultado'].get('reconocido',False))
    def test_cruce_ambiguo_no_infiere(self):
        with patch('surveillance.identidad_vigilancia.reconocer_empleado_en_frame') as reconocer:
            ds=[self.deteccion(1),self.deteccion(2)]
            self.worker.actualizar(self.frame,ds,time.monotonic());time.sleep(.1)
            reconocer.assert_not_called()
            self.assertTrue(all(d['estado_identidad']=='IDENTIDAD_NO_DISPONIBLE' for d in ds))
    def test_consenso_separado_recursos_y_politica_compartidos(self):
        pipelines=[]
        def reconocer(*args,**kwargs):
            pipelines.append(kwargs['pipeline'])
            return dict(reconocido=False,estado_identidad='VERIFICANDO_IDENTIDAD')
        with patch('surveillance.identidad_vigilancia.reconocer_empleado_en_frame',side_effect=reconocer):
            ds=[self.deteccion(1),dict(track_id=2,bbox=[170,10,270,190],confianza=.9)]
            self.worker.actualizar(self.frame,ds,time.monotonic())
            esperar(lambda:len(pipelines)==2)
            self.assertIsNot(pipelines[0].tracker,pipelines[1].tracker)
            self.assertIs(pipelines[0].motor,pipelines[1].motor)
            self.assertIs(pipelines[0].galeria,pipelines[1].galeria)
            self.assertIs(pipelines[0].politica,self.base.politica)


class Enriquecimiento(unittest.TestCase):
    @patch('core.config_manager.obtener',new=lambda s,k: True)
    def test_mismo_evento_sql_se_actualiza_telegram_no_repite(self):
        cfg=deepcopy(DEFAULTS['vigilancia']);cfg.update(telegram_enabled=True,clip_before_seconds=0,clip_after_seconds=0)
        with tempfile.TemporaryDirectory() as carpeta:
            sql=Mock(return_value={'id_alerta':50});enviar=Mock(return_value={'enviado':True,'detalle':'Enviado'})
            e=EvidenciaIntrusion(cfg,carpeta,registrar_sql=sql,notificar=enviar)
            d=dict(track_id=7,track_generacion=1,bbox=[0,0,100,150],confianza=.9)
            evento=e.registrar(d,np.zeros((200,200,3),np.uint8),1)
            esperar(lambda:enviar.call_count==1)
            d.update(reconocido=True,estado_identidad='EMPLEADO_RECONOCIDO',subject='subject101',
                similitud_facial=.78,identidad_evaluada=True,**EMPLEADO)
            e.actualizar_identidades([d]);e.red.join();e.cerrar()
            for h in e.hilos:h.join(3)
            self.assertEqual(sql.call_count,2);self.assertEqual(enviar.call_count,1)
            self.assertEqual(len(e.recientes),1)
            datos=json.loads(Path(evento['metadata']).read_text(encoding='utf-8'))
            self.assertEqual(datos['id_empleado'],101);self.assertEqual(datos['id_alerta'],50)
    def test_generacion_distinta_no_enriquece_evento_anterior(self):
        cfg=deepcopy(DEFAULTS['vigilancia']);cfg.update(clip_before_seconds=0,clip_after_seconds=0)
        with tempfile.TemporaryDirectory() as carpeta:
            e=EvidenciaIntrusion(cfg,carpeta,registrar_sql=Mock(return_value={'id_alerta':1}))
            d=dict(track_id=7,track_generacion=1,bbox=[0,0,20,50],confianza=.9)
            evento=e.registrar(d,np.zeros((80,80,3),np.uint8),1)
            e.actualizar_identidades([dict(d,track_generacion=2,nombre='Otra persona',estado_identidad='EMPLEADO_RECONOCIDO')])
            e.cerrar()
            for h in e.hilos:h.join(3)
            self.assertIsNone(evento['nombre'])
    def test_telegram_distingue_tres_estados(self):
        base=dict(fecha_hora='2026-10-17T12:00:00-06:00',zona='Zona A',camara='Principal',track_id=7,confianza=.9,id_evento='a'*32)
        self.assertIn('Identidad: DESCONOCIDO',mensaje_evento(dict(base,estado_identidad='NO_RECONOCIDO')))
        self.assertIn('Identidad: No disponible',mensaje_evento(dict(base,estado_identidad='ROSTRO_NO_VISIBLE')))
        r=mensaje_evento(dict(base,estado_identidad='EMPLEADO_INACTIVO',similitud_facial=.78,**EMPLEADO))
        self.assertIn('Ana Ruiz',r);self.assertIn('Empleado inactivo',r)
    def test_actualizacion_sql_no_crea_otra_alerta_y_conserva_json(self):
        q=Mock();q.execute.return_value=q;q.fetchone.side_effect=[(0,),(51,)]
        c=Mock();c.cursor.return_value=q
        e=dict(id_evento='a'*32,fecha_hora='2026-10-17T12:00:00-06:00',camara='Principal',zona='Zona A',
               track_id=7,confianza=.9,estado_identidad='EMPLEADO_RECONOCIDO',similitud_facial=.78,subject='subject101',**EMPLEADO)
        with patch.object(alertas,'conectar',return_value=c):r=alertas.registrar_alerta_intrusion(e)
        self.assertFalse(r['creada']);self.assertEqual(r['id_alerta'],51)
        actualizacion=q.execute.call_args_list[-1].args
        self.assertIn('UPDATE dbo.alertas',actualizacion[0]);self.assertEqual(actualizacion[2],101)
        self.assertEqual(json.loads(actualizacion[3])['subject'],'subject101')


if __name__=='__main__':unittest.main()
