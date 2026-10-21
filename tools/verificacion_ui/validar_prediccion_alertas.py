"""Comprobar el botón Predecir con SQL real, sin modificar historial ni catálogo."""
from pathlib import Path
import runpy
import sys
from unittest.mock import patch
import tkinter as tk
from tkinter import ttk,messagebox

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from ui import interfaz
from ai.anomalies import deteccion_anomalias
from core.database import conectar
from ai.prediction.prediccion_stock import predecir_agotamiento

errores=[]


def widgets(root):
    for w in root.winfo_children():
        yield w
        yield from widgets(w)


def recorrer(root,*args,**kwargs):
    root.report_callback_exception=lambda tipo,exc,tb:errores.append(str(exc))
    try:
        root.update()
        notebook=next(w for w in widgets(root) if isinstance(w,ttk.Notebook))
        pagina=next(p for p in notebook.tabs() if notebook.tab(p,'text')=='Análisis IA')
        notebook.select(pagina);root.update()
        marco=next(w for w in widgets(root) if isinstance(w,ttk.LabelFrame) and w.cget('text')=='Predicción de agotamiento')
        selector=next(w for w in marco.winfo_children() if isinstance(w,ttk.Combobox))
        selector.set(next(v for v in selector.cget('values') if v.startswith('REP-001 -')))
        boton=next(w for w in marco.winfo_children() if isinstance(w,ttk.Button) and w.cget('text')=='Predecir')
        boton.invoke();root.update()
        textos=[w.cget('text') for w in marco.winfo_children() if isinstance(w,ttk.Label)]
        assert any('Filtro de aceite' in t and ('Datos insuficientes' in t or 'Consumo promedio:' in t) for t in textos),textos
        assert not errores,errores
        print('Análisis IA: Predecir muestra el resultado real sin errores de tipo de alerta.')
    finally:
        interfaz.cerrar_audio();root.destroy()


if __name__=='__main__':
    # El producto seleccionado no requiere una nueva alerta de agotamiento próximo.
    prediccion=predecir_agotamiento(1,actualizar_alertas=False)
    assert not prediccion['datos_suficientes'] or prediccion['dias_restantes_promedio'] is None or prediccion['dias_restantes_promedio']>7
    c=conectar();antes=c.cursor().execute('SELECT COUNT(*) FROM alertas').fetchone()[0];c.close()
    with patch.object(deteccion_anomalias,'guardar_hallazgos',return_value=None), \
         patch.object(interfaz,'precalentar_voz',return_value=None), \
         patch.object(messagebox,'showerror',side_effect=lambda titulo,mensaje,**k:errores.append(str(mensaje))), \
         patch.object(tk.Misc,'mainloop',recorrer):
        runpy.run_path('main.py',run_name='__main__')
    c=conectar();despues=c.cursor().execute('SELECT COUNT(*) FROM alertas').fetchone()[0];c.close()
    assert antes==despues
    print('Alertas conservadas:',despues)
