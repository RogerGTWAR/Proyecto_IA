"""Filtros automáticos, instantáneas y notificaciones sin envíos reales."""
from copy import deepcopy
from datetime import datetime
import json
import time
import unittest
from unittest.mock import Mock,patch

from core.config_manager import DEFAULTS
from integrations.telegram.telegram_service import ServicioTelegram,permitido,formatear_alerta,formatear_anomalia
from ui.analisis_ui import resumir_predicciones
from core.formato_numerico import format_campo


class Politica(unittest.TestCase):
    def test_habilitacion_categoria_y_nivel(self):
        c=deepcopy(DEFAULTS['telegram']);self.assertTrue(permitido(c,'inventario','ALTA'))
        c['habilitado']=False;self.assertFalse(permitido(c,'inventario','ALTA'))
        c.update(habilitado=True,nivel_minimo='ALTO+')
        self.assertFalse(permitido(c,'inventario','MEDIA'));self.assertTrue(permitido(c,'inventario','CRÍTICA'))
        c['inventario']=False;self.assertFalse(permitido(c,'inventario','ALTA'))
    def test_fechas_no_modifican_valor(self):
        d=datetime(2026,10,17,13,4,8,123456)
        self.assertEqual(format_campo('fecha',d),'17/10/2026 13:04:08');self.assertEqual(d.microsecond,123456)
    def test_resumen_no_inventa_critico_sin_datos(self):
        self.assertEqual(resumir_predicciones([]),(0,None))
        self.assertEqual(resumir_predicciones([dict(producto='A',riesgo='SIN DATOS')]),(0,None))
    def test_critico_se_ordena_por_motor_existente(self):
        filas=[dict(producto='A',riesgo='ALTO',dias_restantes_promedio=2),dict(producto='B',riesgo='CRÍTICO',dias_restantes_promedio=1)]
        cantidad,r=resumir_predicciones(filas);self.assertEqual(cantidad,2);self.assertEqual(r['producto'],'B')
    def test_alerta_y_anomalia_datos_reales_del_evento(self):
        a=dict(tipo='Producto agotado',nivel='Alta',producto='Filtro',codigo='FIL-001',stock_actual=0,stock_minimo=5,
               mensaje='Sin stock',fecha_creacion=datetime(2026,10,17),atendida=True)
        t=formatear_alerta(a);self.assertIn('Stock actual: 0.00',t);self.assertIn('Estado: Atendida',t)
        an=dict(producto='Filtro',tipo_movimiento='Salida',cantidad=20,score=4.5,nivel='CRÍTICA',empleado='Ana',
                fecha=datetime(2026,10,17),motivo='Cantidad superior al patrón',referencia_historica='Promedio previo 3.00')
        t=formatear_anomalia(an);self.assertIn('Promedio previo 3.00',t);self.assertNotIn('fraude',t.lower())


