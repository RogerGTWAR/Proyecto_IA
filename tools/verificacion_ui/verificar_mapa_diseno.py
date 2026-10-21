"""Revisa el mapa con datos SQL de lectura y LEDs en simulación aislada."""
import ast
import hashlib
from copy import deepcopy
import json
from pathlib import Path
import sys
import time

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))
from tools.verificacion_ui.verificar_unicode import ConexionLectura  # Bloquea DML y DDL.
import tkinter as tk
from tkinter import ttk, messagebox
from ui.ui_theme import configurar_estilos, crear_pagina, marco_visual, etiqueta_visual
from tools.verificacion_ui.qa_imagen_ui import capturar
from core.config_manager import DEFAULTS
from integrations.arduino import led_service
cfg = deepcopy(DEFAULTS['arduino'])
cfg['modo'] = 'simulacion'
led_service.servicio_led = led_service.ServicioLED(lambda: cfg)
from inventory.mapa_almacen import MapaAlmacenUI, numero_led

DESTINO = BASE / 'outputs/mapa_compacto' / ('anterior' if '--anterior' in sys.argv else 'actual')
DESTINO.mkdir(parents=True, exist_ok=True)
if '--anterior' in sys.argv:
    import importlib.util
    spec = importlib.util.spec_from_file_location('mapa_previo', BASE / 'outputs/mapa_compacto/mapa_previo.py')
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    MapaAlmacenUI = modulo.MapaAlmacenUI
resultado = {'resoluciones': [], 'errores': [], 'comprobaciones': []}
messagebox.showerror = lambda *a, **k: resultado['errores'].append(str(a))


def esperar(root, segundos=.3):
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        root.update()
        time.sleep(.02)


def comprobar(nombre, condicion):
    resultado['comprobaciones'].append({'nombre': nombre, 'correcto': bool(condicion)})
    if not condicion:
        raise AssertionError(nombre)


