"""Formato y evidencia reales por contrato; sin cámaras físicas ni envíos de red."""
from pathlib import Path
from copy import deepcopy
import tempfile
import unittest
from unittest.mock import Mock,patch
import numpy as np
import cv2
from integrations.telegram import telegram_service as t
from core.config_manager import DEFAULTS
from surveillance.vigilancia_yolo import EvidenciaIntrusion


class EventosVisuales(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        self.inicio=patch.object(t.servicio_telegram,'iniciar');self.inicio.start()
    def tearDown(self):self.inicio.stop();self.tmp.cleanup()
    def evento(self):
        return dict(id_evento='a'*32,fecha_hora='2026-10-17T12:34:56-06:00',camara='Cámara del taller',zona='Zona A',
            tipo_evento='INTRUSIÓN',track_id=7,bbox=[120,120,200,230],confianza=.92,estado_identidad='NO_RECONOCIDO',
            identidad_evaluada=True,similitud_facial=.22)
    def test_formato_completo_sin_identidades_inventadas(self):
        mensaje=t.mensaje_evento(self.evento())
        for texto in ('[INTRUSIÓN]','Categoría: Vigilancia','Subtipo:','Fecha: 2026-10-17','Hora: 12:34:56',
                      'Cámara: Cámara del taller','Zona: Zona A','Módulo: Vigilancia','Nivel: Alta','Identidad: DESCONOCIDO','Confianza YOLO: 0.92','Descripción:'):
            self.assertIn(texto,mensaje)
        self.assertNotIn('Empleado:',mensaje)
    def test_snapshot_conserva_frame_completo_y_no_muta_original(self):
        frame=np.full((300,400,3),(80,130,170),np.uint8);original=frame.copy()
        ruta=t.generar_snapshot_evento(frame,self.evento(),self.base/'captura.jpg')
        salida=cv2.imread(ruta)
        self.assertEqual(salida.shape,original.shape);self.assertTrue(np.array_equal(frame,original))
        self.assertLess(np.abs(salida[260:290,250:380].astype(float)-original[260:290,250:380]).mean(),3)
        self.assertGreater(np.abs(salida[:80].astype(float)-original[:80]).mean(),10)
    def test_no_generar_imagen_si_no_hay_frame(self):
        with self.assertRaises(ValueError):t.generar_snapshot_evento(None,self.evento(),self.base/'captura.jpg')
        self.assertFalse((self.base/'captura.jpg').exists())
    def test_orden_foto_recorte_video(self):
        foto=self.base/'captura.jpg';foto.touch();recorte=self.base/'persona.jpg';recorte.touch();clip=self.base/'clip.mp4';clip.touch()
        datos=dict(mensaje=t.mensaje_evento(self.evento()),imagen=str(foto),video=str(clip),datos={'recorte':str(recorte)})
        with patch.object(t,'_enviar',return_value={'enviado':True,'detalle':'Confirmado'}) as enviar:
            t._entregar_contenido(datos,lambda d:None)
        self.assertEqual([c.args[0] for c in enviar.call_args_list],['sendPhoto','sendPhoto','sendVideo'])
        self.assertTrue(enviar.call_args_list[0].args[1]['caption'].startswith('[INTRUSIÓN]'))
    def test_caption_largo_conserva_descripcion_en_texto_adjunto(self):
        foto=self.base/'captura.jpg';foto.touch()
        mensaje=t.formatear_evento(dict(self.evento(),categoria='Vigilancia',descripcion='Detalle registrado. '*150))
        with patch.object(t,'_enviar',return_value={'enviado':True,'detalle':'Confirmado'}) as enviar:
            t._entregar_contenido(dict(mensaje=mensaje,imagen=str(foto)),lambda d:None)
        self.assertLessEqual(len(enviar.call_args_list[0].args[1]['caption']),1024)
        textos=''.join(c.args[1]['text'] for c in enviar.call_args_list if c.args[0]=='sendMessage')
        self.assertEqual(textos,mensaje)
    def test_foto_falla_hay_texto_y_clip_no_repite_foto(self):
        foto=self.base/'captura.jpg';foto.touch();clip=self.base/'clip.mp4';clip.touch()
        datos=dict(mensaje='[INTRUSIÓN]',imagen=str(foto),video=str(clip))
        respuestas=[dict(enviado=False,reintentable=False,detalle='HTTP 400'),dict(enviado=True,detalle='Texto confirmado'),
            dict(enviado=False,reintentable=True,detalle='HTTP 503'),dict(enviado=True,detalle='Clip confirmado')]
        with patch.object(t,'_enviar',side_effect=respuestas) as enviar:
            t._entregar_contenido(datos,lambda d:None);t._entregar_contenido(datos,lambda d:None)
        self.assertEqual([c.args[0] for c in enviar.call_args_list],['sendPhoto','sendMessage','sendVideo','sendVideo'])
    def test_empleado_confirmado_no_se_notifica_cincuenta_veces(self):
        cfg=deepcopy(DEFAULTS['vigilancia']);cfg.update(clip_before_seconds=0,clip_after_seconds=0)
        cfg['zone_polygon']=[[0,0],[1,0],[1,1]]
        empleado=dict(track_id=8,track_generacion=1,bbox=[0,0,80,90],confianza=.94,estado_identidad='EMPLEADO_RECONOCIDO',
            identidad_evaluada=True,reconocido=True,id_empleado=2,nombre='Empleado registrado',codigo_empleado='EMP-002',similitud_facial=.83)
        sql=Mock();notificar=Mock(return_value=dict(enviado=True,detalle='Foto confirmada'))
        with patch('core.config_manager.obtener',return_value=True):
            evidencia=EvidenciaIntrusion(cfg,self.base,registrar_sql=sql,notificar=notificar)
            try:
                frame=np.full((120,140,3),100,np.uint8)
                for _ in range(50):evidencia.registrar_identidades([empleado],frame,1.)
            finally:
                evidencia.cerrar()
                for hilo in evidencia.hilos:hilo.join(3)
        self.assertEqual(len(evidencia.recientes),1);self.assertEqual(notificar.call_count,1)
        evento=evidencia.recientes[0]
        self.assertEqual(evento['tipo_evento'],'EMPLEADO RECONOCIDO');self.assertTrue(Path(evento['captura']).is_file())
        self.assertIn('Empleado: Empleado registrado',t.mensaje_evento(evento))
        sql.assert_not_called()  # El registro es central; no se fabrica una alerta de intrusión.
    def test_verificando_no_es_desconocido(self):
        cfg=deepcopy(DEFAULTS['vigilancia']);cfg.update(clip_before_seconds=0,clip_after_seconds=0)
        evidencia=EvidenciaIntrusion(cfg,self.base,registrar_sql=Mock(),notificar=Mock())
        try:
            self.assertEqual(evidencia.registrar_identidades([dict(track_id=1,estado_identidad='VERIFICANDO_IDENTIDAD',identidad_evaluada=True)],np.zeros((80,80,3),np.uint8),1),[])
        finally:
            evidencia.cerrar()
            for hilo in evidencia.hilos:hilo.join(2)
    def test_alerta_y_anomalia_tienen_mismo_encabezado_y_estadisticas_presentes(self):
        a=dict(tipo='Stock bajo',nivel='Alta',producto='Filtro',codigo='FIL-001',stock_actual=4,stock_minimo=5,
            mensaje='Stock inferior al mínimo.',fecha_creacion='2026-10-17T16:10:30',atendida=False)
        self.assertIn('Código producto: FIL-001',t.formatear_alerta(a))
        an=dict(producto='Tornillo',codigo='TOR-001',nivel='CRÍTICA',cantidad=100,score=4,fecha='2026-10-17T16:12:50',
            motivo='Salida superior al patrón.',referencia_historica='Promedio: 12.42; desviación: 7.97; muestras: 10')
        mensaje=t.formatear_anomalia(an)
        self.assertIn('[ANOMALÍA]',mensaje);self.assertIn('Promedio previo: 12.42',mensaje);self.assertIn('Desviación: 7.97',mensaje)
        self.assertNotIn('fraude',mensaje.lower())

    def test_similitud_del_escaner_no_se_presenta_como_confianza_yolo(self):
        servicio=t.ServicioTelegram()
        with patch.object(t,'servicio_telegram',servicio):
            t.notificar_rostro_desconocido(dict(estado='DESCONOCIDO',calidad_estado='CALIDAD_OK',track_id=1,confianza=.25,similitud=.25),np.zeros((100,100,3),np.uint8))
        mensaje=servicio.cola.get_nowait()['mensaje']
        self.assertIn('Confianza facial: 0.25',mensaje);self.assertNotIn('Confianza YOLO',mensaje)
        self.assertIn('Módulo: Empleados',mensaje)

    def test_descripcion_larga_sin_camara_no_se_trunca(self):
        mensaje=t.formatear_evento(dict(tipo_evento='ANOMALÍA',categoria='Inventario',descripcion='Detalle de hallazgo. '*400))
        with patch.object(t,'_enviar',return_value=dict(enviado=True,detalle='Confirmado')) as enviar:
            t._entregar_contenido(dict(mensaje=mensaje),lambda d:None)
        self.assertEqual(''.join(c.args[1]['text'] for c in enviar.call_args_list),mensaje)
        self.assertTrue(all(len(c.args[1]['text'])<=4096 for c in enviar.call_args_list))


if __name__=='__main__':unittest.main()