class Entregas(unittest.TestCase):
    def setUp(self):
        self.servicio=ServicioTelegram();self.estado='PENDIENTE';self.intentos=0
        self.q=Mock();self.c=Mock();self.c.cursor.return_value=self.q
        def ejecutar(sql,*args):
            if 'SELECT tipo,nivel,estado,contenido' in sql:
                self.q.fetchone.return_value=('inventario','ALTA',self.estado,json.dumps({'mensaje':'Stock bajo','imagen':None,'video':None}))
            elif 'OUTPUT INSERTED.id_notificacion' in sql:
                if self.estado=='PENDIENTE':self.estado='ENVIANDO';self.intentos+=1;self.q.fetchone.return_value=(5,)
                else:self.q.fetchone.return_value=None
            elif 'fecha_envio=CASE' in sql:self.estado=args[0]
            elif "SET estado='OMITIDA'" in sql:self.estado='OMITIDA'
            return self.q
        self.q.execute.side_effect=ejecutar
        self.cfg=deepcopy(DEFAULTS);self.cfg['telegram']['habilitado']=True
        self.conexion=patch('core.database.conectar',return_value=self.c);self.conexion.start()
        self.config=patch('core.config_manager.cargar_configuracion',return_value=self.cfg);self.config.start()
    def tearDown(self):self.conexion.stop();self.config.stop()
    def test_misma_referencia_no_se_envia_dos_veces(self):
        with patch('integrations.telegram.telegram_service._enviar',return_value={'enviado':True,'detalle':'Confirmado'}) as enviar:
            self.assertTrue(self.servicio.entregar('alerta:5')['enviado'])
            self.assertTrue(self.servicio.entregar('alerta:5')['enviado'])
            self.assertEqual(enviar.call_count,1);self.assertEqual(self.intentos,1)
    def test_fallo_confirmado_se_conserva_como_error(self):
        with patch('integrations.telegram.telegram_service._enviar',return_value={'enviado':False,'detalle':'HTTP 403'}):
            self.assertEqual(self.servicio.entregar('alerta:5')['estado'],'ERROR')
    def test_entrega_incierta_no_se_repite(self):
        with patch('integrations.telegram.telegram_service._enviar',return_value={'enviado':False,'incierto':True,'detalle':'Sin confirmación'}) as enviar:
            self.servicio.entregar('alerta:5');self.servicio.entregar('alerta:5')
            self.assertEqual(self.estado,'INCIERTO');self.assertEqual(enviar.call_count,1)
    def test_deshabilitado_no_envia(self):
        self.cfg['telegram']['habilitado']=False
        with patch('integrations.telegram.telegram_service._enviar') as enviar:
            self.servicio.entregar('alerta:5');enviar.assert_not_called();self.assertEqual(self.estado,'OMITIDA')
    def test_reintento_no_incluye_enviadas_ni_inciertas(self):
        self.q.fetchall.return_value=[]
        self.servicio.reintentar_errores()
        sql=self.q.execute.call_args.args[0]
        self.assertIn("WHERE estado='ERROR'",sql)
    def test_referencia_es_obligatoria(self):
        with self.assertRaises(ValueError):self.servicio.notificar('inventario','Título','Mensaje')
    def test_observador_no_envia_historicos(self):
        self.servicio.base_alertas=22;self.servicio.base_anomalias=12
        with patch('inventory.inventario_service.consultar',return_value=[]) as consultar,patch.object(self.servicio,'notificar') as notificar:
            self.servicio._observar();notificar.assert_not_called()
            self.assertIn('a.id_alerta>?',consultar.call_args_list[0].args[0])
            self.assertEqual(consultar.call_args_list[0].args[1],22)
    def test_no_recalcula_prediccion_sin_nuevos_movimientos(self):
        self.servicio.base_movimientos=100
        with patch('inventory.inventario_service.consultar',return_value=[]),patch('ai.prediction.prediccion_stock.predecir_agotamiento') as predecir:
            self.servicio._observar_movimientos();predecir.assert_not_called()
    def test_primer_riesgo_relevante_tras_movimiento_nuevo_notifica(self):
        with patch('inventory.inventario_service.consultar',side_effect=[[],[]]),patch.object(self.servicio,'notificar') as notificar:
            self.servicio._cambio_riesgo(1,80,dict(riesgo='ALTO',datos_suficientes=True))
            notificar.assert_called_once()
            self.assertEqual(notificar.call_args.args[0],'prediccion')
    def test_cambio_a_critico_mismo_evento_no_repite_alerta_original(self):
        r=dict(riesgo='CRÍTICO',datos_suficientes=True,producto='Filtro',stock_actual=2,consumo_promedio_diario=1,dias_restantes_promedio=2)
        with patch('inventory.inventario_service.consultar',side_effect=[[dict(riesgo='ALTO',id_alerta=8)],[dict(id_alerta=8)],[dict(id_notificacion=12)]]),patch.object(self.servicio,'notificar') as notificar:
            self.servicio._cambio_riesgo(1,80,r)
            self.assertEqual(notificar.call_args.kwargs['referencia'],'riesgo:1:80:CRÍTICO')
    def test_riesgo_sin_cambio_no_notifica(self):
        with patch('inventory.inventario_service.consultar',side_effect=[[dict(riesgo='ALTO',id_alerta=8)],[dict(id_alerta=8)]]),patch.object(self.servicio,'notificar') as notificar:
            self.servicio._cambio_riesgo(1,80,dict(riesgo='ALTO',datos_suficientes=True))
            notificar.assert_not_called()


