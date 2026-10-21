"""Acciones completas de JARVIS sobre SQL Server, siempre con rollback exterior."""
import unittest
from decimal import Decimal
from unittest.mock import patch
from tests import probar_conteo_servicio as base
from tests.probar_inventario import ConexionPrueba
from jarvis import agente_inventario as agente
from inventory import conteo_inventario as conteo


class OrquestadorSQL(unittest.TestCase):
    def setUp(self):
        base.ConteosSQL.setUp(self)
        agente.reiniciar_contexto('verificacion_acciones_sql')
        p=patch.object(agente,'conectar',side_effect=lambda:ConexionPrueba(self.c,'agente'))
        p.start();self.addCleanup(p.stop)
        q=self.c.cursor()
        self.codigo=q.execute('SELECT codigo FROM productos WHERE id_producto=?',self.p).fetchone()[0]
        self.codigo_empleado=q.execute('SELECT codigo_empleado FROM empleados WHERE id_empleado=?',self.emp).fetchone()[0]

    entrada=base.ConteosSQL.entrada
    saldo=base.ConteosSQL.saldo
    filas=base.ConteosSQL.filas

    def preguntar(self,texto):return agente.procesar_consulta(texto,True,sesion='verificacion_acciones_sql')

    def preparar(self,cantidad):
        r=self.preguntar(f'Ajusta el stock de {self.codigo} a {cantidad} por {self.codigo_empleado}')
        self.assertEqual(r['intencion'],'confirmacion_requerida',r['respuesta'])

    def test_ajuste_decimal_no_ejecuta_antes_de_confirmacion(self):
        self.preparar('4.125');self.assertEqual(self.saldo(),0)
        r=self.preguntar('confirmar');self.assertEqual(r['intencion'],'accion_confirmada',r['respuesta'])
        self.assertEqual(self.saldo(),Decimal('4.125'))
        total=self.c.cursor().execute('SELECT COUNT(*) FROM movimientos').fetchone()[0]
        self.preguntar('sí')
        self.assertEqual(self.c.cursor().execute('SELECT COUNT(*) FROM movimientos').fetchone()[0],total)

    def test_stock_cambia_despues_de_previsualizar_rechaza(self):
        self.preparar('5');self.entrada(2)
        r=self.preguntar('hazlo');self.assertIn('stock cambió',r['respuesta'])
        self.assertEqual(self.saldo(),2)

    def test_conteo_confirmado_aplica_snapshot(self):
        self.entrada(20);filas=self.filas()
        for f in filas:f.update(cantidad_fisica=Decimal(19),contado=True)
        numero=conteo.guardar_conteo(self.emp,self.a,filas)
        r=self.preguntar(f'aplicar conteo {numero}')
        self.assertEqual(r['intencion'],'confirmacion_requerida',r['respuesta']);self.assertEqual(self.saldo(),20)
        r=self.preguntar('sí');self.assertEqual(r['intencion'],'accion_confirmada',r['respuesta'])
        self.assertEqual(self.saldo(),19)


if __name__=='__main__':unittest.main()
