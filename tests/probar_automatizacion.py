"""Pipeline real y motores reales con persistencia/transporte aislados."""
from datetime import datetime,date,timedelta
from decimal import Decimal
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock,patch

from core import event_bus as core
from core.event_subscribers import consumir_alerta,consumir_telegram,ALERTABLES,NOTIFICABLES
from core.automatizacion_inventario import AutomatizacionInventario,ResultadosPrediccion
from ai.anomalies.deteccion_anomalias import evaluar_movimiento_incremental as evaluar_incremental_real


class Pipeline(unittest.TestCase):
    def setUp(self):
        from tests.probar_system_state import aislar_estado
        aislar_estado(self)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.bus=core.EventBus();self.addCleanup(self.bus.close)
        self.servicio=AutomatizacionInventario(self.bus,ResultadosPrediccion(Path(self.tmp.name)/'resultados.json'),debounce=.05)
        self.addCleanup(self.servicio.cerrar)
        self.stock=Decimal(10);self.activas={};self.historial=[];self.analizadas=[]
        self.patchers=[patch.object(core,'event_bus',self.bus),
            patch('inventory.alertas.verificar_alertas_stock',side_effect=self.alerta_stock),
            patch('inventory.alertas.registrar_alerta_anomalia_evento',return_value={'id_alerta':91,'creada':True}),
            patch('ai.prediction.prediccion_stock._actualizar_alerta'),
            patch('integrations.telegram.telegram_service.servicio_telegram.notificar'),
            patch('ai.anomalies.deteccion_anomalias.evaluar_movimiento_incremental',side_effect=lambda m,p:self.analizadas.append(m)),
            patch('ai.prediction.prediccion_stock.analizar_consumo_producto',side_effect=self.consumo)]
        self.mocks=[p.start() for p in self.patchers]
        for p in self.patchers:self.addCleanup(p.stop)
        self.bus.subscribe(ALERTABLES,consumir_alerta,name='alertas')
        self.bus.subscribe(NOTIFICABLES,consumir_telegram,name='telegram')
        self.sub=self.bus.subscribe('MOVIMIENTO_REGISTRADO',self.servicio.movimiento,name='pipeline')

    def alerta_stock(self,p,**kwargs):
        estado='AGOTADO' if self.stock==0 else 'BAJO' if self.stock<=5 else 'NORMAL'
        for k in list(self.activas):
            if k!=estado:
                self.historial.append((k,'Atendida'));self.activas.pop(k)
                core.emitir('ALERTA_RESUELTA','ALERTAS','alertas','Resuelta',metadata={'derivada':True})
        if estado!='NORMAL' and estado not in self.activas:
            self.activas[estado]=p
            core.emitir('ALERTA_CREADA','ALERTAS','alertas','Stock',metadata={'derivada':True})

    def consumo(self,p,ventana,**kwargs):
        inicio=date.today()-timedelta(days=ventana-1)
        return dict(producto='Filtro de combustible',stock_actual=self.stock,stock_minimo=Decimal(5),
            fecha_analisis=date.today(),ventana=ventana,dias_analizados=ventana,dias_con_salidas=ventana,
            consumo_diario=[{'fecha':inicio+timedelta(days=i),'cantidad':2.0} for i in range(ventana)],
            consumo_promedio_diario=2.0,consumo_maximo=2.0,consumo_minimo=2.0)

    def mover(self,previo,nuevo,m=1,tipo='Salida'):
        self.stock=Decimal(nuevo)
        return core.emitir('MOVIMIENTO_REGISTRADO','MOVIMIENTOS','movimientos','Confirmado',
            reference='movimiento:'+str(m),data=dict(id_movimiento=m,id_producto=7,tipo_movimiento=tipo,
            stock_anterior=Decimal(previo),stock_nuevo=self.stock,stock_minimo=Decimal(5),
            producto='Filtro de combustible',codigo='FIL-003'))

    def tipos(self,tipo):return self.bus.store.get_events_by_type(tipo)

    def test_A_movimiento_stock_alerta_telegram_una_vez(self):
        self.mover(6,4)
        self.assertEqual(len(self.tipos('STOCK_BAJO')),1)
        self.assertEqual(len(self.tipos('ALERTA_CREADA')),1)
        self.assertEqual(len(self.activas),1)
        self.mocks[4].assert_called_once()
        self.assertEqual(self.mocks[4].call_args.args[0],'inventario')

    def test_B_algoritmo_incremental_persistencia_anomalia_alerta(self):
        from ai.anomalies import deteccion_anomalias as motor
        base=datetime(2026,10,18)
        anteriores=[dict(id_detalle=i,id_movimiento=i,id_producto=7,tipo_movimiento='Salida',
                        fecha=base+timedelta(minutes=i),cantidad=2+i%2) for i in range(1,13)]
        candidato=dict(anteriores[-1],id_detalle=50,id_movimiento=50,cantidad=25,producto='Filtro',
                       empleado='Ana',id_empleado=1,fecha=base+timedelta(hours=1))
        guardados=set();c=Mock();q=Mock();c.cursor.return_value=q
        def insertar(sql,*args):
            clave=(args[0],args[1]);identificador=None
            if clave not in guardados:guardados.add(clave);identificador=90
            q.fetchone.return_value=(identificador,);return q
        q.execute.side_effect=insertar
        self.mocks[5].side_effect=evaluar_incremental_real
        with patch.object(motor,'datos_movimientos',side_effect=lambda **kw:[candidato] if 'movimiento' in kw else anteriores), \
             patch.object(motor,'conectar',return_value=c):
            self.mover(100,75,m=50)
            self.mover(100,75,m=50)
            r=self.servicio.ultima_evaluacion
        self.assertEqual(r['anomalias_detectadas'],1)
        self.assertEqual(len(self.tipos('ANOMALIA_DETECTADA')),1)
        self.assertEqual(len(self.tipos('ALERTA_CREADA')),1)
        self.assertEqual(len(guardados),1)

    def test_C_prediccion_persistida_antes_de_evento_y_critico(self):
        self.stock=Decimal(40);self.servicio.calcular(7,False)
        observados=[]
        self.bus.subscribe('PREDICCION_GENERADA',lambda e:observados.append(self.servicio.resultados.obtener(7,30)['riesgo']))
        self.mover(40,4);self.servicio.procesar_prediccion(7)
        self.assertEqual(observados,['CRÍTICO'])
        self.assertEqual(len(self.tipos('RIESGO_CRITICO')),1)
        nuevo=ResultadosPrediccion(self.servicio.resultados.ruta)
        self.assertEqual(nuevo.obtener(7,30)['stock_actual'],Decimal(4))
        self.assertIsInstance(nuevo.obtener(7,30)['fecha_analisis'],date)

    def test_D_bajo_bajo_agotado_normal_sin_duplicar_y_con_historial(self):
        self.mover(6,4,1);self.mover(4,3,2)
        self.assertEqual(len(self.tipos('STOCK_BAJO')),1)
        self.assertEqual(len(self.tipos('ALERTA_CREADA')),1)
        self.mover(3,0,3);self.mover(0,10,4,tipo='Entrada')
        self.assertEqual(len(self.tipos('STOCK_AGOTADO')),1)
        self.assertEqual(len(self.tipos('STOCK_NORMALIZADO')),1)
        self.assertFalse(self.activas)
        self.assertEqual(len(self.historial),2)

    def test_E_alto_critico_y_repeticion_sin_spam(self):
        self.stock=Decimal(40);self.servicio.calcular(7,False)
        self.stock=Decimal(12);self.servicio.calcular(7,True)
        self.stock=Decimal(4);self.servicio.calcular(7,True);self.servicio.calcular(7,True)
        self.assertEqual(len(self.tipos('RIESGO_ALTO')),1)
        self.assertEqual(len(self.tipos('RIESGO_CRITICO')),1)
        self.assertEqual(self.mocks[4].call_count,2)
        self.assertEqual(len(self.tipos('PREDICCION_GENERADA')),4)

    def test_inicio_silencioso_sin_repetir_riesgo_historico(self):
        self.stock=Decimal(4);self.servicio.calcular(7,False)
        self.servicio.calcular(7,True)
        self.mocks[4].assert_not_called()
        self.assertFalse(self.tipos('RIESGO_CRITICO'))

    def test_ui_cerrada_worker_procesa_y_coalesce(self):
        self.sub.unsubscribe()
        with patch.object(self.servicio,'reconciliar',side_effect=lambda:setattr(self.servicio,'proxima_revision',time.monotonic()+3600)):
            self.servicio.iniciar()
            self.mover(10,9,1);self.mover(9,8,2);self.mover(8,7,3)
            limite=time.monotonic()+5
            while not self.servicio.resultados.obtener(7,30) and time.monotonic()<limite:time.sleep(.02)
            self.assertTrue(self.servicio.resultados.obtener(7,30))
            self.assertEqual(self.analizadas,[1,2,3])
            self.assertEqual(self.mocks[6].call_count,4)
            self.servicio.cerrar()

    def test_fallo_prediccion_conserva_movimiento_stock_y_anomalias(self):
        self.mover(6,4)
        with patch('ai.prediction.prediccion_stock.predecir_agotamiento',side_effect=RuntimeError('No disponible')):
            self.assertFalse(self.servicio.procesar_prediccion(7))
        self.assertEqual(self.stock,4);self.assertEqual(self.analizadas,[1])
        self.assertEqual(len(self.tipos('MOVIMIENTO_REGISTRADO')),1)
        self.assertEqual(len(self.tipos('PREDICCION_ERROR')),1)
        self.assertIn(7,self.servicio.pendientes)

    def test_fallo_anomalia_no_impide_prediccion(self):
        self.mocks[5].side_effect=RuntimeError('No disponible')
        self.mover(6,4)
        self.assertTrue(self.servicio.procesar_prediccion(7))
        self.assertEqual(len(self.tipos('ANOMALIAS_ERROR')),1)
        self.assertTrue(self.servicio.resultados.obtener(7,30))

    def test_transferencia_se_evalua_sin_programar_consumo(self):
        self.mover(10,10,tipo='Transferencia')
        self.assertEqual(self.analizadas,[1]);self.assertFalse(self.servicio.pendientes)
        self.assertFalse(self.tipos('STOCK_BAJO'))

    def test_lecturas_no_invocan_motores(self):
        from core.automatizacion_inventario import obtener_prediccion,listar_predicciones
        with patch('ai.prediction.prediccion_stock.predecir_agotamiento',side_effect=AssertionError('Lectura no debe calcular')):
            self.assertIsInstance(listar_predicciones(),list)
            self.assertIsInstance(obtener_prediccion(987654321),dict)

    def test_historial_insuficiente_no_notifica_ni_inventa_fecha(self):
        def insuficiente(p,ventana,**kwargs):
            r=self.consumo(p,ventana)
            r.update(dias_con_salidas=0,consumo_diario=[],dias_analizados=0,consumo_promedio_diario=0.0)
            return r
        self.mocks[6].side_effect=insuficiente
        self.servicio.calcular(7,True)
        r=self.servicio.resultados.obtener(7,30)
        self.assertFalse(r['datos_suficientes']);self.assertIsNone(r['fecha_agotamiento'])
        self.mocks[4].assert_not_called()


if __name__=='__main__':unittest.main()
