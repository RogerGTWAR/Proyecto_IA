"""Revisión de geometría y captura de las pantallas actuales del sistema."""
import sys,time,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import tkinter as tk
from tkinter import ttk,messagebox
from ui import interfaz
from tools.verificacion_ui.qa_imagen_ui import capturar

BASE=(Path(__file__).resolve().parents[2] / 'verificacion_ui')/'distribucion';BASE.mkdir(exist_ok=True)
errores=[]
def error(*args,**kwargs):raise RuntimeError(str(args))
messagebox.showerror=error
interfaz.precalentar_voz=lambda:None
def descendientes(w):
    yield w
    for hijo in w.winfo_children():yield from descendientes(hijo)
def esperar(root,segundos=.3):
    fin=time.monotonic()+segundos
    while time.monotonic()<fin:root.update();time.sleep(.025)
def revisar(root):
    print('Pantallas construidas; inicio de revisión.',flush=True)
    root.report_callback_exception=lambda t,v,b:errores.append(str(v))
    esperar(root,2)
    nb=next(w for w in descendientes(root) if isinstance(w,ttk.Notebook) and w.cget('style')=='Workspace.TNotebook')
    resultados=[]
    for ancho,alto in (() if '--formularios' in sys.argv else ((1366,768),(1920,1080))):
        root.geometry(f'{ancho}x{alto}+0+0');esperar(root)
        for i,p in enumerate(nb.tabs()):
            nb.select(p);esperar(root,.4)
            titulo=nb.tab(p,'text')
            if ancho<=root.winfo_screenwidth() and alto<=root.winfo_screenheight()-40:
                try:capturar(root,BASE/f'{ancho}_{i:02}.png')
                except RuntimeError:esperar(root,.4);capturar(root,BASE/f'{ancho}_{i:02}.png')
            resultados.append({'pantalla':titulo,'ancho':ancho,'alto':alto})
    # Formularios existentes: abrir y cerrar sin guardar operaciones.
    root.geometry('1366x768+0+0')
    for titulo,accion in [('Productos','+ Nuevo producto'),('Movimientos','Registrar entrada'),('Movimientos','Registrar salida'),('Movimientos','Transferir producto'),('Movimientos','Registrar ajuste'),('Empleados','Nuevo empleado')]:
        p=next(p for p in nb.tabs() if nb.tab(p,'text')==titulo);nb.select(p);esperar(root)
        boton=next(w for w in descendientes(root.nametowidget(p)) if isinstance(w,ttk.Button) and w.cget('text')==accion)
        boton.invoke();esperar(root)
        ventanas=[w for w in root.winfo_children() if isinstance(w,tk.Toplevel)]
        for ventana in ventanas:
            destino=BASE/(accion.replace(' ','_').replace('+','')+'.png')
            try:capturar(ventana,destino)
            except RuntimeError:ventana.lift();esperar(root,.4);capturar(ventana,destino)
            ventana.destroy()
    (BASE/('formularios.json' if '--formularios' in sys.argv else 'validacion.json')).write_text(json.dumps({'pantallas':resultados,'errores':errores},ensure_ascii=False,indent=2),encoding='utf-8')
    root.destroy()
    if errores:raise RuntimeError(str(errores))
    print('Distribución verificada:',len(resultados),'vistas; seis formularios; sin errores de callbacks.')
tk.Misc.mainloop=revisar
interfaz.iniciar_aplicacion()
