"""Rechazo CNN, sesiones separadas y conservación de identidades de embeddings."""
import unittest
from pathlib import Path
from unittest.mock import patch,Mock
import numpy as np

from ai.facial.seguridad_cnn import (VERSION_PROTOCOLO,ranking,metricas,buscar_politica,
                           EvidenciaCNN,parametros_validos)
from ai.facial.cnn_dataset import particionar,validar_manifest,cercanas
from ai.facial import reconocimiento_cnn as cnn


def politica():
    return {'calibrada':True,'protocolo':VERSION_PROTOCOLO,'threshold':.7,'margin':.2,
        'validacion_independiente':{'protocolo_valido':True,'muestras':8,'correctas_aceptadas':8,'incorrectas_aceptadas':0},
        'vinculos_sql':{'subject01':1,'subject02':2}}


class Decision(unittest.TestCase):
    def test_ranking_con_indices_explicitos(self):
        r=ranking([.2,.8],{0:'subject09',1:'subject03'})
        self.assertEqual(r['best_class'],'subject03');self.assertEqual(r['second_class'],'subject09')
        self.assertAlmostEqual(r['margin'],.6)
    def test_rechaza_probabilidades_y_mapeos_invalidos(self):
        for p in ([float('nan'),1],[1,1],[-.1,1.1],[1]):
            with self.assertRaises(ValueError):ranking(p,{0:'a',1:'b'})
        with self.assertRaises(ValueError):ranking([.5,.5],{0:'a',1:'a'})
    def test_no_confunde_softmax_con_identidad_confirmada(self):
        e=EvidenciaCNN();r=ranking([.51,.49],{0:'subject01',1:'subject02'})
        for i in range(5):estado,s=e.actualizar(r,politica(),i*.1)
        self.assertEqual(estado,'DESCONOCIDO');self.assertIsNone(s)
    def test_requiere_score_y_margen_en_cada_voto(self):
        e=EvidenciaCNN();r={'best_class':'subject01','best_score':.99,'margin':.01}
        for i in range(5):estado,s=e.actualizar(r,politica(),i*.1)
        self.assertEqual(estado,'DESCONOCIDO');self.assertIsNone(s)
    def test_requiere_evidencia_y_revoca_ultimo_frame_ambiguo(self):
        e=EvidenciaCNN();r=ranking([.9,.1],{0:'subject01',1:'subject02'})
        for i in range(4):self.assertIsNone(e.actualizar(r,politica(),i*.1)[1])
        self.assertEqual(e.actualizar(r,politica(),.4),('RECONOCIDO','subject01'))
        self.assertIsNone(e.actualizar({**r,'margin':.01},politica(),.5)[1])
    def test_ultimo_candidato_contrario_no_arrastra_identidad(self):
        e=EvidenciaCNN();r=ranking([.9,.1],{0:'subject01',1:'subject02'})
        for i in range(5):e.actualizar(r,politica(),i*.1)
        self.assertIsNone(e.actualizar({**r,'best_class':'subject02'},politica(),.5)[1])
    def test_expira_evidencia_antigua(self):
        e=EvidenciaCNN();r=ranking([.9,.1],{0:'subject01',1:'subject02'})
        for i in range(5):e.actualizar(r,politica(),i*.1)
        self.assertIsNone(e.actualizar(r,politica(),4)[1])
    def test_sin_politica_y_sin_margen_no_se_activa(self):
        r=ranking([.99,.01],{0:'subject01',1:'subject02'});e=EvidenciaCNN()
        self.assertEqual(e.actualizar(r,None,1),('CNN_NO_CALIBRADA',None))
        p=politica();p.pop('margin');self.assertFalse(parametros_validos(p))
    def test_sql_inactivo_y_reasignacion_no_son_reconocimiento(self):
        empleado={'id_empleado':1,'codigo_empleado':'E1','nombre':'Nombre SQL','cargo':'Cargo','empleado_activo':False}
        with patch.object(cnn,'_politica_cnn',politica()):
            r=cnn.resolver_etiqueta('subject01',.9,{'subject01':empleado},margen=.8)
            self.assertFalse(r['reconocido'])
            empleado.update(empleado_activo=True,id_empleado=99)
            self.assertFalse(cnn.resolver_etiqueta('subject01',.9,{'subject01':empleado},margen=.8)['reconocido'])
            empleado['id_empleado']=1
            self.assertTrue(cnn.resolver_etiqueta('subject01',.9,{'subject01':empleado},margen=.8)['reconocido'])
            self.assertFalse(cnn.resolver_etiqueta('subject01',.9,{'subject01':empleado})['reconocido'])
    def test_calibracion_con_errores_deriva_parametros_de_scores(self):
        filas=[{'real':'a','best_class':'a','best_score':.9,'margin':.8},
               {'real':'b','best_class':'b','best_score':.8,'margin':.6},
               {'real':'a','best_class':'b','best_score':.75,'margin':.1}]
        p=buscar_politica(filas);m=metricas(filas,p)
        self.assertEqual(m['incorrectas_aceptadas'],0);self.assertEqual(m['correctas_aceptadas'],2)
    def test_distribuciones_inseparables_no_producen_politica(self):
        filas=[{'real':'a','best_class':'b','best_score':.9,'margin':.8},
               {'real':'a','best_class':'a','best_score':.7,'margin':.2}]
        with self.assertRaises(ValueError):buscar_politica(filas)


