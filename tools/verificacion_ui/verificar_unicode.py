"""Revisión Unicode con SQL de solo lectura, sin Telegram, voz ni cámaras."""
import json
from pathlib import Path
import re
import sys
import time

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))
DESTINO = BASE / 'outputs/codificacion'
DESTINO.mkdir(parents=True, exist_ok=True)

from tools.verificar_codificacion import problemas_texto
from core import database

conectar_original = database.conectar


class CursorLectura:
    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, sentencia, *args):
        # Rechazar escritura antes de enviarla; no depende de rollback posterior.
        limpio = re.sub(r"N?'(?:''|[^'])*'|--[^\n]*|/\*.*?\*/|\[[^\]]*\]", '', sentencia, flags=re.S)
        if re.search(r'\b(INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE|EXEC|EXECUTE|INTO)\b', limpio, re.I):
            raise RuntimeError('La revisión Unicode solo permite consultas de lectura.')
        self.cursor.execute(sentencia, *args)
        return self

    def executemany(self, *args):
        raise RuntimeError('Escritura deshabilitada en la revisión Unicode.')

    def __getattr__(self, nombre):
        return getattr(self.cursor, nombre)

    def __iter__(self):
        return iter(self.cursor)


class ConexionLectura:
    def __init__(self, conexion):
        self.conexion = conexion

    def cursor(self):
        return CursorLectura(self.conexion.cursor())

    def commit(self):
        raise RuntimeError('Confirmación de escritura deshabilitada.')

    def __getattr__(self, nombre):
        return getattr(self.conexion, nombre)


database.conectar = lambda: ConexionLectura(conectar_original())


def verificar_sql():
    resultado = {'columnas': [], 'hallazgos': [], 'filas_texto_revisadas': 0}
    conexion = database.conectar()
    try:
        cursor = conexion.cursor()
        cadena = 'Automática, Cámara, Predicción, Anomalía, Configuración, ü, ñ, ¿, ¡'
        cursor.execute('SELECT CAST(? AS NVARCHAR(200))', cadena)
        resultado['parametro_unicode_correcto'] = cursor.fetchone()[0] == cadena
        cursor.execute("""SELECT s.name,t.name,c.name,y.name FROM sys.tables t
            JOIN sys.schemas s ON s.schema_id=t.schema_id
            JOIN sys.columns c ON c.object_id=t.object_id
            JOIN sys.types y ON y.user_type_id=c.user_type_id
            WHERE t.is_ms_shipped=0 AND y.name IN ('varchar','nvarchar','char','nchar','text','ntext')""")
        columnas = list(cursor.fetchall())
        for esquema, tabla, columna, tipo in columnas:
            resultado['columnas'].append({'tabla': esquema + '.' + tabla, 'columna': columna, 'tipo': tipo})
            q = lambda v: '[' + v.replace(']', ']]') + ']'
            cursor.execute('SELECT ' + q(columna) + ' FROM ' + q(esquema) + '.' + q(tabla)
                           + ' WHERE ' + q(columna) + ' IS NOT NULL')
            cantidad = 0
            for fila in cursor:
                resultado['filas_texto_revisadas'] += 1
                if problemas_texto(str(fila[0])):
                    cantidad += 1
            if cantidad:
                resultado['hallazgos'].append({'tabla': tabla, 'columna': columna, 'filas': cantidad})
        resultado['correcto'] = resultado['parametro_unicode_correcto'] and not resultado['hallazgos']
    finally:
        conexion.close()
    (DESTINO / 'sql_unicode.json').write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding='utf-8')
    print('SQL:', resultado['correcto'], 'columnas:', len(resultado['columnas']), flush=True)


def verificar_ui():
    # Aplicar bloqueos antes de importar la interfaz y sus referencias locales.
    from integrations.telegram import telegram_service
    from integrations.telegram import telegram_bot_service
    telegram_service.servicio_telegram.iniciar = lambda: None
    telegram_bot_service.servicio_bot_telegram.iniciar = lambda: None
    telegram_service.servicio_telegram.publicar = lambda *a, **k: None
    from inventory import lotes_service
    lotes_service.refrescar_vencimientos = lambda *a, **k: None
    from jarvis import asistente_voz
    asistente_voz.precalentar_voz = lambda: None
    import tkinter as tk
    from tkinter import ttk, messagebox
    from ui import interfaz
    from core.automatizacion_inventario import automatizacion
    automatizacion.iniciar=lambda:None
    from tools.verificacion_ui.qa_imagen_ui import capturar
    resultado = {'pantallas': [], 'hallazgos': [], 'errores': [], 'capturas': []}
    messagebox.showerror = lambda *a, **k: resultado['errores'].append(str(a))

    def descendientes(w):
        yield w
        for hijo in w.winfo_children():
            yield from descendientes(hijo)

    def esperar(root, segundos):
        fin = time.monotonic() + segundos
        while time.monotonic() < fin:
            root.update()
            time.sleep(.025)

    def revisar(root):
        root.report_callback_exception = lambda t, v, b: resultado['errores'].append(str(v))
        root.geometry('1366x768+0+0')
        esperar(root, 3)
        nb = next(w for w in descendientes(root) if isinstance(w, ttk.Notebook)
                  and w.cget('style') == 'Workspace.TNotebook')
        for i, pagina in enumerate(nb.tabs()):
            nb.select(pagina)
            esperar(root, 1.5)
            titulo = nb.tab(pagina, 'text')
            textos = []
            for w in descendientes(root.nametowidget(pagina)):
                for opcion in ('text', 'values'):
                    try:
                        textos.append(str(w.cget(opcion)))
                    except tk.TclError:
                        pass
                if isinstance(w, ttk.Treeview):
                    textos.extend(str(w.heading(c, 'text')) for c in w['columns'])
                    textos.extend(str(w.item(f, 'values')) for f in w.get_children())
                if isinstance(w, tk.Text):
                    textos.append(w.get('1.0', 'end'))
                if isinstance(w, tk.Canvas):
                    textos.extend(w.itemcget(item, 'text') for item in w.find_all() if w.type(item) == 'text')
            resultado['pantallas'].append({'nombre': titulo, 'textos_revisados': len(textos)})
            for texto in textos:
                motivos = problemas_texto(texto)
                if motivos:
                    resultado['hallazgos'].append({'pantalla': titulo, 'motivos': motivos})
            try:
                archivo = DESTINO / f'ui_{i:02}.png'
                capturar(root, archivo)
                resultado['capturas'].append(archivo.name)
            except RuntimeError as error:
                resultado['errores'].append(str(error))
            if titulo == 'Configuración':
                for interior in descendientes(root.nametowidget(pagina)):
                    if isinstance(interior, ttk.Notebook):
                        for subpagina in interior.tabs():
                            interior.select(subpagina)
                            esperar(root, .15)
                            if interior.tab(subpagina, 'text') == 'JARVIS':
                                capturar(root, DESTINO / 'configuracion_jarvis.png')
        resultado['correcto'] = not resultado['hallazgos'] and not resultado['errores']
        (DESTINO / 'interfaz_unicode.json').write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding='utf-8')
        print('UI:', json.dumps(resultado, ensure_ascii=False), flush=True)
        root.tk.call(root.protocol('WM_DELETE_WINDOW'))
        try:
            if root.winfo_exists():
                esperar(root, .2)
        except tk.TclError:
            pass  # El cierre normal puede haber destruido Tcl inmediatamente.

    tk.Misc.mainloop = revisar
    interfaz.iniciar_aplicacion()


if __name__ == '__main__':
    verificar_sql()
    if '--sql' not in sys.argv:
        verificar_ui()
