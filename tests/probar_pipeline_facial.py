"""Regresión del pipeline facial. Datos sintéticos solo para tests, nunca reportes de precisión."""

import sys
from pathlib import Path as _RutaProyecto
_RAIZ_PROYECTO = _RutaProyecto(__file__).resolve().parents[1]
if str(_RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_PROYECTO))

import json
import tempfile
import threading
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch, MagicMock

import cv2
import numpy as np

from ai.facial import pipeline_facial as p
from tools.evaluar_reconocimiento_facial import aplicar_politica, calibrar, metricas
from ai.facial.reconocimiento_embeddings import resultado_principal


def cara(x=30,y=30,w=100,h=100):
    return np.array([x,y,w,h,x+w*.3,y+h*.35,x+w*.7,y+h*.35,
                     x+w*.5,y+h*.55,x+w*.35,y+h*.75,x+w*.65,y+h*.75,.99],np.float32)


class Calidad(unittest.TestCase):
    def setUp(self):
        self.cfg=p.cargar_configuracion()
        self.frame=np.random.default_rng(42).integers(70,190,(220,220,3),dtype=np.uint8)
    def test_calidad_original_y_tamano(self):
        q=p.evaluar_calidad(self.frame,cara(),self.cfg)
        self.assertTrue(q["valida"])
        pequena=p.evaluar_calidad(self.frame,cara(w=40,h=45),self.cfg)
        self.assertEqual(pequena["estado"],"ROSTRO_MUY_PEQUENO")
        self.assertEqual(pequena["ancho_rostro"],40)
    def test_blur_iluminacion_y_corte(self):
        borrosa=np.full_like(self.frame,130)
        self.assertEqual(p.evaluar_calidad(borrosa,cara(),self.cfg)["estado"],"IMAGEN_BORROSA")
        cfg={**self.cfg,"blur_min":0,"blur_rechazo":0}
        self.assertEqual(p.evaluar_calidad(np.zeros_like(self.frame),cara(),cfg)["estado"],"ILUMINACION_DEFICIENTE")
        self.assertEqual(p.evaluar_calidad(self.frame,cara(x=-50),self.cfg)["estado"],"ANGULO_O_OCLUSION")
    def test_landmarks_y_orientacion(self):
        c=cara(); c[4]=-1
        self.assertFalse(p.evaluar_calidad(self.frame,c,self.cfg)["valida"])
        c=cara(); c[7]+=60
        self.assertFalse(p.evaluar_calidad(self.frame,c,self.cfg)["valida"])
    def test_landmarks_no_finitos_se_rechazan(self):
        c=cara(); c[0]=np.nan
        self.assertFalse(p.evaluar_calidad(self.frame,c,self.cfg)["valida"])

    def test_distancias_relativas_no_metros(self):
        self.assertEqual(p.distancia_relativa(90,100),"LEJOS")
        self.assertEqual(p.distancia_relativa(150,180),"MEDIA")
        self.assertEqual(p.distancia_relativa(300,310),"CERCA")


