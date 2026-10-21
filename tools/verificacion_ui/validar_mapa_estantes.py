"""Verificar y capturar el mapa propio, sin editar datos ni activar periféricos."""
from pathlib import Path
import sys
import time
import json

RAIZ=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(RAIZ))
import tkinter as tk
from tkinter import ttk,messagebox
import ttkbootstrap as tb
from ui.interfaz import _tabla
from inventory.mapa_almacen import MapaAlmacenUI,ubicaciones_producto
from ui.ui_theme import configurar_estilos,crear_pagina
from tools.verificacion_ui.qa_imagen_ui import capturar

errores=[]
messagebox.showerror=lambda titulo,mensaje,**kwargs:errores.append(str(titulo)+': '+str(mensaje))
root=tb.Window(themename='flatly')
root.geometry('1250x950+0+0')
configurar_estilos(root)
root.report_callback_exception=lambda tipo,exc,tb:errores.append(str(exc))
notebook=ttk.Notebook(root);notebook.pack(fill='both',expand=True)
pagina=crear_pagina(notebook);notebook.add(pagina.pagina,text='Mapa del almacén')
vista=MapaAlmacenUI(pagina,root,_tabla)
try:
    root.update()
    assert len(vista.datos)==12
    assert len(vista.tarjetas_estantes)==6
    assert len(vista.espacios)==24
    assert all(u['productos']==2 for u in vista.datos)
    # Comprobar el espacio de un producto agotado y la búsqueda de otro registrado.
    assert ubicaciones_producto(4)[0]['cantidad']==0
    assert vista.mostrar_producto_en_mapa(1)
    assert vista.resaltados=={ubicaciones_producto(1)[0]['id_ubicacion']}
    vista.resaltados.clear();vista.refrescar();root.update()
    assert vista.mostrar_ubicacion(vista.datos[0]['id_ubicacion'])
    assert len(vista.tabla.get_children())==2
    vista.seleccion=None;vista.refrescar();root.update()
    for _ in range(15):root.update();time.sleep(.04)
    print(json.dumps([{'texto':w.cget('text').splitlines()[0],'x':w.winfo_rootx(),'ancho':w.winfo_width(),'requerido':w.winfo_reqwidth(),'wrap':w.cget('wraplength')} for w in vista.espacios[:4]],ensure_ascii=False))
    assert not errores,errores
    capturar(root,(Path(__file__).resolve().parents[2] / 'verificacion_ui')/'mapa_estantes.png')
    print('Mapa: 6 estantes, 12 niveles, 24 posiciones. Búsqueda, agotados y detalle correctos.')
finally:
    root.destroy()
