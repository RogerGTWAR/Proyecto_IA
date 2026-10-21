from pathlib import Path
import sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import tkinter as tk
from tkinter import ttk
import ttkbootstrap as tb
from reportes_ui import ReportesUI
from ui_theme import configurar_estilos
from verificacion_ui.qa_imagen_ui import capturar
root=tb.Window(themename='flatly'); root.geometry('1366x768+0+0'); configurar_estilos(root)
padre=ttk.Frame(root,padding=18); padre.pack(fill='both',expand=True)
def tabla(padre,cols,titulos,anchos):
 f=ttk.Frame(padre); f.pack(fill='both',expand=True)
 t=ttk.Treeview(f,columns=cols,show='headings',height=6)
 for c,n,a in zip(cols,titulos,anchos):t.heading(c,text=n);t.column(c,width=a,minwidth=90,stretch=False)
 t.grid(row=0,column=0,sticky='nsew');f.rowconfigure(0,weight=1);f.columnconfigure(0,weight=1)
 sx=ttk.Scrollbar(f,orient='horizontal',command=t.xview);sx.grid(row=1,column=0,sticky='ew');t.configure(xscrollcommand=sx.set)
 return t
ui=ReportesUI(padre,root,tabla)
def esperar():
 limite=time.monotonic()+25
 while ui.trabajo.ocupado and time.monotonic()<limite:root.update();time.sleep(.04)
 root.update()
esperar();ui.previa();esperar();capturar(root,Path(__file__).parent/'pantalla_inventario.png')
ui.tipo.set('Resumen general');ui.cambiar();esperar();ui.previa();esperar();capturar(root,Path(__file__).parent/'pantalla_resumen.png')
print('UI OK');root.destroy()
