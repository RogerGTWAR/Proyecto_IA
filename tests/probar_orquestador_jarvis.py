"""Lenguaje, contexto y confirmaciones con catálogos aislados y sin hardware."""
import unittest
from unittest.mock import patch,Mock
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from jarvis import agente_inventario as agente
from jarvis import herramientas_jarvis as servicios
from jarvis import jarvis_consultas as datos


class Orquestador(unittest.TestCase):
    def setUp(self):
        agente.reiniciar_contexto()
        self.ps=[dict(id_producto=1,codigo='TOR-001',nombre='Tornillo M8',stock_actual=43,stock_minimo=10,unidad_medida='Unidad',categoria='Tornillería',precio=2,control_lotes=False,fecha_creacion=datetime(2026,1,1)),
            dict(id_producto=2,codigo='FIL-001',nombre='Filtro de aceite',stock_actual=0,stock_minimo=5,unidad_medida='Unidad',categoria='Filtros',precio=10,control_lotes=False,fecha_creacion=datetime(2026,2,1))]
        self.es=[dict(id_empleado=7,codigo_empleado='EMP-007',nombre='Carlos López',fecha_creacion=datetime(2026,1,1)),
            dict(id_empleado=8,codigo_empleado='EMP-008',nombre='Fernando Ruiz',fecha_creacion=datetime(2026,2,1))]
        self.ms=[dict(id_movimiento=12,id_producto=1,id_empleado=8,empleado='Fernando Ruiz',tipo_movimiento='Salida',cantidad=5,producto='Tornillo M8',unidad_medida='Unidad',fecha_movimiento=datetime(2026,10,17,18,42)),
            dict(id_movimiento=11,id_producto=2,id_empleado=7,empleado='Carlos López',tipo_movimiento='Entrada',cantidad=10,producto='Filtro de aceite',unidad_medida='Unidad',fecha_movimiento=datetime(2026,10,16,10))]
        self.an=[dict(id_anomalia=3,id_movimiento=12,id_producto=1,id_empleado=8,producto='Tornillo M8',nivel='CRÍTICA',score=4,estado='PENDIENTE',motivo='Salida de 5 frente a promedio previo de 1.',fecha=datetime(2026,10,17,18,42))]
        self.al=[dict(id_alerta=4,id_producto=2,id_empleado=None,id_movimiento=None,tipo='Producto agotado',nivel='Critica',mensaje='Sin existencias.',fecha_generacion=datetime(2026,10,17))]
        self.us=[dict(id_ubicacion=4,codigo_ubicacion='E04-N01',cantidad=43,estante='04',nivel='01',posicion=2,unidad_medida='Unidad')]
        def movimientos(f,producto=None,empleado=None):
            filas=[m for m in self.ms if (producto is None or m['id_producto']==producto) and (empleado is None or m['id_empleado']==empleado)]
            if f.get('tipo_movimiento'):filas=[m for m in filas if m['tipo_movimiento']==f['tipo_movimiento']]
            return deepcopy(filas)
        parches=[patch.object(agente,'obtener_productos_activos',side_effect=lambda:deepcopy(self.ps)),
            patch.object(agente,'obtener_empleados_activos',side_effect=lambda:deepcopy(self.es)),
            patch.object(servicios,'datos_inventario',side_effect=lambda estado='Todos',**kw:deepcopy([p for p in self.ps if not p['stock_actual']] if estado=='Agotados' else self.ps)),
            patch.object(servicios,'datos_producto',side_effect=lambda i:deepcopy(next(p for p in self.ps if p['id_producto']==i))),
            patch.object(servicios,'datos_ubicaciones',side_effect=lambda i:deepcopy(self.us if i==1 else [])),
            patch.object(servicios,'datos_movimientos',side_effect=movimientos),
            patch.object(servicios,'datos_anomalias',side_effect=lambda f:deepcopy(self.an)),
            patch.object(datos,'alertas',side_effect=lambda f:deepcopy(self.al)),
            patch.dict(datos.LECTURAS,{'alertas':lambda filtros:deepcopy(self.al),'facial':lambda filtros:[],
                'conteos':lambda filtros:[],'vigilancia':lambda filtros:[]}),
            patch.object(datos,'estado',return_value={'SQL':'ONLINE','Telegram':'CONECTADO','JARVIS':'DISPONIBLE','Cámara':'SIN VERIFICAR','Vigilancia':'Inactivo','Arduino':'SIN VERIFICAR','SFace':'SIN VERIFICAR'}),
            patch.object(servicios,'datos_prediccion',side_effect=lambda i:dict(producto=self.ps[i-1]['nombre'],stock_actual=self.ps[i-1]['stock_actual'],datos_suficientes=True,dias_restantes_promedio=4,consumo_promedio_diario=2,riesgo='ALTO',explicacion='Stock dividido por consumo registrado.',mensaje='')),
            patch.object(agente,'interpretar_con_llm',return_value=(None,0,'sin servicio'))]
        for p in parches:p.start();self.addCleanup(p.stop)

    def preguntar(self,t,sesion='escritorio'):return agente.procesar_consulta(t,True,sesion)

    def test_consultas_obligatorias_y_variantes(self):
        casos=[('¿Cuántos empleados hay?','2'),('Cuantos empleados hay','2'),
            ('¿Quién fue el último empleado agregado?','Fernando'),('Quien fue el ultimo empleado agregado','Fernando'),
            ('¿Quién hizo el último movimiento?','Fernando'),('¿Quién fue el último empleado en hacer un movimiento?','Fernando'),
            ('¿Cuál fue el último movimiento?','Tornillo M8'),('¿Qué producto tiene más stock?','43.00'),
            ('¿Qué producto tiene menos stock?','Filtro de aceite'),('¿Dónde está Tornillo M8?','Estante'),
            ('¿Hay productos agotados?','Filtro de aceite'),('¿Cuántas alertas críticas hay?','1'),
            ('¿Cuál fue la última anomalía?','promedio previo'),('¿Qué productos están en riesgo de agotarse?','Riesgo alto'),
            ('¿Está funcionando Telegram?','CONECTADO'),('¿La cámara está activa?','SIN VERIFICAR'),
            ('Hola Jarvis','Hola'),('Qué nota',''),('Gracias','')]
        for texto,esperado in casos:
            with self.subTest(texto=texto):
                agente.reiniciar_contexto();r=self.preguntar(texto)
                self.assertNotEqual(r['intencion'],'error',r['respuesta']);self.assertIn(esperado,r['respuesta'])
                self.assertNotIn('No encontré un empleado',r['respuesta'])

    def test_contexto_producto_movimiento_y_autor(self):
        for t in ('¿Dónde está Tornillo M8?','¿Cuánto stock tiene?','¿Y cuál fue su último movimiento?','¿Quién lo hizo?'):
            r=self.preguntar(t);self.assertNotEqual(r['intencion'],'error')
        self.assertIn('Fernando Ruiz',r['respuesta'])
        self.assertEqual(agente.obtener_contexto()['ultimo_producto_id'],1)
        self.assertIn('43',self.preguntar('¿Y cuánto tiene?')['respuesta'])

    def test_aclaracion_pendiente_de_ubicacion(self):
        self.preguntar('Ubicación');r=self.preguntar('Filtro de aceite')
        self.assertEqual(r['intencion'],'consultar_ubicacion')
        self.assertNotIn('Qué deseas hacer',r['respuesta'])

    def test_ultimo_agregado_sin_dominio_pide_aclaracion(self):
        r=self.preguntar('¿Quién fue el último en ser agregado?');self.assertEqual(r['intencion'],'aclaracion')
        self.assertIn('Fernando',self.preguntar('empleado')['respuesta'])

    def test_explicacion_anomalia_utiliza_el_registro(self):
        self.preguntar('¿Cuál fue la última anomalía?')
        r=self.preguntar('¿Por qué fue considerada anomalía?')
        self.assertEqual(r['respuesta'],self.an[0]['motivo'])

    def test_luz_seguimiento_y_apagado_con_servicio_real_mockeado(self):
        with patch('integrations.arduino.led_service.servicio_led.por_producto',return_value={'mensaje':'Orden confirmada por el servicio.'}) as led:
            self.preguntar('Enciende la luz de Tornillo M8');led.assert_called_once_with(1,True)
            self.preguntar('Apágala');self.assertEqual(led.call_args.args,(1,False))

    def test_consulta_relacional_no_busca_ultimo_como_empleado(self):
        r=self.preguntar('¿Quién hizo el último movimiento del Tornillo M8?')
        self.assertIn('Fernando',r['respuesta']);self.assertIn('5.00',r['respuesta'])
        self.assertEqual(agente.obtener_contexto()['ultimo_movimiento']['id_movimiento'],12)

    def test_catalogo_ambiguo_no_elige_producto(self):
        self.ps.append(dict(self.ps[0],id_producto=3,codigo='TOR-002',nombre='Tornillo M10'))
        r=self.preguntar('último movimiento de tornillo')
        self.assertEqual(r['intencion'],'aclaracion');self.assertIn('Tornillo M10',r['respuesta'])
        r=self.preguntar('1');self.assertIn('Tornillo M8',r['respuesta'])

    def test_codigo_inexistente_no_consulta_movimiento_global(self):
        r=self.preguntar('último movimiento de TOR-999')
        self.assertEqual(r['intencion'],'aclaracion');self.assertNotIn('Fernando',r['respuesta'])

    def test_sin_fechas_no_afirma_orden_por_id(self):
        self.es[0].pop('fecha_creacion')
        self.assertIn('Faltan fechas',self.preguntar('último empleado agregado')['respuesta'])

    def test_fecha_intervalo_y_primero(self):
        r=self.preguntar('primer movimiento entre 2026-10-01 y 2026-10-18')
        self.assertIn('Carlos',r['respuesta'])
        self.assertIn('Carlos',self.preguntar('último movimiento antes de 2026-10-17')['respuesta'])
        self.assertIn('Fernando',self.preguntar('último movimiento después de 2026-10-16')['respuesta'])

    def test_contar_movimientos_no_detalles_duplicados(self):
        self.ms.append(dict(self.ms[0],id_producto=2))
        r=self.preguntar('cuántos movimientos hay')
        self.assertEqual(r['datos']['total'],2)

    def test_confirmacion_ajuste_solo_una_ejecucion_y_esperado(self):
        with patch('inventory.movimientos.registrar_ajuste',return_value=99) as ajustar:
            r=self.preguntar('Ajusta el stock de Tornillo M8 a 50');self.assertEqual(r['intencion'],'aclaracion')
            r=self.preguntar('EMP-008');self.assertTrue(r['confirmation']);self.assertIn('7.00',r['respuesta'])
            ajustar.assert_not_called()
            r=self.preguntar('confirmar');ajustar.assert_called_once()
            self.assertEqual(ajustar.call_args.kwargs['esperado'],Decimal(43))
            self.preguntar('sí');ajustar.assert_called_once()

    def test_cancelar_no_escribir_y_confirmacion_por_sesion(self):
        with patch('inventory.movimientos.registrar_ajuste') as ajustar:
            self.preguntar('Ajusta el stock de Tornillo M8 a 50 por EMP-008')
            self.preguntar('sí',sesion='telegram:88');ajustar.assert_not_called()
            self.preguntar('cancelar');self.preguntar('sí');ajustar.assert_not_called()

    def test_confirmacion_caduca_y_sql_fallido_no_usa_stock_memorizado(self):
        self.preguntar('Ajusta el stock de Tornillo M8 a 50 por EMP-008')
        agente.obtener_contexto()['confirmacion_pendiente']['vence']=0
        with patch('inventory.movimientos.registrar_ajuste') as ajustar:
            self.assertEqual(self.preguntar('hazlo')['intencion'],'confirmacion_vencida');ajustar.assert_not_called()
        with patch.object(servicios,'datos_movimientos',side_effect=ConnectionError()),patch('jarvis.agente_inventario.logging'):
            r=self.preguntar('último movimiento');self.assertEqual(r['intencion'],'error');self.assertNotIn('Fernando',r['respuesta'])

    def test_alerta_confirmada_revalida_pendiente(self):
        with patch('inventory.alertas.marcar_alerta_atendida') as atender:
            r=self.preguntar('marca la alerta 4 como atendida');self.assertTrue(r['confirmation']);atender.assert_not_called()
            self.al.clear();r=self.preguntar('sí');atender.assert_not_called();self.assertIn('ya no está pendiente',r['respuesta'])

    def test_nueva_pregunta_invalida_confirmacion(self):
        self.preguntar('Ajusta el stock de Tornillo M8 a 50 por EMP-008')
        self.preguntar('cuántos empleados hay')
        with patch('inventory.movimientos.registrar_ajuste') as ajustar:self.preguntar('hazlo');ajustar.assert_not_called()

    def test_ajuste_decimal_no_pierde_decimales_en_normalizacion(self):
        with patch('inventory.movimientos.registrar_ajuste',return_value=99) as ajustar:
            self.preguntar('Ajusta el stock de Tornillo M8 a 50,125 por EMP-008')
            self.preguntar('sí')
            self.assertEqual(ajustar.call_args.args[3],Decimal('50.125'))

    def test_accion_incompleta_no_secuestra_pregunta_nueva(self):
        self.preguntar('ajusta stock de Tornillo M8 a 50')
        r=self.preguntar('cuantos empleados hay')
        self.assertEqual(r['intencion'],'empleados_contar')
        self.assertFalse(agente.obtener_contexto().get('borrador_ajuste'))

    def test_vigilancia_confirmar_no_modifica_motor_ni_config(self):
        with patch('surveillance.vigilancia_yolo.servicio_vigilancia.obtener_estado',return_value={'activo':True}), \
             patch('surveillance.vigilancia_yolo.servicio_vigilancia.parar') as parar:
            r=self.preguntar('detener vigilancia');self.assertTrue(r['confirmation']);parar.assert_not_called()
            self.preguntar('sí');parar.assert_called_once()

    def test_conteo_confirmado_usa_snapshot_y_responsable_registrado(self):
        filas=[dict(id_producto=1,id_lote=None,cantidad_sistema=43,cantidad_fisica=40,contado=True,unidad_medida='Unidad')]
        with patch('inventory.conteo_inventario.cargar_conteo',return_value=({'id_conteo':2,'id_empleado':8,'estado':'BORRADOR'},filas)), \
             patch('inventory.conteo_inventario.aplicar_conteo') as aplicar:
            r=self.preguntar('aplica conteo 2');self.assertTrue(r['confirmation']);aplicar.assert_not_called()
            self.preguntar('hazlo');aplicar.assert_called_once_with(2,esperado=filas,empleado_esperado=8)

    def test_reportes_reutilizan_motor_sin_sql_desde_ui(self):
        r={'titulo':'Movimientos','filas':[{}]}
        with patch.object(datos,'vista_reporte',return_value=(r,None)) as reporte:
            x=self.preguntar('genera reporte de movimientos')
            self.assertEqual(x['intencion'],'generar_reporte');reporte.assert_called_once()
            self.assertEqual(reporte.call_args.kwargs['tipo'],'Movimientos')

    def test_comparacion_y_agrupacion_no_mezclan_unidades(self):
        r=self.preguntar('cuál tiene más stock TOR-001 o FIL-001');self.assertIn('Tornillo M8',r['respuesta'])
        r=self.preguntar('cuál tiene menos stock TOR-001 o FIL-001');self.assertIn('Filtro de aceite',r['respuesta'])
        r=self.preguntar('qué empleado ha hecho más movimientos Carlos o Fernando')
        self.assertIn('Carlos',r['respuesta']);self.assertIn('Fernando',r['respuesta'])
        self.ps[1]['unidad_medida']='Litro'
        r=self.preguntar('stock total');self.assertIn('Unidad',r['respuesta']);self.assertIn('Litro',r['respuesta'])
        r=self.preguntar('stock por categoría');self.assertIn('Tornillería',r['respuesta'])

    def test_producto_mas_antiguo_y_producto_con_menor_stock(self):
        self.assertIn('Tornillo M8',self.preguntar('producto más antiguo')['respuesta'])
        self.preguntar('qué producto tiene más stock')
        self.assertIn('Filtro de aceite',self.preguntar('cuál tiene menos')['respuesta'])

    def test_producto_precio_categoria_y_no_sobre_responder(self):
        r=self.preguntar('precio del producto TOR-001')
        self.assertIn('Precio: 2.00',r['respuesta']);self.assertNotIn('43.00',r['respuesta'])
        self.assertIn('Tornillería',self.preguntar('categoría del producto TOR-001')['respuesta'])

    def test_alias_publico_router_usa_mismo_contexto(self):
        from jarvis.jarvis_router import procesar
        r=procesar('quien hizo el ultimo movimiento',session_id='telegram:orquestador')
        self.assertIn('Fernando',r['respuesta'])
        self.assertEqual(agente.obtener_contexto('telegram:orquestador')['ultimo_producto_id'],1)

    def test_no_hay_autor_sin_referencia_previa(self):
        self.assertEqual(self.preguntar('¿Quién lo hizo?')['intencion'],'aclaracion')

    def test_sumar_y_promedio_por_producto_solo_movimientos_correspondientes(self):
        self.ms.append(dict(self.ms[0],id_movimiento=13,cantidad=3))
        r=self.preguntar('promedio de salidas de Tornillo M8');self.assertIn('4.00',r['respuesta'])
        r=self.preguntar('cantidad total movida de Tornillo M8');self.assertIn('8.00',r['respuesta'])

    def test_consultar_led_no_enciende_hardware(self):
        with patch('integrations.arduino.led_service.servicio_led.por_producto') as encender:
            r=self.preguntar('qué LED corresponde a Tornillo M8')
            self.assertEqual(r['intencion'],'consultar_led');self.assertIn('14',r['respuesta'])
            encender.assert_not_called()

    def test_navegacion_no_aplica_ajuste_que_estaba_pendiente(self):
        self.preguntar('ajusta stock de Tornillo M8 a 50 por EMP-008')
        r=self.preguntar('abrir conteo físico')
        self.assertEqual(r['acciones_ui'],[{'tipo':'abrir_modulo','modulo':'Conteo de inventario'}])
        with patch('inventory.movimientos.registrar_ajuste') as ajustar:self.preguntar('sí');ajustar.assert_not_called()

    def test_cortesia_no_rompe_borrador_ni_consulta_sql(self):
        self.preguntar('ajusta stock de Tornillo M8 a 50')
        with patch.object(servicios,'datos_inventario') as inventario:
            self.preguntar('gracias');inventario.assert_not_called()
        self.assertTrue(self.preguntar('EMP-008')['confirmation'])

    def test_texto_voz_y_telegram_comparten_respuesta_logica(self):
        r=self.preguntar('quien hizo el ultimo movimiento')
        self.assertEqual(r['voz'],r['respuesta'])
        otro=self.preguntar('quien hizo el ultimo movimiento',sesion='telegram:orquestador_voz')
        self.assertEqual(otro['respuesta'],r['respuesta'])


if __name__=='__main__':unittest.main()