def main():
    import ttkbootstrap as tb
    root = tb.Window(themename='flatly')
    root.overrideredirect(True)
    root.report_callback_exception = lambda t, v, b: resultado['errores'].append(str(v))
    configurar_estilos(root)
    etiqueta_visual(root, text='Sistema Inteligente de Inventario', bg='#16324F', fg='white',
             font=('Segoe UI', 16, 'bold'), anchor='w', padx=24, pady=20).pack(fill='x')
    cuerpo = ttk.Frame(root, style='App.TFrame')
    cuerpo.pack(fill='both', expand=True)
    lateral = marco_visual(cuerpo, bg='#16324F', width=200)
    lateral.pack(side='left', fill='y'); lateral.pack_propagate(False)
    etiqueta_visual(lateral, text='INVENTARIO IA\n\nMapa del almacén', bg='#16324F', fg='white',
             font=('Segoe UI', 10, 'bold'), justify='left', padx=14, pady=24).pack(anchor='w')
    notebook = ttk.Notebook(cuerpo, style='Workspace.TNotebook')
    notebook.pack(side='left', fill='both', expand=True)
    pagina = crear_pagina(notebook)
    notebook.add(pagina.pagina, text='Mapa')
    vistos = []
    mapa = MapaAlmacenUI(pagina, root, None, ver_producto=vistos.append)
    try:
        esperar(root)
        comprobar('24 posiciones y seis estantes SQL', len(mapa.espacios) == 24 and len(mapa.tarjetas_estantes) == 6)
        comprobar('Mapeo LED 1 a 24 intacto', sorted(t.led_numero for t in mapa.espacios) == list(range(1, 25)))
        actual = ast.parse((BASE / 'inventory/mapa_almacen.py').read_text(encoding='utf-8'))
        consultas = '\n'.join(ast.dump(n) for n in actual.body if isinstance(n, ast.FunctionDef))
        comprobar('Funciones de consulta intactas',
                  hashlib.sha256(consultas.encode('utf-8')).hexdigest() ==
                  '73370490f101d0e3a99d423460f8d929d82259cb9d7a9edeeb2f8e37cb0425c6')
        for ancho, alto in ((1366, 768), (1600, 900), (1920, 1080)):
            root.geometry(f'{ancho}x{alto}+0+0')
            mapa.seleccion = mapa.posicion_led = None
            mapa.busqueda.delete(0, 'end'); mapa.resaltados.clear(); mapa.refrescar()
            esperar(root, .5)
            comprobar(f'Tres columnas a {ancho}', [t.grid_info()['column'] for t in mapa.tarjetas_estantes] == [0, 1, 2, 0, 1, 2])
            comprobar(f'Detalle lateral a {ancho}', mapa.panel_detalle.grid_info()['column'] == 1)
            anchos = [t.winfo_width() for t in mapa.tarjetas_estantes]
            comprobar(f'Estantes de igual ancho a {ancho}', max(anchos)-min(anchos) <= 1)
            alturas = [t.winfo_height() for t in mapa.tarjetas_estantes]
            comprobar(f'Estantes de igual alto a {ancho}', max(alturas)-min(alturas) <= 1)
            comprobar(f'Tarjetas legibles a {ancho}', min(t.winfo_width() for t in mapa.espacios) >= 105)
            registro = {'ancho': ancho, 'alto': alto, 'ancho_tarjeta': min(t.winfo_width() for t in mapa.espacios),
                        'alto_tarjeta': max(t.winfo_height() for t in mapa.espacios),
                        'alto_estante': max(alturas), 'alto_contenido': pagina.winfo_reqheight(),
                        'alto_visible': pagina.master.winfo_height(),
                        'estantes': anchos, 'detalle': mapa.panel_detalle.winfo_width()}
            pagina.master.yview_moveto(0); esperar(root)
            registro['seis_estantes_visibles'] = all(
                t.winfo_rooty()+t.winfo_height() <= pagina.master.winfo_rooty()+pagina.master.winfo_height()
                for t in mapa.tarjetas_estantes)
            registro['sin_desbordamiento_horizontal'] = all(
                w.winfo_rootx()+w.winfo_width() <= root.winfo_rootx()+root.winfo_width()
                for w in mapa.espacios+[mapa.panel_detalle])
            registro['sin_scroll_vertical'] = pagina.winfo_reqheight() <= pagina.master.winfo_height()
            if '--anterior' not in sys.argv:
                comprobar(f'Sin desbordamiento horizontal a {ancho}', registro['sin_desbordamiento_horizontal'])
                if ancho == 1920:
                    comprobar('Seis estantes visibles sin scroll en 1920', registro['seis_estantes_visibles'])
                    comprobar('Página sin scroll vertical en 1920', registro['sin_scroll_vertical'])
            if ancho <= root.winfo_screenwidth() and alto <= root.winfo_screenheight():
                pagina.master.yview_moveto(0); esperar(root)
                capturar(root, DESTINO / f'{ancho}_mapa.png')
                pagina.master.yview_moveto(1); esperar(root)
                capturar(root, DESTINO / f'{ancho}_mapa_inferior.png')
            resultado['resoluciones'].append(registro)
        root.geometry('1366x768+0+0'); esperar(root)
        producto = next((p for p in mapa.contenido if p['nombre'] == 'Tornillo M8'), mapa.contenido[0])
        mapa.busqueda.insert(0, producto['nombre']); mapa.buscar(); esperar(root)
        comprobar('Búsqueda selecciona el producto correcto', mapa.producto_seleccionado == producto['id_producto'])
        comprobar('Una sola posición seleccionada', sum((t.uid, t.posicion) == mapa.posicion_led for t in mapa.espacios) == 1)
        comprobar('Detalle visible junto al producto encontrado',
                  pagina.master.winfo_rooty() <= mapa.panel_detalle.winfo_rooty() < pagina.master.winfo_rooty()+pagina.master.winfo_height())
        mapa.abrir_producto(); comprobar('Ver producto reutiliza callback', vistos == [producto['id_producto']])
        capturar(root, DESTINO / '1366_busqueda.png')
        mapa.encender_seleccion(); esperar(root, .6)
        comprobar('Encendido en simulación', mapa.boton_led.cget('text').startswith('Apagar LED'))
        capturar(root, DESTINO / '1366_led_encendido.png')
        mapa.encender_seleccion(); esperar(root, .6)
        comprobar('Apagado individual', mapa.boton_led.cget('text').startswith('Encender LED'))
        mapa.mostrar_producto_en_mapa(producto['id_producto']); esperar(root)
        comprobar('Entrada desde JARVIS selecciona producto', mapa.producto_seleccionado == producto['id_producto'])
        mapa.mostrar_ubicacion(producto['id_ubicacion']); esperar(root)
        comprobar('Nivel muestra ambas posiciones sin selección individual', mapa.posicion_led is None)
        capturar(root, DESTINO / '1366_nivel.png')
        mapa.busqueda.delete(0, 'end'); mapa.busqueda.insert(0, 'ZZZ9999999999'); mapa.buscar(); esperar(root)
        comprobar('Sin coincidencias no conserva selección', mapa.posicion_led is None and 'No se encontró' in mapa.resumen.cget('text'))
        comprobar('Sin errores de interfaz', not resultado['errores'])
    finally:
        resultado['correcto'] = not resultado['errores'] and all(c['correcto'] for c in resultado['comprobaciones'])
        (DESTINO / 'verificacion.json').write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding='utf-8')
        root.destroy()
    print(json.dumps(resultado, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