class Galeria(unittest.TestCase):
    def test_multimuestra_serializacion_y_binding_empleado(self):
        with tempfile.TemporaryDirectory() as directorio:
            g=p.GaleriaEmbeddings(Path(directorio)/"galeria.npz")
            v=np.zeros(128,np.float32);v[0]=1
            g.agregar("subject01",7,[v]*5,["a"]*5)
            g.agregar("subject02",8,[np.eye(128,dtype=np.float32)[1]]*5,["b"]*5)
            g.guardar(); restaurada=p.GaleriaEmbeddings(g.ruta)
            self.assertEqual(restaurada.comparar(v)[0],"subject01")
            self.assertEqual(restaurada.ultima_comparacion['segundo_candidato'],'subject02')
            self.assertAlmostEqual(restaurada.ultima_comparacion['mejor_similitud'],1)
            self.assertAlmostEqual(restaurada.ultima_comparacion['segunda_similitud'],0)
            empleados={"subject01":{"id_empleado":99,"empleado_activo":True}}
            self.assertIsNone(restaurada.comparar(v,empleados)[0])
            empleados={"subject01":{"id_empleado":7,"empleado_activo":False}}
            self.assertIsNone(restaurada.comparar(v,empleados)[0])
            empleados["subject01"]["empleado_activo"]=True
            self.assertEqual(restaurada.comparar(v,empleados)[0],"subject01")
    def test_un_parecido_aislado_no_domina(self):
        g=p.GaleriaEmbeddings(Path("archivo_inexistente_pruebas.npz"))
        g.agregar("subject01",7,[np.array([1,0])]+[np.array([0,1])]*4,["a"]*5)
        _,score,_=g.comparar(np.array([1,0]))
        self.assertAlmostEqual(score,1/3,places=6)
    def test_vectors_invalidos_y_minimo_muestras(self):
        for vector in ([0,0],[float("nan"),1]):
            with self.assertRaises(ValueError): p.normalizar(vector)
        g=p.GaleriaEmbeddings(Path("archivo_inexistente_pruebas.npz"))
        with self.assertRaises(ValueError): g.agregar("subject01",1,[[1,0]],["a"])
    def test_modificar_galeria_invalida_calibracion(self):
        with tempfile.TemporaryDirectory() as directorio:
            g=p.GaleriaEmbeddings(Path(directorio)/"g.npz")
            g.agregar("subject01",7,[[1,0]]*5,["a"]*5); g.guardar()
            cfg=p.cargar_configuracion(); ruta=Path(directorio)/"cal.json"
            politica={"calibrada":True,"threshold":.7,"margen":.1,"min_rostro":80,
                      "pipeline":p.VERSION_PIPELINE,"galeria_sha256":g.firma,"config_sha256":p.firma_configuracion(cfg)}
            p.escribir_json_atomico(ruta,politica)
            self.assertIsNotNone(p.cargar_politica(g,cfg,ruta))
            self.assertIsNone(p.cargar_politica(g,{**cfg,"resolucion":[640,480]},ruta))
            g.agregar("subject02",8,[[0,1]]*5,["b"]*5); g.guardar()
            self.assertIsNone(p.cargar_politica(g,cfg,ruta))


class Evidencia(unittest.TestCase):
    def setUp(self):
        self.cfg=p.cargar_configuracion()
        self.track=p.TrackFacial(1,cara(),0,deque(maxlen=7))
        self.q={"valida":True,"estado":"CALIDAD_OK","calidad":.9}
        self.politica={"threshold":.7,"margen":.1,"min_rostro":80}
    def decidir(self,s="subject01",score=.8,margen=.2,tiempo=0,q=None,politica=True):
        return p.decision_temporal(self.track,s,score,margen,q or self.q,self.politica if politica else None,self.cfg,tiempo)
    def test_no_autoriza_sin_calibracion(self):
        for _ in range(10):
            self.assertEqual(self.decidir(politica=False)["estado"],"SIN_CALIBRAR")
    def test_necesita_consenso_y_margen(self):
        for n in range(3): self.assertFalse(self.decidir(tiempo=n*.1)["reconocido"])
        self.assertTrue(self.decidir(tiempo=.3)["reconocido"])
        self.assertFalse(self.decidir(margen=.01,tiempo=.4)["reconocido"])
    def test_candidatos_alternados_y_desconocido(self):
        for n,s in enumerate(("subject01","subject02","subject01",None,"subject02")):
            self.assertFalse(self.decidir(s=s,tiempo=n*.1)["reconocido"])
        self.track.evidencia.clear()
        for n in range(4): resultado=self.decidir(score=.4,tiempo=n*.1)
        self.assertEqual(resultado["estado"],"DESCONOCIDO")
    def test_calidad_mala_y_expiracion_borran_evidencia(self):
        for n in range(4): self.decidir(tiempo=n*.1)
        self.assertFalse(self.decidir(q={**self.q,"valida":False,"estado":"IMAGEN_BORROSA"})["reconocido"])
        self.assertEqual(len(self.track.evidencia),0)
        self.decidir(tiempo=1)
        self.assertFalse(self.decidir(tiempo=10)["reconocido"])
        self.assertEqual(len(self.track.evidencia),1)
    def test_tracks_independientes_y_no_rostro_no_identidad(self):
        otra=p.TrackFacial(2,cara(),0)
        for n in range(4): self.decidir(tiempo=n*.1)
        r=p.decision_temporal(otra,"subject01",.8,.2,self.q,self.politica,self.cfg,.4)
        self.assertFalse(r["reconocido"])
        self.assertFalse(resultado_principal([])["reconocido"])
        self.assertFalse(resultado_principal([{"reconocido":True}]*2)["reconocido"])


