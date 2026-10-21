"""Verificaciones de captura manual sin cámara, SQL, entrenamiento ni biometría real."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch,Mock
import numpy as np

from ai.facial.sesiones_cnn import plan_subject,respaldar_imagenes
from ai.facial import captura_rostros as captura


class Sesiones(unittest.TestCase):
    def test_sesiones_guiadas_y_conserva_una_previa(self):
        for n,condicion in enumerate(('frontal','angulos','distancia','iluminacion')):
            p=plan_subject('subject19',{'subjects_activos_sql':['subject19'],'sesiones_por_subject':{'subject19':n}})
            self.assertEqual(p['numero'],n+1);self.assertEqual(p['condicion'],condicion)
        self.assertIsNone(plan_subject('s',{'subjects_activos_sql':['s'],'sesiones_por_subject':{'s':4}})['numero'])
        with self.assertRaises(ValueError):plan_subject('sin_vinculo',{'subjects_activos_sql':['s']})

    def test_respaldo_se_verifica_y_no_modifica_original(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'imagen.png';p.write_bytes(b'contenido conservado')
            r=respaldar_imagenes([p],Path(t)/'backups')
            self.assertTrue(r['verificado']);self.assertEqual(p.read_bytes(),b'contenido conservado')
            self.assertEqual(r,respaldar_imagenes([p],Path(t)/'backups'))

    def ejecutar(self,t,pedir=True,cancelar=False,calidad=True):
        from ai.facial import cnn_dataset
        presentador=Mock()
        presentador.plan_cnn=plan_subject('subject01',{'subjects_activos_sql':['subject01'],'sesiones_por_subject':{}})
        presentador.cierre_solicitado=False
        presentador.solicitud_foto=threading.Event();presentador.fin_sesion=threading.Event()
        reloj=iter(range(10000))
        imagenes=[np.random.default_rng(i).integers(20,230,(112,112,3),dtype=np.uint8) for i in range(6)]
        # Se ofrece dos veces el mismo contenido para verificar su rechazo.
        secuencia=[imagenes[0],imagenes[0],*imagenes[1:]];contador=[0]
        def leer():
            i=contador[0];contador[0]+=1
            if pedir:presentador.solicitud_foto.set()
            if i>=len(secuencia):
                presentador.cierre_solicitado=True
                return i,secuencia[-1]
            if cancelar and i==2:presentador.cierre_solicitado=True
            return i,secuencia[i]
        camara=Mock();camara.leer.side_effect=leer;camara.error=None;camara.iniciar.return_value=camara
        motor=Mock();motor.detectar.return_value=[np.zeros(15)];motor.alinear.side_effect=lambda frame,cara:frame
        datos={'X':[],'metadatos':[],'reporte_dataset':{'subjects_activos_sql':['subject01'],'sesiones_por_subject':{}}}
        with patch('ai.facial.rostros_empleados.obtener_cache_empleados_por_subject',return_value={'subject01':{'id_empleado':9,'empleado_activo':True}}),\
             patch.object(cnn_dataset,'MUESTRAS_CNN',Path(t)),patch.object(cnn_dataset,'cargar',return_value=datos),\
             patch('ai.facial.sesiones_cnn.respaldar_imagenes',return_value={'verificado':True}),\
             patch('ai.facial.pipeline_facial.MotorEmbeddings',return_value=motor),\
             patch('ai.facial.pipeline_facial.evaluar_calidad',return_value={'valida':calidad,'estado':'CALIDAD_OK' if calidad else 'IMAGEN_BORROSA'}),\
             patch.object(captura,'CamaraUltimoFrame',return_value=camara),\
             patch.object(captura.time,'monotonic',side_effect=lambda:next(reloj)),\
             patch.object(captura,'cerrar_camara'):
            return captura._capturar_sesion_cnn(9,presentador),presentador

    def test_captura_manual_excluye_duplicado_y_guarda_procedencia(self):
        with tempfile.TemporaryDirectory() as t:
            r,p=self.ejecutar(t)
            self.assertTrue(r['completado']);self.assertEqual(r['imagenes_guardadas'],5)
            carpeta=Path(t)/'subject01'/r['sesion']
            sesion=json.loads((carpeta/'sesion.json').read_text(encoding='utf-8'))
            filas=json.loads((carpeta/'registro.json').read_text(encoding='utf-8'))
            for k in ('subject','session_id','fecha_hora','grupo','condicion'):
                self.assertIn(k,sesion);self.assertTrue(all(k in f for f in filas))
            self.assertEqual(sesion['session_id'],carpeta.name)
            self.assertEqual(len(list(carpeta.glob('*.png'))),5)
            self.assertTrue(any('casi duplicada' in str(c) for c in p.publicar_info.call_args_list))

    def test_sin_pulsar_boton_no_guarda_frames(self):
        with tempfile.TemporaryDirectory() as t:
            r,p=self.ejecutar(t,pedir=False)
            self.assertFalse(r['completado']);self.assertEqual(r['imagenes_guardadas'],0)
            self.assertFalse(list(Path(t).rglob('*.png')))

    def test_baja_calidad_no_guarda_imagen(self):
        with tempfile.TemporaryDirectory() as t:
            r,p=self.ejecutar(t,calidad=False)
            self.assertFalse(r['completado']);self.assertEqual(r['imagenes_guardadas'],0)
            self.assertTrue(any('baja calidad' in str(c) for c in p.publicar_info.call_args_list))

    def test_cancelacion_conserva_parcial_sin_contar_sesion(self):
        with tempfile.TemporaryDirectory() as t:
            r,p=self.ejecutar(t,cancelar=True)
            self.assertFalse(r['completado'])
            sesion=json.loads(next(Path(t).rglob('sesion.json')).read_text(encoding='utf-8'))
            self.assertFalse(sesion['completa']);self.assertLess(sesion['imagenes'],4)

    def test_validacion_solo_habilita_con_cuatro_sesiones_completas(self):
        from ai.facial import cnn_dataset
        with tempfile.TemporaryDirectory() as t:
            raiz=Path(t);fuentes=[];entradas={}
            for i in range(16):
                sid='captura_'+str(i//4);p=raiz/sid/f'subject01_{i}.png'
                p.parent.mkdir(exist_ok=True);p.write_bytes(str(i).encode())
                fuentes.append((p,False,{'sesion_documentada':{'subject':'subject01','session_id':sid,
                    'fecha_hora':'2026-10-15T12:00:00-06:00','grupo':'subject01:'+sid}}))
                entradas[p]=np.random.default_rng(i).random((100,100,1)).astype(np.float32)
            with patch.object(cnn_dataset,'MotorEmbeddings'),patch.object(cnn_dataset,'MUESTRAS_CNN',raiz/'nuevas'),\
                 patch.object(cnn_dataset,'INFORME',raiz/'informe.json'),\
                 patch.object(cnn_dataset,'fuentes_cnn',side_effect=lambda s,r:iter(fuentes)),\
                 patch.object(cnn_dataset,'preparar',side_effect=lambda m,p,a,d:(entradas[p],p.name,{'valida':True})):
                d=cnn_dataset.cargar(raiz,subjects_activos=['subject01'])
                resumen=d['reporte_dataset']['resumen_sesiones']
                self.assertTrue(resumen['listo']);self.assertEqual(resumen['sesiones_completas'],4)
                self.assertEqual(resumen['clases_incompletas'],0)
                self.assertEqual(resumen['fugas_entre_sesiones'],0)
                self.assertEqual(set(map(len,cnn_dataset.particionar(d).values())),{4})
                fuentes.pop()
                d=cnn_dataset.cargar(raiz,subjects_activos=['subject01'])
                self.assertFalse(d['reporte_dataset']['resumen_sesiones']['listo'])
                self.assertEqual(d['reporte_dataset']['sesiones_por_subject']['subject01'],3)


if __name__=='__main__':unittest.main()
