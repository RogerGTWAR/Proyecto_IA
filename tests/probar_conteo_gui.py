"""Flujo de tres pasos, progreso y confirmación sin cambiar inventario real."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import time
import unittest
from unittest.mock import patch,Mock
import tkinter as tk
from tkinter import ttk
import ttkbootstrap as tb
from ui import inventario_ui as ui
from inventory.conteo_inventario import resumir_conteo


def widgets(p):
    for w in p.winfo_children():yield w;yield from widgets(w)


class Resumen(unittest.TestCase):
    def test_pendientes_no_son_ceros_confirmados(self):
        r=resumir_conteo([dict(id_producto=1,cantidad_sistema=20,cantidad_fisica=20,contado=False)])
        self.assertEqual(r['contados'],0);self.assertEqual(r['correctos'],0)
    def test_diferencias_y_unidades(self):
        filas=[dict(id_producto=1,cantidad_sistema=20,cantidad_fisica=19,contado=True,unidad_medida='Unidad'),
               dict(id_producto=2,cantidad_sistema=30,cantidad_fisica=32,contado=True,unidad_medida='Litro')]
        r=resumir_conteo(filas)
        self.assertEqual((r['faltantes'],r['sobrantes'],r['diferencia']),(1,1,Decimal(1)))
        self.assertEqual(r['por_unidad']['Unidad']['diferencia'],-1)
    def test_lotes_del_mismo_producto_son_registros_separados(self):
        filas=[dict(id_producto=1,cantidad_sistema=10,cantidad_fisica=10,contado=True),dict(id_producto=1,cantidad_sistema=5,cantidad_fisica=5,contado=False)]
        r=resumir_conteo(filas);self.assertEqual((r['productos'],r['registros'],r['contados']),(1,2,1))


class Pantalla(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.root=tb.Window(themename='flatly');cls.root.withdraw()
    @classmethod
    def tearDownClass(cls):
        for tarea in cls.root.tk.call('after','info'):cls.root.after_cancel(tarea)
        cls.root.destroy()
        # Bootstrap conserva un singleton; la siguiente clase usa otra raíz Tk.
        tb.Style.instance=None
    def setUp(self):
        self.padre=ttk.Frame(self.root);self.padre.pack()
        self.datos=[dict(id_producto=i,codigo=f'REP-00{i}',nombre='Filtro '+str(i),posicion=i,
                        cantidad_sistema=Decimal(c),cantidad_fisica=Decimal(c),id_lote=None,codigo_lote=None,unidad_medida='Unidad')
                    for i,c in ((1,20),(2,30))]
        self.guardados={};self.cabeceras={};self.aplicar=Mock(side_effect=self.cerrar)
        ubicaciones=[dict(id_ubicacion=i,codigo_ubicacion=f'E0{i}-N01',estante=str(i),nivel='1') for i in (1,2)]
        self.parches=[patch.object(ui,'listar_ubicaciones',return_value=ubicaciones),
            patch.object(ui,'listar_empleados_activos',return_value=[dict(id_empleado=4,codigo_empleado='EMP-004',nombres='Ana',apellidos='Ruiz')]),
            patch.object(ui,'listar_conteo_ubicacion',side_effect=lambda _:deepcopy(self.datos)),
            patch.object(ui,'listar_conteos',side_effect=lambda:list(self.cabeceras.values())),
            patch.object(ui,'guardar_conteo',side_effect=self.persistir),patch.object(ui,'aplicar_conteo',self.aplicar),
            patch.object(ui,'cargar_conteo',side_effect=lambda n:(deepcopy(self.cabeceras[n]),deepcopy(self.guardados[n])))]
        for p in self.parches:p.start()
        def tabla(p,cols,nombres,anchos):
            t=ttk.Treeview(p,columns=cols,show='headings');t.pack(fill='both',expand=True);return t
        self.cambio=Mock();self.pantalla=ui.ConteoUI(self.padre,self.root,tabla,self.cambio)
        self.bombear(.1)
    def tearDown(self):
        if self.pantalla.autoguardado is not None:self.root.after_cancel(self.pantalla.autoguardado)
        self.bombear(.3)
        for w in self.root.winfo_children():
            if isinstance(w,tk.Toplevel):w.destroy()
        self.padre.destroy()
        for p in self.parches:p.stop()
    def bombear(self,segundos=.3):
        fin=time.monotonic()+segundos
        while time.monotonic()<fin:self.root.update();time.sleep(.01)
    def persistir(self,empleado,ubicacion,filas,id_conteo=None):
        n=id_conteo or len(self.guardados)+1
        self.guardados[n]=deepcopy(filas)
        self.cabeceras[n]=dict(id_conteo=n,id_empleado=empleado,id_ubicacion=ubicacion,estado='BORRADOR',
            estante='1',nivel='1',codigo_ubicacion='E01-N01',fecha=datetime(2026,10,17,10,32),empleado='Ana Ruiz')
        return n
    def cerrar(self,n,**kwargs):self.cabeceras[n]['estado']='APLICADO';return n
    def cargar(self):self.pantalla.cargar();self.bombear()
    def contar(self,i,cantidad):
        p=self.pantalla;p.t.selection_set(str(i));self.bombear(.03)
        p.fisico.delete(0,'end');p.fisico.insert(0,str(cantidad));p.editar();self.bombear(.65)
    def test_inicio_sin_editor_ni_borradores(self):
        self.assertFalse(self.pantalla.editor.winfo_manager());self.assertFalse(self.pantalla.panel_borradores.winfo_manager())
        self.assertEqual(str(self.pantalla.b_aplicar['state']),'disabled')
    def test_carga_no_da_por_contadas_las_cantidades_del_sistema(self):
        self.cargar();p=self.pantalla
        self.assertEqual(resumir_conteo(list(p.filas.values()))['contados'],0)
        self.assertEqual(p.t.item('0','values')[-1],'PENDIENTE')
        p.t.selection_set('0');self.bombear(.05)
        self.assertEqual(p.fisico.get(),'')
    def test_faltante_autoguardado_y_actualiza_mismo_borrador(self):
        self.cargar();self.contar(0,19);p=self.pantalla;n=p.guardado
        self.assertEqual(p.t.item('0','values')[-2:],('-1.00','FALTANTE'))
        self.assertIn('Guardado automáticamente',p.estado['text'])
        self.contar(0,22)
        self.assertEqual(p.guardado,n);self.assertEqual(len(self.guardados),1)
        self.assertEqual(p.t.item('0','values')[-2:],('+2.00','SOBRANTE'))
    def test_cero_se_registra_y_negativos_se_rechazan(self):
        self.cargar();self.contar(0,0);p=self.pantalla
        self.assertEqual(p.filas['0']['cantidad_fisica'],0)
        p.fisico.delete(0,'end');p.fisico.insert(0,'-1')
        with self.assertRaises(ValueError):p.editar()
    def test_no_aplicar_con_filas_pendientes(self):
        self.cargar();self.contar(0,19)
        with self.assertRaisesRegex(ValueError,'Complete'):self.pantalla.aplicar()
        self.aplicar.assert_not_called()
    def test_reanudar_preserva_progreso_y_responsable(self):
        self.cargar();self.contar(0,19);p=self.pantalla
        etiqueta=next(iter(p.mapa_borradores));self.assertNotIn('#',etiqueta);self.assertIn('Ana Ruiz',etiqueta)
        p.borradores.set(etiqueta);p.cargar_borrador();self.bombear()
        self.assertEqual(resumir_conteo(list(p.filas.values()))['contados'],1)
        self.assertEqual(p.es[p.e.get()],4)
    def test_cancelar_revision_no_modifica_existencias(self):
        self.cargar();self.contar(0,19);self.contar(1,30);self.pantalla.aplicar();self.bombear(.05)
        next(w for w in widgets(self.root) if isinstance(w,ttk.Button) and w['text']=='Cancelar').invoke()
        self.aplicar.assert_not_called();self.assertFalse(self.pantalla.cerrado)
    def test_confirmar_cierra_y_bloquea_edicion(self):
        self.cargar();self.contar(0,19);self.contar(1,30);p=self.pantalla
        p.aplicar();self.bombear(.05)
        next(w for w in widgets(self.root) if isinstance(w,ttk.Button) and w['text']=='Confirmar ajustes').invoke()
        self.bombear();self.aplicar.assert_called_once();self.assertTrue(p.cerrado)
        with self.assertRaisesRegex(ValueError,'finalizado'):p.editar()
        self.assertEqual(str(p.b_aplicar['state']),'disabled');self.cambio.assert_called_once()
    def test_borrador_antiguo_requiere_confirmacion_explicita(self):
        self.cargar();p=self.pantalla
        filas=deepcopy(self.datos)
        for f in filas:f['contado']=None
        p.iniciar_filas(filas,1,50)
        self.assertEqual(resumir_conteo(list(p.filas.values()))['contados'],0)


if __name__=='__main__':unittest.main()
