"""Navegación visual con SQL de lectura; sin audio, envíos ni dispositivos."""
from pathlib import Path
import json
import sys
import time
from unittest.mock import patch

BASE=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(BASE))
from tools.verificacion_ui.verificar_unicode import ConexionLectura,conectar_original
from core import database
database.conectar=lambda:ConexionLectura(conectar_original())
import tkinter as tk
from tkinter import ttk,messagebox
from ui import interfaz
from core import event_subscribers
from integrations.telegram import telegram_service
from integrations.telegram import telegram_bot_service
from core import health_monitor
from inventory import lotes_service
from core.automatizacion_inventario import automatizacion
from tools.verificacion_ui.qa_imagen_ui import capturar

DESTINO=BASE/'outputs'/'ux_global'
DESTINO.mkdir(parents=True,exist_ok=True)
resultado={'capturas':[],'errores':[],'resoluciones':[],'alcance':'SQL de lectura; sin envíos, audio, hardware ni cambios de registros.'}


def recorrer(w):
    yield w
    for hijo in w.winfo_children():yield from recorrer(hijo)


def esperar(root,segundos):
    fin=time.monotonic()+segundos
    while time.monotonic()<fin:root.update();time.sleep(.025)


def revisar(root):
    root.report_callback_exception=lambda t,e,b:resultado['errores'].append(str(e))
    root.overrideredirect(True)
    nb=next(w for w in recorrer(root) if isinstance(w,ttk.Notebook) and w.cget('style')=='Workspace.TNotebook')
    for ancho,alto in ((1366,768),(1600,900),(1920,1080)):
        root.geometry(f'{ancho}x{alto}+0+0');esperar(root,1)
        resultado['resoluciones'].append([root.winfo_width(),root.winfo_height()])
        for i,pagina in enumerate(nb.tabs()):
            nb.select(pagina);esperar(root,1.2)
            nombre=nb.tab(pagina,'text');archivo=f'{ancho}x{alto}_{i:02}.png'
            filtros_revisados=0
            for control in recorrer(root.nametowidget(pagina)):
                if isinstance(control,ttk.Combobox) and control.winfo_viewable() and control.get() in ('Todos','Todas'):
                    valores=control.cget('values')
                    if len(valores)>1:
                        previo=control.get();control.current(1);control.event_generate('<<ComboboxSelected>>');esperar(root,.2)
                        control.set(previo);control.event_generate('<<ComboboxSelected>>');esperar(root,.2)
                        filtros_revisados+=1
            tablas=[w for w in recorrer(root.nametowidget(pagina)) if isinstance(w,ttk.Treeview) and w.winfo_viewable()]
            for tabla in tablas:
                filas=tabla.get_children()
                if filas:
                    tabla.selection_set(filas[0]);tabla.event_generate('<<TreeviewSelect>>');tabla.see(filas[0])
                    tabla.yview_moveto(1);tabla.yview_moveto(0)
            esperar(root,.25)
            capturar(root,DESTINO/archivo)
            registro={'modulo':nombre,'resolucion':[ancho,alto],'archivo':archivo,
                      'tablas':len(tablas),'filtros_recorridos':filtros_revisados,
                      'filas_visibles':[len(t.get_children()) for t in tablas]}
            resultado['capturas'].append(registro)
            print(nombre,ancho,alto,flush=True)
        # Revisar también herramientas faciales y todas las páginas de configuración.
        for pagina in nb.tabs():
            if nb.tab(pagina,'text') not in ('Empleados','Configuración'):continue
            nb.select(pagina);esperar(root,.3)
            interiores=[w for w in recorrer(root.nametowidget(pagina)) if isinstance(w,ttk.Notebook)]
            for j,interior in enumerate(interiores):
                for k,sub in enumerate(interior.tabs()):
                    interior.select(sub);esperar(root,.15)
                    nombre=nb.tab(pagina,'text')+' / '+interior.tab(sub,'text')
                    archivo=f'{ancho}x{alto}_sub_{nb.index(pagina)}_{j}_{k}.png'
                    capturar(root,DESTINO/archivo)
                    resultado['capturas'].append({'modulo':nombre,'resolucion':[ancho,alto],'archivo':archivo})
                interior.select(interior.tabs()[0])
    resultado['correcto']=not resultado['errores']
    (DESTINO/'revision.json').write_text(json.dumps(resultado,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'capturas':len(resultado['capturas']),'errores':resultado['errores']},ensure_ascii=False),flush=True)
    root.destroy()


if __name__=='__main__':
    with patch.object(event_subscribers,'iniciar_eventos'), \
         patch.object(automatizacion,'iniciar'), \
         patch.object(telegram_service.servicio_telegram,'iniciar'), \
         patch.object(telegram_bot_service.servicio_bot_telegram,'iniciar'), \
         patch.object(health_monitor.health_monitor,'start'), \
         patch.object(lotes_service,'refrescar_vencimientos'), \
         patch.object(interfaz,'precalentar_voz'), \
         patch.object(messagebox,'showerror',side_effect=lambda *a,**k:resultado['errores'].append(str(a))), \
         patch.object(tk.Misc,'mainloop',revisar):
        interfaz.iniciar_aplicacion()
