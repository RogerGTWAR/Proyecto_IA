"""Contrastar consultas incrementales con SQL protegido contra escritura."""
from pathlib import Path
import json
import sys
import tempfile
from unittest.mock import patch

BASE=Path(__file__).resolve().parents[2];sys.path.insert(0,str(BASE))
from tools.verificacion_ui.verificar_unicode import ConexionLectura,conectar_original
from core import database
database.conectar=lambda:ConexionLectura(conectar_original())
from ai.anomalies import deteccion_anomalias as motor
from core.automatizacion_inventario import AutomatizacionInventario,ResultadosPrediccion
from core.event_bus import EventBus


def main():
    datos=motor.datos_movimientos()
    if not datos:raise RuntimeError('No hay movimientos disponibles para contrastar las consultas.')
    candidato=datos[-1]
    total=motor.analizar_datos_movimientos(datos)
    esperado=[r for r in total['resultados'] if r['id_movimiento']==candidato['id_movimiento'] and r['id_producto']==candidato['id_producto']]
    with patch.object(motor,'guardar_hallazgos'):
        incremental=motor.evaluar_movimiento_incremental(candidato['id_movimiento'],candidato['id_producto'])
    assert [(r['id_detalle'],r['score']) for r in esperado]==[(r['id_detalle'],r['score']) for r in incremental['resultados']]
    bus=EventBus()
    try:
        with tempfile.TemporaryDirectory() as carpeta:
            servicio=AutomatizacionInventario(bus,ResultadosPrediccion(Path(carpeta)/'resultados.json'))
            servicio.calcular(candidato['id_producto'],False)
            resultados=servicio.resultados.listar(30)
            assert resultados and len(bus.store.get_events_by_type('PREDICCION_GENERADA'))==1
            assert not bus.store.get_events_by_type('RIESGO_CRITICO')
            reporte={'consulta_incremental_coincide':True,'candidatos_evaluados':incremental['movimientos_analizados'],
                'ventanas_calculadas':[7,30,60,90],'producto_id':candidato['id_producto'],
                'riesgo_observado':resultados[0]['riesgo'],'datos_suficientes':resultados[0]['datos_suficientes'],
                'alcance':'Consultas reales de lectura. Persistencia de hallazgos sustituida y resultados en carpeta aislada. Sin Telegram.'}
    finally:bus.close()
    salida=BASE/'outputs/automatizacion';salida.mkdir(parents=True,exist_ok=True)
    (salida/'sql_lectura.json').write_text(json.dumps(reporte,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(reporte,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
