"""Modo provisional: separación reproducible, identidad directa y aislamiento de SQL."""
import threading
import queue
import unittest
from unittest.mock import patch,Mock
from pathlib import Path
import tempfile
import numpy as np
import cv2

from ai.facial import cnn_dataset_actual as actual
from ai.facial import reconocimiento_cnn as reconocimiento
from ai.facial.seguridad_cnn import EvidenciaCNN,parametros_validos,VERSION_PROTOCOLO


class DatasetActual(unittest.TestCase):
    def test_particion_reproducible_estratificada_sin_requerir_sesiones(self):
        datos={'y':np.repeat(np.arange(3),10),'indice_a_subject':{0:'subject01',1:'subject02',2:'subject19'},
            'metadatos':[{'pixeles_sha256':str(i),'sesion':None} for i in range(30)]}
        it,iv=actual.dividir(datos);it2,iv2=actual.dividir(datos)
        np.testing.assert_array_equal(it,it2);np.testing.assert_array_equal(iv,iv2)
        self.assertEqual((len(it),len(iv)),(24,6))
        self.assertEqual(set(datos['y'][iv]),{0,1,2})

    def test_contenido_repetido_no_cruza_particiones(self):
        d={'y':np.repeat(np.arange(2),10),'indice_a_subject':{0:'a',1:'b'},
            'metadatos':[{'pixeles_sha256':'mismo'} for i in range(20)]}
        with self.assertRaisesRegex(ValueError,'Contenido idéntico'):actual.dividir(d)

    def test_politicas_no_se_confunden_entre_modos(self):
        p={'protocolo':actual.PROTOCOLO,'provisional':True,'threshold':.6,'margin':.2}
        self.assertTrue(actual.politica_valida(p));self.assertFalse(parametros_validos(p))
        self.assertFalse(actual.politica_valida({**p,'protocolo':VERSION_PROTOCOLO}))
        e=EvidenciaCNN(validador=actual.politica_valida)
        for i in range(5):r=e.actualizar({'best_class':'subject19','best_score':.9,'margin':.8},p,i*.1)
        self.assertEqual(r,('RECONOCIDO','subject19'))
        for i in range(5):r=e.actualizar({'best_class':'subject19','best_score':.9,'margin':.01},p,1+i*.1)
        self.assertEqual(r,('DESCONOCIDO',None))

    def test_preprocesamiento_dataset_y_camara_identico(self):
        from ai.facial.cnn_dataset import preparar
        frame=np.random.default_rng(3).integers(0,256,(112,112,3),dtype=np.uint8)
        motor=Mock();motor.detectar.return_value=[np.array([0,0,112,112])];motor.alinear.return_value=frame
        with tempfile.TemporaryDirectory() as t,patch('ai.facial.pipeline_facial.evaluar_calidad',return_value={'valida':True,'estado':'CALIDAD_OK'}),patch('ai.facial.cnn_dataset.evaluar_calidad',return_value={'valida':True,'estado':'CALIDAD_OK'}):
            p=Path(t)/'foto.png';cv2.imwrite(str(p),frame)
            a,_,_=preparar(motor,p,False,{})
            _,b,*_=reconocimiento._detectar_y_recortar(frame,motor,{})
            np.testing.assert_array_equal(a,b)
            self.assertEqual(a.shape,(100,100,1));self.assertEqual(a.dtype,np.float32)

    def test_worker_provisional_no_resuelve_empleados_ni_escribe_alertas(self):
        detener=threading.Event();frames=queue.Queue();resultados=queue.Queue(maxsize=1)
        for i in range(6):frames.put((i,np.zeros((100,100,3),np.uint8)))
        conteo=[0]
        def inferir(x):
            conteo[0]+=1
            if conteo[0]==6:detener.set()
            return np.array([[.99,.01]])
        p={'protocolo':actual.PROTOCOLO,'provisional':True,'threshold':.6,'margin':.2}
        with patch.object(reconocimiento,'obtener_cache_empleados_por_subject',side_effect=AssertionError('SQL prohibido')),\
             patch.object(reconocimiento,'resolver_etiqueta',side_effect=AssertionError('No resolver empleados')),\
             patch.object(reconocimiento.ControlAlertaDesconocido,'procesar',side_effect=AssertionError('No crear alertas')),\
             patch.object(reconocimiento,'_detectar_y_recortar',return_value=((0,0,100,100),np.zeros((100,100,1),np.float32),0.,0.,'CALIDAD_OK')):
            reconocimiento._worker_inferencia(frames,resultados,detener,None,inferir,{0:'subject19',1:'subject01'},None,None,True,p)
        r=resultados.get();self.assertEqual(r['nombre'],'subject19');self.assertTrue(r['reconocido'])
        self.assertNotIn('id_empleado',r)

    def test_dataset_real_y_modelo_actual_sin_sql(self):
        from ai.facial.rostros_empleados import obtener_subjects_activos
        with patch('ai.facial.rostros_empleados.obtener_subjects_activos',side_effect=AssertionError('SQL prohibido')),\
             patch('core.database.conectar',side_effect=AssertionError('SQL prohibido')):
            d=actual.cargar_actual()
            self.assertEqual(set(d['indice_a_subject'].values()),{f'subject{i:02d}' for i in range(1,16)}|{'subject19'})
            self.assertEqual(len(d['X']),182)
            it,iv=actual.dividir(d);self.assertEqual((len(it),len(iv)),(145,37))
            modelo,clases,inferir,p=actual.recursos()
            self.assertEqual(modelo.output_shape[-1],16)
            self.assertEqual(clases[15],'subject19')
            self.assertTrue(actual.politica_valida(p))
            self.assertIs(actual.recursos()[0],modelo)


if __name__=='__main__':unittest.main()
