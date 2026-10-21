"""Regresión de inserción explícita: sin SQL, cámara ni datos persistidos."""
import ast
from decimal import Decimal
from pathlib import Path
import tkinter as tk
from tkinter import ttk, font as tkfont
import unittest
from unittest.mock import Mock

from core.formato_numerico import format_campo, format_moneda
from ui.ui_components import insertar_fila
from ui.ui_theme import COLORES, FONTS, SPACING_MD, configurar_estilos


class Insercion(unittest.TestCase):
    def test_una_insercion_y_datos_intactos(self):
        tree = Mock()
        tree.__getitem__ = Mock(return_value=('id_producto', 'cantidad', 'empleados'))
        tree.get_children.return_value = ()
        datos = (24, Decimal('3.276492'), 6)
        insertar_fila(tree, iid='24', values=datos)
        tree.insert.assert_called_once_with('', 'end', iid='24',
                                           values=(24, '3.28', 6), tags=('par',))
        self.assertEqual(datos[1], Decimal('3.276492'))

    def test_estados_y_columnas_adicionales_se_conservan(self):
        tree = Mock()
        tree.get_children.return_value = ('anterior',)
        insertar_fila(tree, values=(18.45678, 'extra'), columnas=('cantidad',),
                      tags=('CRÍTICO',))
        self.assertEqual(tree.insert.call_args.kwargs['values'], ('18.46', 'extra'))
        self.assertEqual(tree.insert.call_args.kwargs['tags'], ('CRÍTICO',))

    def test_conteos_y_moneda(self):
        for clave in ('productos', 'empleados', 'alertas', 'agotados',
                      'stock_bajo', 'cantidad_registros', 'id_producto'):
            self.assertEqual(format_campo(clave, 24), 24)
        self.assertEqual(format_campo('stock_total', Decimal('1706.000')), '1706.00')
        self.assertEqual(format_moneda(18451.5), 'C$ 18,451.50')

    def test_factory_real_repetida_sin_reemplazar_insert(self):
        # Aislar la fábrica real evita cargar audio y modelos para este contrato.
        fuente = ast.parse(Path('ui/interfaz.py').read_text(encoding='utf-8'))
        funciones = [n for n in fuente.body if isinstance(n, ast.FunctionDef)
                     and n.name in ('_tabla', 'aplicar_estilo_tabla')]
        espacio = dict(ttk=ttk, tkfont=tkfont, COLORES=COLORES,
                       FONTS=FONTS, SPACING_MD=SPACING_MD)
        exec(compile(ast.Module(body=funciones, type_ignores=[]), 'ui/interfaz.py', 'exec'), espacio)
        root = tk.Tk()
        root.withdraw()
        try:
            configurar_estilos(root)
            original = ttk.Treeview.insert
            for _ in range(3):
                padre = ttk.Frame(root)
                tabla = espacio['_tabla'](padre, ('id', 'stock'), ('ID', 'Stock'), (80, 100))
                self.assertNotIn('insert', tabla.__dict__)
                self.assertIs(tabla.insert.__func__, original)
                for i in range(1200):
                    insertar_fila(tabla, iid=str(i), values=(i, Decimal('18.45678')))
                self.assertEqual(len(tabla.get_children()), 1200)
                self.assertEqual(tabla.item('0', 'values'), ('0', '18.46'))
                self.assertEqual(tabla.item('1', 'tags'), ('impar',))
                padre.destroy()
            self.assertIs(ttk.Treeview.insert, original)
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
