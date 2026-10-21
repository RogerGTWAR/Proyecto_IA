"""Integración central sin publicar mensajes ni abrir cámaras."""
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock,patch
import numpy as np
from integrations.telegram import telegram_service as t
from core.config_manager import DEFAULTS


class ModulosTelegram(unittest.TestCase):
    def setUp(self):
        from tests.probar_system_state import aislar_estado
        aislar_estado(self)
        self.s=t.ServicioTelegram()
        self.global_service=patch.object(t,'servicio_telegram',self.s)
        self.global_service.start()
        self.addCleanup(self.global_service.stop)
        self.frame=np.full((240,320,3),90,np.uint8)
        from core.event_bus import EventBus
        from core.event_subscribers import consumir_telegram,NOTIFICABLES
        self.bus=EventBus();self.addCleanup(self.bus.close)
        bus_patch=patch('core.event_bus.event_bus',self.bus);bus_patch.start();self.addCleanup(bus_patch.stop)
        self.bus.subscribe(NOTIFICABLES,consumir_telegram)

    def conocido(self,**extras):
        r=dict(reconocido=True,id_empleado=7,nombre='Ana Ruiz',codigo_empleado='EMP-007',
            motor='embeddings',estado='EMPLEADO_RECONOCIDO',similitud=.78,caja=[40,60,80,90])
        r.update(extras)
        return r

    def test_sface_reconocido_una_vez_con_frame_original(self):
        for _ in range(50):t.notificar_reconocimiento_empleado(self.conocido(),self.frame,'facial_empleados:1:7')
        self.assertEqual(self.s.cola.qsize(),1)
        e=self.s.cola.get_nowait()
        self.frame[:]=0
        self.assertTrue(np.all(e['_frame']==90))
        for campo in ('[RECONOCIMIENTO FACIAL]','Categoría: Empleados','Módulo: Empleados',
            'Ana Ruiz','EMP-007','Motor facial: SFace','Confianza facial: 0.78'):
            self.assertIn(campo,e['mensaje'])
        self.assertNotIn('Confianza YOLO',e['mensaje'])

    def test_cnn_no_publica_reconocimientos(self):
        self.assertIsNone(t.notificar_reconocimiento_empleado(self.conocido(motor='cnn'),self.frame,'cnn:1'))
        self.assertTrue(self.s.cola.empty())

    def test_verificando_no_publica(self):
        self.assertIsNone(t.notificar_reconocimiento_empleado(self.conocido(reconocido=False),self.frame,'facial:1'))
        self.assertIsNone(t.notificar_rostro_desconocido(dict(estado='VERIFICANDO'),self.frame))
        self.assertTrue(self.s.cola.empty())

    def test_desconocido_requiere_evaluacion_y_calidad(self):
        for r in (dict(estado='NO_RECONOCIDO'),dict(estado='DESCONOCIDO',calidad_estado='BORROSO'),
                  dict(estado='DESCONOCIDO',motor='cnn')):
            self.assertIsNone(t.notificar_rostro_desconocido(r,self.frame))
        r=t.notificar_rostro_desconocido(dict(estado='DESCONOCIDO',calidad_estado='CALIDAD_OK'),self.frame,referencia='facial:desconocido')
        self.assertTrue(r['encolado'])
        e=self.s.cola.get_nowait()
        self.assertTrue(e['_crear_alerta_facial'])
        for campo in ('[ALERTA]','Categoría: Empleados','Subtipo: Persona no reconocida','DESCONOCIDO'):
            self.assertIn(campo,e['mensaje'])

    def test_worker_genera_foto_y_crop_sin_cambiar_frame(self):
        import cv2
        t.notificar_reconocimiento_empleado(self.conocido(),self.frame,'facial_empleados:foto')
        e=self.s.cola.get_nowait()
        with tempfile.TemporaryDirectory() as carpeta,patch.object(t,'BASE',Path(carpeta)), \
             patch.object(self.s,'_guardar') as guardar,patch.object(self.s,'entregar'):
            self.s._procesar_evento(e)
            self.assertTrue(Path(e['imagen']).is_file())
            self.assertIn('empleados',e['imagen'])
            crop=cv2.imread(e['datos']['recorte'])
            self.assertEqual(crop.shape[:2],(90,80))
            self.assertTrue(np.all(self.frame==90))
            guardar.assert_called_once()

    def test_todos_los_filtros_habilitados_y_separados(self):
        for tipo in ('inventario','alertas','anomalias','prediccion','vigilancia','facial','sistema'):
            c=deepcopy(DEFAULTS['telegram'])
            self.assertTrue(t.permitido(c,tipo,'ALTA'))
            c[tipo]=False
            self.assertFalse(t.permitido(c,tipo,'ALTA'))
        c=deepcopy(DEFAULTS['telegram']);c['alertas']=False
        self.assertIsNotNone(t._filtro_evento(c,'inventario','ALTA',{'origen_telegram':'Alertas'}))
        self.assertIsNone(t._filtro_evento(c,'prediccion','ALTA',{}))

    def test_publicar_estado_conserva_categoria_para_ui(self):
        self.s.notificar('prediccion','Riesgo','Cobertura reducida',referencia='riesgo:1:2:ALTO')
        self.s._publicar_estado('riesgo:1:2:ALTO',dict(estado='ENVIADA',partes={'foto':{'enviado':True}}))
        self.assertEqual(self.s.estado_entrega('riesgo:1:2:ALTO')['tipo'],'prediccion')
        self.assertIn('Foto enviada',t.texto_estado_entrega('riesgo:1:2:ALTO'))
        self.assertIn('Confirmado',t.texto_estado_entrega('riesgo:1:2:ALTO'))

    def test_misma_prediccion_con_alerta_recreada_no_repite_aviso(self):
        self.bus.seed_state('riesgo:1:operativo','ALTO')
        with patch('inventory.inventario_service.consultar',side_effect=[[dict(riesgo='ALTO',id_alerta=8)],[dict(id_alerta=9)]]), \
             patch('core.database.conectar',return_value=Mock()),patch.object(self.s,'_omitir') as omitir, \
             patch.object(self.s,'notificar') as notificar:
            self.s._cambio_riesgo(1,80,dict(riesgo='ALTO',datos_suficientes=True))
            notificar.assert_not_called()
            self.assertEqual(len(self.bus.store.get_events_by_type('RIESGO_ALTO')),0)
            self.assertEqual(len(self.bus.store.get_events_by_type('PREDICCION_GENERADA')),1)

    def test_snapshot_identifica_al_empleado_reconocido(self):
        t.notificar_reconocimiento_empleado(self.conocido(),self.frame,'facial_empleados:identidad')
        e=self.s.cola.get_nowait()
        self.assertEqual(t.evento_visual(e['datos'])['identidad_texto'],'Ana Ruiz')

    def test_worker_interrumpido_deja_aviso_para_su_recuperacion(self):
        def ejecutar():
            if self.bus.store.get_events_by_type('TELEGRAM_ERROR'):self.s.detener.set()
            else:raise RuntimeError('Interrupción del consumidor')
        with patch.object(self.s,'_ejecutar',side_effect=ejecutar),patch.object(self.s.detener,'wait'):
            self.s._ejecutar_con_limpieza()
        eventos=self.bus.store.get_events_by_type('TELEGRAM_ERROR')
        self.assertEqual(len(eventos),1)
        self.assertEqual('TELEGRAM',eventos[0].data['componente'])
        self.assertEqual(self.s.cola.qsize(),0)

    def test_categoria_desconocida_es_rechazada(self):
        with self.assertRaises(ValueError):self.s.notificar('otro','Aviso','Dato',referencia='otro:1')

    def test_stock_solo_transiciones_y_recuperacion(self):
        self.s.base_alertas=0;self.s.base_anomalias=0
        self.s.estados_stock[1]='NORMAL'
        alertas=[];stock=[dict(id_producto=1,stock_actual=4,stock_minimo=5)]
        def consultar(sql,*args):
            if 'FROM alertas a' in sql:return alertas
            if 'FROM vw_inventario' in sql:return stock
            return []
        def alerta(numero,tipo):
            return dict(id_alerta=numero,id_producto=1,tipo=tipo,mensaje='Estado del producto',nivel='ALTA',
                producto='Filtro',codigo='FIL-001',stock_actual=stock[0]['stock_actual'],stock_minimo=5)
        with patch('inventory.inventario_service.consultar',side_effect=consultar),patch('core.database.conectar',return_value=Mock()), \
             patch.object(self.s,'_guardar'),patch('inventory.mapa_almacen.ubicaciones_producto',return_value=[]):
            alertas[:]=[alerta(1,'Stock bajo')];self.s._observar()
            self.assertEqual(self.s.cola.qsize(),1)
            self.s._observar()
            self.assertEqual(len(self.bus.store.get_events_by_type('STOCK_BAJO')),1)
            alertas[:]=[alerta(2,'Stock bajo')];self.s._observar()
            self.assertEqual(self.s.cola.qsize(),1)
            self.assertEqual(len(self.bus.store.get_events_by_type('STOCK_BAJO')),1)
            stock[0]['stock_actual']=0;alertas[:]=[alerta(3,'Producto agotado')];self.s._observar()
            self.assertEqual(self.s.cola.qsize(),2)
            stock[0]['stock_actual']=20;alertas.clear();self.s._observar()
            self.assertEqual(self.s.estados_stock[1],'NORMAL')
            stock[0]['stock_actual']=4;alertas[:]=[alerta(4,'Stock bajo')];self.s._observar()
            self.assertEqual(self.s.cola.qsize(),3)

    def test_estado_de_ui_solo_lee_cache(self):
        etiqueta=Mock();etiqueta.winfo_exists.return_value=True
        self.s.notificar('facial','Empleado','Reconocido',referencia='facial_empleados:1')
        with patch('tkinter.ttk.Label',return_value=etiqueta),patch.object(t,'_enviar') as enviar, \
             patch('core.database.conectar') as sql:
            t.crear_estado_telegram(Mock(),('facial',))
            etiqueta.after.call_args.args[1]()
            self.assertIn('facial_empleados:1',etiqueta.configure.call_args.kwargs['text'])
            enviar.assert_not_called();sql.assert_not_called()


if __name__=='__main__':unittest.main()