class Tracking(unittest.TestCase):
    def test_ids_y_perdida_de_rostro(self):
        cfg=p.cargar_configuracion(); tracker=p.SeguimientoFacial(cfg)
        frame=np.zeros((400,500,3),np.uint8)
        tracks=tracker.actualizar(frame,[cara(20,20),cara(260,20)],0)
        ids=[t.numero for t in tracks]
        for t in tracks: t.resultado={"reconocido":True}
        tracks=tracker.actualizar(frame,[cara(25,20),cara(255,20)],.1)
        self.assertEqual([t.numero for t in tracks],ids)
        tracker.actualizar(frame,[],.2)
        self.assertTrue(all(not t.resultado for t in tracker.tracks.values()))
        self.assertEqual(len(tracker.actualizar(frame,[cara()],5)),1)
        self.assertNotIn(ids[0],tracker.tracks)
    def test_cruce_ambiguo_limpia_identidades(self):
        tracker=p.SeguimientoFacial(p.cargar_configuracion()); frame=np.zeros((300,300,3),np.uint8)
        tracks=tracker.actualizar(frame,[cara(30,30),cara(80,30)],0)
        for t in tracks: t.resultado={"reconocido":True}
        tracker.actualizar(frame,[cara(55,30)],.1)
        self.assertTrue(all(not t.resultado for t in tracks))


class Evaluacion(unittest.TestCase):
    def filas(self):
        datos=[]
        for subset in ("calibracion","prueba"):
            for n in range(20):
                for identidad,similitud in (("subject01",.8),("DESCONOCIDO",.3)):
                    datos.append({"subset":subset,"sesion":subset,"identidad_real":identidad,
                        "candidato":"subject01","similitud":similitud,"margen":.2,
                        "ancho_rostro":100,"alto_rostro":120,"calidad_estado":"CALIDAD_OK",
                        "identidad_predicha":"DESCONOCIDO","tiempo_inferencia_ms":20})
        return datos
    def test_metricas_far_frr_y_confusion(self):
        filas=self.filas()[:4]
        filas[0]["identidad_predicha"]="subject01"
        filas[1]["identidad_predicha"]="subject01"
        m=metricas(filas)
        self.assertEqual(m["far_desconocidos"],.5)
        self.assertEqual(m["frr_conocidos"],.5)
        self.assertEqual(m["precision"],.5)
        self.assertEqual(m["recall"],.5)
        self.assertEqual(sum(map(sum,m["matriz_confusion"])),4)
    def test_calibracion_empirica_y_holdout(self):
        g=MagicMock(); g.subjects=np.array(["subject01"]); g.firma="galeria"
        politica=calibrar(self.filas(),g,p.cargar_configuracion())
        self.assertTrue(politica["calibrada"])
        self.assertEqual(politica["validacion_independiente"]["identificaciones_incorrectas"],0)
        self.assertIsNotNone(politica["validacion_independiente"]["far_limite_superior_95_cero_errores"])
    def test_calibracion_no_pasa_si_unknown_cambia_en_prueba(self):
        g=MagicMock(); g.subjects=np.array(["subject01"]); g.firma="galeria"
        filas=self.filas()
        for f in filas:
            if f["subset"]=="prueba" and f["identidad_real"]=="DESCONOCIDO": f["similitud"]=.99
        with self.assertRaises(ValueError): calibrar(filas,g,p.cargar_configuracion())
    def test_no_usa_unknowns_demasiado_pequenos_para_calibrar(self):
        g=MagicMock(); g.subjects=np.array(["subject01"]); g.firma="galeria"
        filas=self.filas()
        for f in filas:
            if f["identidad_real"]=="DESCONOCIDO": f["ancho_rostro"]=32
        with self.assertRaises(ValueError): calibrar(filas,g,p.cargar_configuracion())

    def test_no_calibra_sin_unknown_o_sin_cobertura(self):
        g=MagicMock(); g.subjects=np.array(["subject01"]); g.firma="galeria"
        with self.assertRaises(ValueError): calibrar([f for f in self.filas() if f["identidad_real"]!="DESCONOCIDO"],g,p.cargar_configuracion())
        g.subjects=np.array(["subject01","subject02"])
        with self.assertRaises(ValueError): calibrar(self.filas(),g,p.cargar_configuracion())


