"""Consultas naturales de salidas y consumo sobre las rutas compartidas."""
from datetime import date
import unittest
from jarvis.nlp_jarvis import normalizar_texto,plan_conversacional,extraer_filtros


class ConsultasHistorial(unittest.TestCase):
    def test_salidas_de_la_semana(self):
        texto=normalizar_texto('¿Qué salió esta semana?')
        self.assertEqual(plan_conversacional(texto),['consultar_movimientos'])
        filtros=extraer_filtros(texto,hoy=date(2026,10,13))
        self.assertEqual(filtros['tipo_movimiento'],'Salida')
        self.assertEqual((filtros['fecha_desde'],filtros['fecha_hasta']),('2026-10-12','2026-10-13'))

    def test_consumiendo_mas(self):
        self.assertEqual(plan_conversacional(normalizar_texto('¿Qué productos se están consumiendo más?')),['resumen_consumo'])

    def test_mayor_numero_de_salidas(self):
        self.assertEqual(plan_conversacional(normalizar_texto('¿Qué producto ha tenido más salidas?')),['resumen_consumo'])


if __name__=='__main__':unittest.main()
