"""Reglas físicas y límites SQL; las operaciones de verificación se revierten."""
import unittest
from decimal import Decimal
from inventory.organizacion_fisica import numero_led, validar_ubicacion, describir_posicion, asegurar_espacio
from core.database import conectar
from inventory.movimientos import _mover,_ajustar


class ReglasFisicas(unittest.TestCase):
    def test_correspondencia_leds(self):
        self.assertEqual([numero_led(e,n,p) for e in range(1,7) for n in (1,2) for p in (1,2)],list(range(1,25)))

    def test_nivel_y_estante_fuera_de_rango(self):
        for datos in ((1,3,1),(7,1,1),(1,1,3)):
            with self.assertRaises(ValueError):numero_led(*datos)

    def test_codigos_normalizados(self):
        self.assertEqual(validar_ubicacion('e01-n02','E1','N2'),('E01-N02','01','02'))
        with self.assertRaises(ValueError):validar_ubicacion('A-01','1','1')

    def test_descripcion_humana(self):
        self.assertEqual(describir_posicion({'estante':'01','nivel':'02','posicion':2}), 'Estante 1 - Nivel 2 - Posición 2')


class CapacidadSQL(unittest.TestCase):
    def setUp(self):
        self.c=conectar();self.q=self.c.cursor()
        self.addCleanup(self.c.close);self.addCleanup(self.c.rollback)
        self.destino=self.q.execute("SELECT id_ubicacion FROM ubicaciones WHERE codigo_ubicacion='E01-N01' AND estado=1").fetchone()[0]
        self.otro=self.q.execute("SELECT id_ubicacion FROM ubicaciones WHERE codigo_ubicacion='E01-N02' AND estado=1").fetchone()[0]
        self.productos=[r[0] for r in self.q.execute('SELECT id_producto FROM existencias WHERE id_ubicacion=? ORDER BY posicion',self.destino)]
        self.tercero=self.q.execute('SELECT id_producto FROM existencias WHERE id_ubicacion=? AND posicion=1',self.otro).fetchone()[0]
        self.empleado=self.q.execute('SELECT TOP 1 id_empleado FROM empleados WHERE estado=1 ORDER BY id_empleado').fetchone()[0]

    def test_tercer_producto_bloqueado_por_servicio(self):
        with self.assertRaisesRegex(ValueError,'dos espacios'):
            asegurar_espacio(self.q,self.tercero,self.destino)

    def test_nivel_tres_bloqueado_en_sql(self):
        with self.assertRaises(Exception) as error:
            self.q.execute("UPDATE ubicaciones SET nivel='03',codigo_ubicacion='E01-N03' WHERE id_ubicacion=?",self.destino)
        self.assertIn('547',str(error.exception))

    def test_nivel_nulo_bloqueado_en_sql(self):
        with self.assertRaises(Exception) as error:
            self.q.execute('UPDATE ubicaciones SET nivel=NULL WHERE id_ubicacion=?',self.destino)
        self.assertIn('547',str(error.exception))

    def test_tercer_producto_bloqueado_en_sql_incluso_cero(self):
        with self.assertRaises(Exception) as error:
            self.q.execute('INSERT existencias(id_producto,id_ubicacion,cantidad,posicion,fecha_creacion) VALUES(?,?,0,NULL,SYSDATETIME())',self.tercero,self.destino)
        self.assertIn('51001',str(error.exception))

    def test_duplicado_bloqueado_por_sql(self):
        with self.assertRaises(Exception) as error:
            self.q.execute('INSERT existencias(id_producto,id_ubicacion,cantidad,posicion,fecha_creacion) VALUES(?,?,1,NULL,SYSDATETIME())',self.productos[0],self.destino)
        self.assertTrue('2601' in str(error.exception) or '2627' in str(error.exception))

    def test_posicion_duplicada_bloqueada_por_sql(self):
        with self.assertRaises(Exception) as error:
            self.q.execute('INSERT existencias(id_producto,id_ubicacion,cantidad,posicion,fecha_creacion) VALUES(?,?,1,1,SYSDATETIME())',self.tercero,self.destino)
        self.assertIn('2601',str(error.exception))

    def test_entrada_y_salida_de_producto_presente(self):
        p=self.productos[0]
        anterior=self.q.execute('SELECT cantidad FROM existencias WHERE id_producto=? AND id_ubicacion=?',p,self.destino).fetchone()[0]
        _mover(self.q,self.empleado,p,None,self.destino,Decimal('0.125'),'Entrada','Verificación de capacidad')
        _mover(self.q,self.empleado,p,self.destino,None,Decimal('0.125'),'Salida','Verificación de capacidad')
        actual=self.q.execute('SELECT cantidad,posicion FROM existencias WHERE id_producto=? AND id_ubicacion=?',p,self.destino).fetchone()
        self.assertEqual(actual[0],anterior);self.assertEqual(actual[1],1)

    def test_transferencia_a_destino_lleno_bloqueada(self):
        with self.assertRaisesRegex(ValueError,'dos espacios'):
            _mover(self.q,self.empleado,self.productos[0],self.destino,self.otro,Decimal(1),'Transferencia')

    def test_ajuste_de_producto_presente(self):
        p=self.productos[0]
        anterior=self.q.execute('SELECT cantidad FROM existencias WHERE id_producto=? AND id_ubicacion=?',p,self.destino).fetchone()[0]
        _ajustar(self.q,self.empleado,p,self.destino,anterior+Decimal('0.125'),'Verificación de capacidad')
        self.assertEqual(self.q.execute('SELECT cantidad FROM existencias WHERE id_producto=? AND id_ubicacion=?',p,self.destino).fetchone()[0],anterior+Decimal('0.125'))


if __name__ == '__main__':unittest.main()
