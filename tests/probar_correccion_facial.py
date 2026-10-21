"""Regresiones de procedencia, particiones y exclusión de identidades retiradas."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np
from ai.facial import base_facial as b
from ai.facial import pipeline_facial as p
from ai.facial import reconocimiento_cnn as cnn


class Procedencia(unittest.TestCase):
    def test_politica_cnn_rechazada_no_adquiere_umbral_por_defecto(self):
        self.assertFalse(cnn._politica_valida({'calibrada':False,'threshold':None}))
        self.assertFalse(cnn._politica_valida({'calibrada':True,'threshold':float('nan')}))
    def test_alineada_documentada_no_se_alinea_dos_veces(self):
        motor=Mock();motor.reconocedor.feature.return_value=np.eye(128,dtype=np.float32)[0]
        frame=np.full((112,112,3),90,np.uint8)
        with patch.object(b,'leer_bgr',return_value=frame):
            vector,alineada,q=b.preparar_muestra(motor,Path('captura.png'),True,{'calidad':{'valida':True}})
        motor.detectar.assert_not_called();motor.extraer.assert_not_called()
        np.testing.assert_array_equal(alineada,frame);self.assertAlmostEqual(np.linalg.norm(vector),1)

    def test_no_se_acepta_alineacion_con_tamano_incompatible(self):
        with patch.object(b,'leer_bgr',return_value=np.zeros((100,100,3),np.uint8)):
            with self.assertRaises(ValueError):b.preparar_muestra(Mock(),Path('a.png'),True)

    def test_sin_cara_no_ejecuta_cnn_ni_alineacion(self):
        detector=Mock();detector.detectar.return_value=[]
        r=cnn._detectar_y_recortar(np.zeros((200,200,3),np.uint8),detector)
        self.assertIsNone(r[1]);detector.alinear.assert_not_called();detector.extraer.assert_not_called()

    def test_cnn_usa_alineacion_y_gris_normalizado_sin_embeddings(self):
        frame=np.full((112,112,3),(10,80,200),np.uint8)
        detector=Mock();detector.detectar.return_value=[np.arange(15,dtype=np.float32)]
        detector.alinear.return_value=frame
        with patch.object(p,'evaluar_calidad',return_value={'valida':True,'estado':'CALIDAD_OK'}):
            entrada=cnn._detectar_y_recortar(frame,detector)[1]
        esperado=cv2.resize(cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY),(100,100)).astype(np.float32)/255
        np.testing.assert_allclose(entrada[...,0],esperado)
        detector.extraer.assert_not_called();self.assertEqual(entrada.shape,(100,100,1))


class Separacion(unittest.TestCase):
    def ejecutar(self, insuficiente=False):
        with tempfile.TemporaryDirectory() as t:
            directorio=Path(t);ruta=directorio/'galeria.npz';cal=directorio/'calibracion.json'
            rng=np.random.default_rng(5);g=p.GaleriaEmbeddings(ruta,cargar=False)
            cache={}
            for j in range(2):
                s=f'subject{j+1:02d}';base=np.eye(128)[j]
                vectores=[p.normalizar(base+rng.normal(0,.01,128)) for _ in range(7 if insuficiente and j==1 else 8)]
                g.agregar(s,j+1,vectores,[f'{s}-{i}' for i in range(len(vectores))])
                cache[s]={'id_empleado':j+1,'empleado_activo':True,'nombre':s}
            g.agregar('subject17',1,g.vectores[:8],[f'retirada{i}' for i in range(8)])
            g.guardar();original=p.GaleriaEmbeddings
            def fabrica(ruta_arg=None,cargar=True):return original(ruta_arg or ruta,cargar=cargar)
            with patch.multiple(b,DIRECTORIO=directorio,GALERIA=ruta,CALIBRACION=cal,SALIDA=directorio),patch.object(b,'GaleriaEmbeddings',side_effect=fabrica):
                if insuficiente:
                    antes=p.sha256(ruta)
                    with self.assertRaises(ValueError):b.calibrar_base(cache)
                    self.assertEqual(p.sha256(ruta),antes)
                    return
                politica=b.calibrar_base(cache)
                operativa=original(ruta);informe=json.loads((directorio/'evaluacion_separada.json').read_text(encoding='utf-8'))
                self.assertNotIn('subject17',operativa.subjects)
                usados=set(map(str,operativa.archivos));c={f['archivo'] for f in informe['calibracion']};e={f['archivo'] for f in informe['evaluacion']}
                self.assertFalse(usados&c);self.assertFalse(usados&e);self.assertFalse(c&e)
                firma=operativa.firma;otra=b.calibrar_base(cache)
                self.assertEqual(otra['threshold'],politica['threshold']);self.assertEqual(original(ruta).firma,firma)
                self.assertEqual(politica['evaluacion']['identidades_incorrectas_aceptadas'],0)
    def test_descarta_etiqueta_retirada_y_no_reutiliza_holdout(self):self.ejecutar()
    def test_falta_muestras_conserva_base(self):self.ejecutar(True)

if __name__=='__main__':unittest.main()
