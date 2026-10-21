"""Contratos de presentación, calidad y descarte; sin cámara ni datos persistidos."""
import unittest
from decimal import Decimal
from unittest.mock import patch
import numpy as np
from core.formato_numerico import format_numero,format_moneda,format_campo
from ai.facial.pipeline_facial import cargar_configuracion,evaluar_calidad,TrackFacial,decision_temporal
from ai.facial.reconocimiento_embeddings import dibujar

class Presentacion(unittest.TestCase):
    def test_formato_sin_redondear_valor_original(self):
        valor=Decimal('15.92345')
        self.assertEqual(format_numero(valor),'15.92')
        self.assertEqual(valor,Decimal('15.92345'))
        self.assertEqual(format_numero(Decimal('1706.000')),'1706.00')
        self.assertEqual(format_moneda(18451.5),'C$ 18,451.50')
    def test_identificadores_y_conteos_no_se_formatean(self):
        self.assertEqual(format_campo('id_producto',24),24)
        self.assertEqual(format_campo('codigo','A-P01-E03'),'A-P01-E03')
        self.assertEqual(format_campo('empleados',16),16)
        self.assertEqual(format_campo('stock_actual',24),'24.00')
    def test_ausencias_y_no_finitos(self):
        self.assertEqual(format_numero(None),'—')
        self.assertEqual(format_numero(float('nan')),'—')
    def test_debug_no_se_dibuja_sobre_rostro(self):
        frame=np.zeros((480,640,3),np.uint8)
        r={'caja':(100,100,100,140),'estado':'RECONOCIDO','reconocido':True,'nombre':'Persona registrada','similitud':.82345,'track_id':1,'blur':23.123}
        with patch('ai.facial.reconocimiento_embeddings.cv2.putText') as texto:
            dibujar(frame,[r],debug=True)
        self.assertEqual(texto.call_count,3)
        for llamada in texto.call_args_list:
            self.assertNotIn('Blur',llamada.args[1])
            self.assertNotIn('0.82345',llamada.args[1])
            self.assertGreater(llamada.args[2][1],240)

class Evidencia(unittest.TestCase):
    def test_calidad_aceptable_requiere_mas_evidencia(self):
        cfg=cargar_configuracion()
        track=TrackFacial(1,np.zeros(15),0)
        calidad={'valida':True,'estado':'CALIDAD_ACEPTABLE','calidad':.5}
        politica={'threshold':.5,'margen':.1}
        for i in range(4):r=decision_temporal(track,'subject01',.8,.3,calidad,politica,cfg,i*.1)
        self.assertFalse(r['reconocido'])
        for i in range(4,6):r=decision_temporal(track,'subject01',.8,.3,calidad,politica,cfg,i*.1)
        self.assertTrue(r['reconocido'])
    def test_baja_calidad_nunca_confirma_identidad(self):
        cfg=cargar_configuracion();track=TrackFacial(1,np.zeros(15),0)
        for i in range(10):r=decision_temporal(track,'subject01',.99,.9,{'valida':False,'estado':'IMAGEN_BORROSA','calidad':0},{'threshold':.5,'margen':.1},cfg,i*.1)
        self.assertFalse(r['reconocido']);self.assertFalse(track.evidencia)

if __name__=='__main__':unittest.main()
