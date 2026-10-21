"""Contratos de presentación y recarga; sin SQL, audio ni transporte."""
from datetime import datetime
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from core.formato_numerico import format_campo
from ui.ui_theme import configurar_estilos
from ui.ui_components import StandardTreeview,FilterBar,insertar_fila


class Presentacion(unittest.TestCase):
    def test_fecha_y_cantidad_sin_alterar_origen(self):
        fecha=datetime(2026,10,19,12,30,15,123456)
        self.assertEqual(format_campo('fecha',fecha),'19/10/2026 12:30:15')
        self.assertEqual(format_campo('fecha','2026-10-19T12:30:15.123456'),'19/10/2026 12:30:15')
        self.assertEqual(format_campo('cantidad',20),'20.00')
        self.assertEqual(fecha.microsecond,123456)

    def setUp(self):
        try:self.root=tk.Tk()
        except tk.TclError as error:self.skipTest(str(error))
        self.root.withdraw();configurar_estilos(self.root)

    def tearDown(self):
        if hasattr(self,'root'):self.root.destroy()

    def test_tabla_conserva_columnas_ocultas_y_seleccion(self):
        t=StandardTreeview(self.root,('fecha','cantidad','detalle'),('Fecha','Cantidad','Detalle'),(150,100,200))
        insertar_fila(t,iid='1',values=(datetime(2026,10,19),2.5,'Detalle completo'))
        t.configure(displaycolumns=('fecha','cantidad'));t.selection_set('1')
        self.assertEqual(t.item('1','values')[1],'2.50')
        self.assertEqual(t.set('1','detalle'),'Detalle completo')
        self.assertEqual(t.selection(),('1',))

    def test_prediccion_filtrar_y_recargar_incluye_filas_ocultas(self):
        from ui import prediccion_ui
        class Inmediato:
            ocupado=False
            def __init__(self,root):pass
            def ejecutar(self,fn,mostrar,al_error=None):mostrar(fn())
        def resultado(i,*args,**kwargs):
            return dict(producto='Producto '+str(i),stock_actual=10,consumo_promedio_diario=1,
                        dias_restantes_promedio=10,riesgo='MEDIO',datos_suficientes=True,
                        fecha_agotamiento=None,explicacion='Consumo registrado.',
                        tendencia='ESTABLE',recomendacion='',consumo_diario=[])
        with patch.object(prediccion_ui,'TrabajosUI',Inmediato), \
             patch.object(prediccion_ui,'buscar_inventario',return_value=[{'id_producto':i,'estado':True} for i in (1,2)]), \
             patch.object(prediccion_ui,'listar_predicciones',side_effect=lambda _: [resultado(i) for i in (1,2)]) as motor, \
             patch('integrations.telegram.telegram_service.crear_estado_telegram'):
            ui=prediccion_ui.PrediccionUI(ttk.Frame(self.root),self.root,StandardTreeview)
            ui.busqueda.insert(0,'Producto 1');ui.filtrar()
            self.assertEqual(len(ui.t.get_children()),1)
            self.assertEqual(motor.call_count,1)
            ui.cargar()
            self.assertEqual(len(ui.t.get_children()),1)
            ui.busqueda.delete(0,'end');ui.filtrar()
            self.assertEqual(len(ui.t.get_children()),2)
            ui.t.selection_set('0');ui.seleccionar()
            self.assertEqual(ui.kpis['stock'].get(),'10.00')


if __name__=='__main__':unittest.main()
