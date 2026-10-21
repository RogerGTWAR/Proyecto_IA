"""Recorrido de escritorio con consultas SQL, sin registrar movimientos ni hallazgos."""
from pathlib import Path
import runpy
import sys
import time
import traceback
from unittest.mock import patch
import tkinter as tk
from tkinter import ttk, messagebox

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ui import interfaz
from ai.anomalies import deteccion_anomalias
from ui.inventario_ui import InventarioUI
from ui.prediccion_ui import PrediccionUI

inventarios = []
predicciones = []
errores = []
refrescar_original = InventarioUI.refrescar
cargar_original = PrediccionUI.cargar


def refrescar(self, *args, **kwargs):
    if self not in inventarios:
        inventarios.append(self)
    return refrescar_original(self, *args, **kwargs)


def cargar(self, *args, **kwargs):
    if self not in predicciones:
        predicciones.append(self)
    return cargar_original(self, *args, **kwargs)


def widgets(root):
    for hijo in root.winfo_children():
        yield hijo
        yield from widgets(hijo)


def error_dialogo(titulo, mensaje, **kwargs):
    errores.append(str(titulo) + ': ' + str(mensaje))


def recorrer(root, *args, **kwargs):
    root.report_callback_exception = lambda tipo, exc, tb: errores.append(
        ''.join(traceback.format_exception(tipo, exc, tb)))
    try:
        limite = time.monotonic() + 8
        while time.monotonic() < limite:
            root.update()
            time.sleep(.04)
        for notebook in (w for w in widgets(root) if isinstance(w, ttk.Notebook)):
            for pagina in notebook.tabs():
                notebook.select(pagina)
                root.update()
                print('Pantalla:', notebook.tab(pagina, 'text'), flush=True)
        for vista in inventarios:
            for _ in range(3):
                vista.refrescar()
            print('Inventario:', len(vista.tabla.get_children()),
                  'filas; KPI:', {k: v.get() for k, v in vista.kpis.items()}, flush=True)
        for vista in predicciones:
            for _ in range(3):
                vista.cargar()
            print('Predicción:', len(vista.t.get_children()), 'filas', flush=True)
        root.update()
        tablas = [w for w in widgets(root) if isinstance(w, ttk.Treeview)]
        assert tablas, 'No se construyeron tablas.'
        for tabla in tablas:
            assert 'insert' not in tabla.__dict__, 'Insert reemplazado en una tabla.'
            assert tabla.insert.__func__ is ttk.Treeview.insert
        assert inventarios and inventarios[0].tabla.get_children(), 'Inventario sin filas.'
        assert predicciones and predicciones[0].t.get_children(), 'Predicción sin filas.'
        assert not errores, '\n'.join(errores)
        print('Validación completa:', len(tablas), 'tablas sin wrappers ni errores.', flush=True)
    finally:
        interfaz.cerrar_audio()
        root.destroy()


if __name__ == '__main__':
    # Evitar escritura de hallazgos y precalentamiento de audio durante el recorrido.
    with patch.object(deteccion_anomalias, 'guardar_hallazgos', return_value=None), \
         patch.object(interfaz, 'precalentar_voz', return_value=None), \
         patch.object(InventarioUI, 'refrescar', refrescar), \
         patch.object(PrediccionUI, 'cargar', cargar), \
         patch.object(messagebox, 'showerror', error_dialogo), \
         patch.object(tk.Misc, 'mainloop', recorrer):
        runpy.run_path('main.py', run_name='__main__')
