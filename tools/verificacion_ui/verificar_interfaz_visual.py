"""QA de presentación con SQL real; abre formularios sin guardar registros."""
import json
import traceback
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from PIL import ImageGrab
import ctypes
from ctypes import wintypes
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from ui import interfaz
from ui.ui_theme import Navegacion, ChatConversacion
from ui.ventanas_camara import VentanaCamara

DESTINO=(Path(__file__).resolve().parents[2] / 'verificacion_ui')
DESTINO.mkdir(exist_ok=True)
informe={"pantallas":[],"modales":[],"errores":[],"controles_recortados":[]}
original=interfaz.tb.Window if interfaz.tb else tk.Tk

def todos(widget):
    for hijo in widget.winfo_children():
        yield hijo
        yield from todos(hijo)

def captura(root,nombre):
    """Captura solo el área propia, comprobando que no esté cubierta por otra app."""
    root.update_idletasks(); anterior=root.attributes('-topmost')
    try:
        root.attributes('-topmost',True); root.update(); time.sleep(.15); root.update()
        x,y=root.winfo_rootx(),root.winfo_rooty(); ancho,alto=root.winfo_width(),root.winfo_height()
        user=ctypes.windll.user32
        user.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT]; user.GetAncestor.restype=wintypes.HWND
        user.WindowFromPoint.argtypes=[wintypes.POINT]; user.WindowFromPoint.restype=wintypes.HWND
        propio=user.GetAncestor(root.winfo_id(),2)
        for px in (x+2,x+ancho//2,x+ancho-3):
            for py in (y+2,y+alto//2,y+alto-3):
                ventana=user.WindowFromPoint(wintypes.POINT(px,py))
                if user.GetAncestor(ventana,2)!=propio:
                    raise RuntimeError('Captura omitida: otra ventana cubre el área de la aplicación')
        ImageGrab.grab(bbox=(x,y,x+ancho,y+alto)).save(DESTINO/(nombre+'.png'))
    finally:
        root.attributes('-topmost',anterior)


def crear(*args,**kwargs):
    root=original(*args,**kwargs)
    def error_callback(tipo,error,tb):
        informe['errores'].append(''.join(traceback.format_exception(tipo,error,tb)))
    root.report_callback_exception=error_callback
    def verificar():
        try:
            nav=next(w for w in todos(root) if isinstance(w,Navegacion))
            resumen=next(w.dashboard for w in todos(root) if hasattr(w,'dashboard'))
            limite=time.monotonic()+10
            while resumen.cargando and time.monotonic()<limite:
                root.update(); time.sleep(.05)
            informe['dashboard']={'kpi':{k:v.get() for k,v in resumen.valores.items()},'base':resumen.estado_base.get()}
            for ancho,alto in ((1366,768),(1920,1080),(1100,650)):
                root.geometry(f'{ancho}x{alto}+0+0'); root.update()
                for indice,pagina in enumerate(nav.notebook.tabs()):
                    nav.notebook.select(pagina); root.update()
                    titulo=nav.notebook.tab(pagina,'text')
                    informe['pantallas'].append({'modulo':titulo,'solicitado':[ancho,alto],'real':[root.winfo_width(),root.winfo_height()]})
                    for w in todos(root.nametowidget(pagina)):
                        if isinstance(w,(ttk.Button,tk.Button)) and w.winfo_ismapped() and w.winfo_width()<w.winfo_reqwidth()-2:
                            informe['controles_recortados'].append({'modulo':titulo,'resolucion':[ancho,alto],'texto':w.cget('text'),'ancho':w.winfo_width(),'requerido':w.winfo_reqwidth()})
                    if ancho==1366: captura(root,'modulo_'+str(indice))
                    if ancho==1100 and indice in (0,4,6): captura(root,'minimo_'+str(indice))
            root.geometry('1366x768+0+0'); root.update()
            # Comprobar datos visibles y todas las categorías de configuración.
            nav.notebook.select(next(p for p in nav.notebook.tabs() if nav.notebook.tab(p,'text')=='Reportes')); root.update()
            previa=next(w for w in todos(root.nametowidget(nav.notebook.select())) if isinstance(w,ttk.Button) and w.cget('text')=='Vista previa')
            previa.invoke(); limite=time.monotonic()+8
            while time.monotonic()<limite:
                root.update(); time.sleep(.05)
                tablas=[w for w in todos(root.nametowidget(nav.notebook.select())) if isinstance(w,ttk.Treeview)]
                if tablas and tablas[0].get_children(): break
            if not tablas or not tablas[0].get_children(): informe['errores'].append('La vista previa del inventario no cargó los productos reales')
            captura(root,'reportes_vista_previa')
            nav.notebook.select(next(p for p in nav.notebook.tabs() if nav.notebook.tab(p,'text')=='Configuración')); root.update()
            categorias=next(w for w in todos(root.nametowidget(nav.notebook.select())) if isinstance(w,ttk.Notebook))
            for indice,p in enumerate(categorias.tabs()):
                categorias.select(p); root.update(); captura(root,'configuracion_'+str(indice))
            categorias.select(categorias.tabs()[0])
            nav.notebook.select(nav.notebook.tabs()[0]); root.update()
            pagina=root.nametowidget(nav.notebook.tabs()[0])
            canvas=next(w for w in pagina.winfo_children() if isinstance(w,tk.Canvas))
            canvas.yview_moveto(.30); root.update(); captura(root,'dashboard_secciones')
            canvas.yview_moveto(.70); root.update(); captura(root,'dashboard_actividad')
            canvas.yview_moveto(0)
            chat=next(w for w in todos(root) if isinstance(w,ChatConversacion))
            chat.agregar('Tú','¿Dónde están los tornillos?')
            chat.agregar('JARVIS','Mensaje de prueba visual. Las respuestas operativas mantienen el agente existente.')
            nav.notebook.select(next(p for p in nav.notebook.tabs() if nav.notebook.tab(p,"text")=="JARVIS")); root.update(); captura(root,'jarvis_mensajes')
            responder=next(w for w in todos(root) if isinstance(w,ttk.Checkbutton) and w.cget('text')=='Responder con voz')
            responder.invoke()
            pagina_jarvis=next(p for p in nav.notebook.tabs() if nav.notebook.tab(p,'text')=='JARVIS')
            entrada=next(w for w in todos(root.nametowidget(pagina_jarvis)) if isinstance(w,ttk.Entry))
            enviar=next(w for w in todos(root) if isinstance(w,ttk.Button) and w.cget('text')=='Enviar')
            producto=interfaz.buscar_productos('motor')[0]
            # Ahora puede haber varios motores: resolver el código único, sin asumir identidad.
            entrada.delete(0,'end'); entrada.insert(0,'¿Cuántos '+producto['codigo']+' quedan?')
            esperado=f"{producto['nombre']}: {float(producto['stock_actual']):g}"
            enviar.invoke()
            limite=time.monotonic()+8
            while time.monotonic()<limite:
                root.update(); time.sleep(.05)
                if any(esperado in label.cget('text') for label in chat.etiquetas): break
            informe['jarvis_consulta_real']=any(esperado in label.cget('text') for label in chat.etiquetas)
            informe['jarvis_respuesta']=next((label.cget('text') for label in chat.etiquetas if esperado in label.cget('text')),None)
            if not informe['jarvis_consulta_real']: informe['errores'].append('La consulta real de JARVIS no apareció en el chat')
            captura(root,'jarvis_consulta_real')
            # Verificar la acción real del asistente, además del texto del chat.
            from inventory.mapa_almacen import ubicaciones_producto
            esperadas=ubicaciones_producto(producto['id_producto'])
            entrada.delete(0,'end'); entrada.insert(0,'¿Dónde está?'); enviar.invoke()
            limite=time.monotonic()+8
            while time.monotonic()<limite:
                root.update(); time.sleep(.05)
                if nav.notebook.tab(nav.notebook.select(),'text')=='Mapa': break
            if nav.notebook.tab(nav.notebook.select(),'text')!='Mapa': informe['errores'].append('JARVIS no abrió el mapa')
            pagina= root.nametowidget(nav.notebook.select())
            tarjetas=[w.cget('text') for w in todos(pagina) if isinstance(w,tk.Button)]
            for u in esperadas:
                if not any(u['codigo_ubicacion'] in t and 'ENCONTRADA' in t for t in tarjetas): informe['errores'].append('La ubicación del producto no quedó resaltada')
            captura(root,'jarvis_mapa_real')
            nav.notebook.select(pagina_jarvis); root.update()
            entrada.delete(0,'end'); entrada.insert(0,'¿Cuánto tiempo durará?'); enviar.invoke()
            limite=time.monotonic()+8
            while time.monotonic()<limite:
                root.update(); time.sleep(.05)
                if any('Datos insuficientes' in w.cget('text') or 'podría durar' in w.cget('text') for w in chat.etiquetas): break
            if not any('Datos insuficientes' in w.cget('text') or 'podría durar' in w.cget('text') for w in chat.etiquetas): informe['errores'].append('El seguimiento de predicción no respondió')
            captura(root,'jarvis_prediccion_contextual')
            escenarios=[('Dashboard','Nuevo producto'),('Dashboard','Registrar entrada'),('Dashboard','Registrar salida'),('Productos','+ Nuevo producto'),('Productos','Editar'),('Productos','Ficha'),('Productos','Categorías'),('Productos','Unidades'),('Productos','Ubicaciones'),('Productos','Motivos'),('Productos','Análisis de rotación'),('Movimientos','Registrar entrada'),('Movimientos','Registrar salida'),('Movimientos','Transferir producto'),('Movimientos','Ajuste de inventario'),('Empleados','Nuevo empleado'),('Empleados','Editar')]
            for modulo,texto in escenarios:
                indice=next(i for i,p in enumerate(nav.notebook.tabs()) if nav.notebook.tab(p,'text')==modulo)
                nav.notebook.select(nav.notebook.tabs()[indice]); root.update()
                boton=next(w for w in todos(root.nametowidget(nav.notebook.tabs()[indice])) if isinstance(w,ttk.Button) and w.cget('text')==texto)
                if texto in {'Editar','Ficha'}:
                    tabla=next(w for w in todos(root.nametowidget(nav.notebook.tabs()[indice])) if isinstance(w,ttk.Treeview))
                    tabla.selection_set(tabla.get_children()[0])
                boton.invoke(); root.update()
                modales=[w for w in root.winfo_children() if isinstance(w,tk.Toplevel)]
                for modal in modales:
                    informe['modales'].append({'accion':texto,'titulo':modal.title(),'tamano':[modal.winfo_width(),modal.winfo_height()]})
                    for w in todos(modal):
                        if isinstance(w,ttk.Button) and (not w.winfo_ismapped() or w.winfo_rooty()+w.winfo_height()>modal.winfo_rooty()+modal.winfo_height()):
                            informe['controles_recortados'].append({'modal':modal.title(),'texto':w.cget('text')})
                    captura(modal,'modal_'+str(len(informe['modales'])))
                    modal.destroy()
            camara=VentanaCamara(root,'escaner','Prueba visual',lambda _:None)
            root.update(); captura(camara.ventana,'camara'); camara.cerrar()
            informe['tablas']=[{'filas':len(w.get_children()),'columnas':list(w.cget('columns'))} for w in todos(root) if isinstance(w,ttk.Treeview)]
            print(json.dumps(informe,ensure_ascii=False,indent=2),flush=True)
        except Exception:
            informe['errores'].append(traceback.format_exc()); print(informe['errores'][-1],flush=True)
        finally:
            (DESTINO/'resultado.json').write_text(json.dumps(informe,ensure_ascii=False,indent=2),encoding='utf-8')
            cierre=root.protocol('WM_DELETE_WINDOW')
            if cierre: root.tk.call(cierre)
            else: root.destroy()
    root.after(2200,verificar)
    return root

if interfaz.tb: interfaz.tb.Window=crear
else: interfaz.tk.Tk=crear
interfaz.messagebox.showerror=lambda titulo,mensaje,**kwargs: informe['errores'].append(f'{titulo}: {mensaje}')
interfaz.iniciar_aplicacion()
if informe['errores'] or informe['controles_recortados']:
    raise SystemExit(1)
print('VERIFICACION_VISUAL_OK')