class Particiones(unittest.TestCase):
    def datos(self):
        meta=[{'subject':s,'sesion':s+str(i//2),'grupo':s+str(i//2),'sha256':s+str(i),'pixeles_sha256':s+str(i),'archivo':s+str(i)} for s in ['a','b'] for i in range(8)]
        return {'metadatos':meta,'subjects_activos_sql':['a','b'],'problemas_particion':[]}
    def test_no_divide_grupos_de_frames_entre_conjuntos(self):
        d=self.datos();p=particionar(d);vistos={}
        for nombre,ids in p.items():
            for i in ids:
                grupo=d['metadatos'][i]['grupo']
                if grupo in vistos:self.assertEqual(nombre,vistos[grupo])
                vistos[grupo]=nombre
        self.assertEqual(len({i for v in p.values() for i in v}),16)
        m={'protocolo':VERSION_PROTOCOLO,'particiones':{k:[d['metadatos'][i] for i in ids] for k,ids in p.items()}}
        self.assertEqual(validar_manifest(m,d),[])
    def test_detecta_protocolo_anterior_y_fuga_de_captura(self):
        d=self.datos();p=particionar(d);m={'particiones':{k:[d['metadatos'][i] for i in ids] for k,ids in p.items()}}
        m['particiones']['evaluacion'].append(m['particiones']['entrenamiento'][0])
        problemas=validar_manifest(m,d)
        self.assertTrue(any('grupo' in s for s in problemas));self.assertTrue(any('anterior' in s for s in problemas))
    def test_impide_entrenamiento_con_pocas_sesiones(self):
        d=self.datos();d['problemas_particion']=['subject19: una sola sesión']
        with self.assertRaisesRegex(ValueError,'subject19'):particionar(d)
    def test_detecta_imagen_casi_duplicada(self):
        a=np.random.default_rng(5).random((100,100,1)).astype(np.float32)
        self.assertTrue(cercanas(a,a.copy()));self.assertFalse(cercanas(a,1-a))
    def test_archivos_historicos_no_acreditan_sesiones(self):
        from ai.facial.cnn_dataset import procedencia
        for nombre in ('subject01.normal.gif','subject01.leftlight.gif'):
            sesion,fecha,grupo=procedencia(Path('historicos')/nombre,'subject01',{})
            self.assertIsNone(sesion);self.assertIsNone(fecha)
            self.assertEqual(grupo,'subject01:historico_sin_sesion')
    def test_no_entrena_con_ocho_archivos_sin_sesion(self):
        d=self.datos()
        for f in d['metadatos']:f['sesion']=None
        with self.assertRaisesRegex(ValueError,'sesiones'):particionar(d)
    def test_una_sesion_con_muchos_grupos_no_habilita_clase(self):
        d=self.datos()
        for i,f in enumerate(d['metadatos']):f['sesion']='unica';f['grupo']=str(i)
        with self.assertRaises(ValueError):particionar(d)
    def test_misma_sesion_aunque_grupos_diferentes_detecta_fuga(self):
        d=self.datos();p=particionar(d)
        m={'protocolo':VERSION_PROTOCOLO,'particiones':{k:[dict(d['metadatos'][i]) for i in ids] for k,ids in p.items()}}
        d['metadatos'][p['evaluacion'][0]]['sesion']=d['metadatos'][p['entrenamiento'][0]]['sesion']
        self.assertTrue(any('Misma sesión' in s for s in validar_manifest(m,d)))
    def test_falta_una_clase_en_validacion(self):
        d=self.datos();p=particionar(d)
        m={'protocolo':VERSION_PROTOCOLO,'particiones':{k:[d['metadatos'][i] for i in ids] for k,ids in p.items()}}
        m['particiones']['validacion']=[f for f in m['particiones']['validacion'] if f['subject']=='a']
        self.assertIn('Faltan clases activas en validacion',validar_manifest(m,d))
    def test_registro_cnn_no_llama_registro_embeddings(self):
        from ai.facial import captura_rostros
        with patch.object(captura_rostros,'_capturar_sesion_cnn',return_value={'motor':'cnn'}) as cnn_cap,patch('ai.facial.reconocimiento_embeddings.registrar_embeddings') as sf:
            self.assertEqual(captura_rostros.capturar_rostros_nuevo_empleado(9,motor='cnn'),{'motor':'cnn'})
            cnn_cap.assert_called_once_with(9,None);sf.assert_not_called()

if __name__=='__main__':unittest.main()