class ReportesAutomaticos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import ttkbootstrap as tb
        cls.root=tb.Window(themename='flatly');cls.root.withdraw()
    @classmethod
    def tearDownClass(cls):cls.root.destroy()
    def setUp(self):
        from tkinter import ttk
        from integrations.reporting import reportes_ui
        from integrations.reporting.reportes import preparar_reporte
        self.panel=ttk.Frame(self.root);self.panel.pack()
        self.consultas=[]
        def obtener(tipo,filtros):
            self.consultas.append((tipo,deepcopy(filtros)))
            return preparar_reporte(dict(titulo=tipo,generado=datetime.now(),filtros={k:v for k,v in filtros.items() if v not in ('','Todos')},
                columnas=('nombre',),filas=[{'nombre':'Filtro'}],totales={},mensaje=''))
        self.patches=[patch.object(reportes_ui,'buscar_inventario',return_value=[]),patch.object(reportes_ui,'listar_categorias',return_value=[]),
            patch.object(reportes_ui,'listar_ubicaciones',return_value=[]),patch.object(reportes_ui,'obtener_datos_reporte',side_effect=obtener)]
        for p in self.patches:p.start()
        def tabla(padre,cols,titulos,anchos):
            t=ttk.Treeview(padre,columns=cols,show='headings');t.pack();return t
        self.ui=reportes_ui.ReportesUI(self.panel,self.root,tabla);self.bombear(.4)
    def tearDown(self):
        self.panel.destroy()
        for p in self.patches:p.stop()
    def bombear(self,segundos):
        fin=time.monotonic()+segundos
        while time.monotonic()<fin:self.root.update();time.sleep(.01)
    def test_carga_inicial_automatica_y_sin_boton(self):
        self.assertEqual(self.ui.reporte['titulo'],'Inventario actual');self.assertTrue(self.consultas)
        self.assertEqual(str(self.ui.botones_exportar[0]['state']),'normal')
    def test_cambio_combo_carga_y_desactiva_exportacion(self):
        self.ui.controles['estado'].set('BAJO');self.ui.controles['estado'].event_generate('<<ComboboxSelected>>')
        self.assertIsNone(self.ui.reporte);self.bombear(.3)
        self.assertEqual(self.ui.reporte['filtros']['estado'],'BAJO')
    def test_debounce_fechas(self):
        self.ui.tipo.set('Movimientos');self.ui.cambiar();self.bombear(.4)
        inicial=len(self.consultas);w=self.ui.controles['desde']
        for c in '2026-10-01':w.insert('end',c);self.bombear(.01)
        self.assertEqual(len(self.consultas),inicial)
        self.bombear(.55);self.assertEqual(len(self.consultas),inicial+1)
        self.assertEqual(self.ui.reporte['filtros']['desde'],'2026-10-01')
    def test_exporta_instantanea_sin_consultar(self):
        from integrations.reporting import reportes_ui
        consultas=len(self.consultas);original=deepcopy(self.ui.reporte)
        with patch.object(reportes_ui.filedialog,'asksaveasfilename',return_value='salida.pdf'),patch.object(reportes_ui,'exportar_pdf',return_value='salida.pdf') as exportar,patch.object(reportes_ui.messagebox,'showinfo'):
            self.ui.exportar('pdf');self.bombear(.2)
            self.assertEqual(exportar.call_args.args[0],original)
            self.assertIsNot(exportar.call_args.args[0],self.ui.reporte)
        self.assertEqual(len(self.consultas),consultas)


if __name__=='__main__':unittest.main()
