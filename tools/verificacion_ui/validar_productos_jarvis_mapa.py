"""Verifica consultas, menús y navegación opcional con SQL de solo lectura."""
from pathlib import Path
from types import SimpleNamespace
import json
import runpy
import sys
import time
import tkinter as tk
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from ui import interfaz
from ui import inventario_ui
from ai.anomalies import deteccion_anomalias
from jarvis import agente_inventario as agente
from tools.verificacion_ui.validar_tablas_presentacion import widgets

instancias=[]
inicializar=inventario_ui.InventarioUI.__init__
def registrar(self,*args,**kwargs):inicializar(self,*args,**kwargs);instancias.append(self)


def comprobar(root,*args,**kwargs):
    errores=[];root.report_callback_exception=lambda t,e,tb:errores.append(str(e))
    def actualizar(segundos=.1):
        limite=time.monotonic()+segundos
        while time.monotonic()<limite:root.update();time.sleep(.02)
    try:
        actualizar(2);ui=instancias[0]
        assert ui.datos,'Se requieren productos disponibles para comprobar la interfaz.'
        p=next(iter(ui.datos.values()));pid=p['id_producto'];ui.tabla.selection_remove(*ui.tabla.selection());ui.actualizar_acciones()
        assert all(str(b.cget('state'))=='disabled' for b in ui.botones_seleccion)
        assert ui.menu_mas.entrycget(0,'state')=='disabled'
        assert ui.menu_mas.entrycget(1,'state')=='disabled'
        assert [ui.menu_mas.entrycget(i,'label') for i in range(3)]==['Ficha del producto','Desactivar / reactivar','Análisis de rotación']
        assert [ui.menu_catalogos.entrycget(i,'label') for i in range(4)]==['Categorías','Unidades','Ubicaciones','Motivos']
        botones=[str(w.cget('text')) for w in widgets(ui.padre) if w.winfo_class()=='TButton']
        assert set(botones)=={'+ Nuevo producto','Editar','Ver ubicación','Limpiar filtros'},botones
        ui.tabla.selection_set(str(pid));actualizar()
        assert all(str(b.cget('state'))=='normal' for b in ui.botones_seleccion)
        with patch.object(root,'mostrar_producto_en_mapa',wraps=root.mostrar_producto_en_mapa) as mostrar:
            ui.ver_ubicacion();actualizar();assert mostrar.call_count==0
            ubicacion=next(w for w in widgets(root) if w.winfo_class()=='TButton' and str(w.cget('text'))=='Ver en mapa')
            ubicacion.invoke();actualizar();mostrar.assert_called_once_with(pid)
        ui.busqueda.insert(0,p['codigo']);ui.programar(SimpleNamespace(keysym='x'))
        ui.buscar_ahora();actualizar(.4)
        assert pid in ui.datos and all(p['codigo'].lower() in r['codigo'].lower() or p['codigo'].lower() in r['nombre'].lower() for r in ui.datos.values())
        assert ui.pendiente is None
        ui.limpiar();actualizar();assert len(ui.datos)>0
        # Ruta real de JARVIS y botón en la misma burbuja: no ejecuta navegación al responder.
        sesion='verificacion_mapa_opcional';agente.reiniciar_contexto(sesion)
        r=agente.procesar_consulta('ubicacion de '+p['codigo'],True,sesion)
        assert not r['acciones_ui'] and r['acciones_opcionales'][0]=={'tipo':'producto_mapa','id':pid},r
        chat=next(w for w in widgets(root) if isinstance(w,interfaz.ChatConversacion))
        with patch.object(root,'mostrar_producto_en_mapa',wraps=root.mostrar_producto_en_mapa) as mostrar:
            chat.agregar('Jarvis',r['respuesta'],[('Ver en mapa',lambda:root.mostrar_producto_en_mapa(pid))])
            assert mostrar.call_count==0
            boton=next(w for w in widgets(chat) if w.winfo_class()=='TButton' and str(w.cget('text'))=='Ver en mapa')
            boton.invoke();actualizar();mostrar.assert_called_once_with(pid)
        assert agente.obtener_contexto(sesion)['ultimo_producto_id']==pid
        r=agente.procesar_consulta('Muestramelo',True,sesion)
        assert r['acciones_ui']==[{'tipo':'producto_mapa','id':pid}],r
        # Doble clic y menú contextual están vinculados y dependen de una fila real.
        assert ui.tabla.bind('<Double-1>') and ui.tabla.bind('<Button-3>')
        ui.tabla.selection_set(str(pid));ui.actualizar_acciones()
        assert ui.menu_contextual.entrycget(0,'state')=='normal'
        assert not errores,errores
        print('Productos: 3 acciones principales, 2 menús, selección, búsqueda y ubicación opcional correctos. JARVIS: texto primero, botón y orden posterior con contexto comprobados con datos SQL actuales.')
    finally:interfaz.cerrar_audio();root.destroy()


if __name__=='__main__':
    with patch.object(deteccion_anomalias,'guardar_hallazgos',return_value=None),patch.object(interfaz,'precalentar_voz',return_value=None),\
         patch.object(inventario_ui.InventarioUI,'__init__',registrar),patch.object(tk.Misc,'mainloop',comprobar):
        runpy.run_path('main.py',run_name='__main__')