class Compatibilidad(unittest.TestCase):
    def test_ruta_nueva_y_legacy_explicita(self):
        from ai.facial import reconocimiento_cnn as reconocimiento
        with patch('ai.facial.reconocimiento_embeddings.reconocer_embeddings',return_value={"estado":"SIN_ROSTRO"}) as nuevo:
            reconocimiento.reconocer_con_camara(motor="embeddings")
            nuevo.assert_called_once()
        with patch.object(reconocimiento,"_reconocer_cnn_legacy",return_value={"estado":"SIN_ROSTRO"}) as anterior:
            reconocimiento.reconocer_con_camara(motor="cnn")
            anterior.assert_called_once()
    def test_autenticacion_revalida_en_sql(self):
        from ai.facial import reconocimiento_facial as reconocimiento
        r={"estado":"RECONOCIDO","reconocido":True,"id_empleado":7,"confianza":.8}
        with patch('ai.facial.reconocimiento_embeddings.reconocer_embeddings',return_value=r), \
             patch.object(reconocimiento,"_obtener_empleado",return_value={"id_empleado":7}) as validar:
            empleado=reconocimiento.reconocer_empleado(motor="embeddings")
            self.assertEqual(empleado["id_empleado"],7)
            validar.assert_called_once_with(7,solo_activo=True)
    def test_fuente_rtsp_no_usa_dshow_y_usb_pide_hd(self):
        from surveillance import camara_utils
        camara=MagicMock(); camara.isOpened.return_value=True
        with patch.object(cv2,"VideoCapture",return_value=camara) as abrir:
            camara_utils.abrir_camara("rtsp://ejemplo/camara")
            self.assertEqual(abrir.call_args.args[1],cv2.CAP_FFMPEG)
        with patch.object(cv2,"VideoCapture",return_value=camara):
            camara_utils.abrir_camara(0,(1920,1080))
            camara.set.assert_any_call(cv2.CAP_PROP_FRAME_WIDTH,1920)
    def test_augmentation_cnn_no_modifica_original(self):
        from ai.facial.entrenar_cnn_rostros import aumentar_rostro_distante
        original=np.full((100,100,1),.5,np.float32)
        copia=original.copy()
        aumentada=aumentar_rostro_distante(original)
        self.assertEqual(aumentada.shape,original.shape)
        self.assertTrue(np.isfinite(aumentada).all())
        self.assertTrue((aumentada>=0).all() and (aumentada<=1).all())
        np.testing.assert_array_equal(original,copia)

    def test_modelos_reales_y_embedding_normalizado(self):
        from tools.evaluar_reconocimiento_facial import cargar_imagen
        motor=p.MotorEmbeddings(); frame=cargar_imagen(p.BASE_DIR/"Clasificacion/rostros/DataSet01/data/subject01.normal.gif")
        caras=motor.detectar(frame,exhaustivo=True)
        self.assertEqual(len(caras),1)
        vector,alineado=motor.extraer(frame,caras[0])
        self.assertEqual(alineado.shape,(112,112,3))
        self.assertAlmostEqual(float(np.linalg.norm(vector)),1,places=5)
        self.assertTrue(np.isfinite(vector).all())


if __name__=="__main__":
    unittest.main(verbosity=2)
