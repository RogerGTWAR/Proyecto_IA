"""Regresión de conversaciones y resolución, sin hardware ni escrituras SQL."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import patch
from datetime import date,datetime
from decimal import Decimal
from jarvis import agente_inventario as agente
from jarvis import herramientas_jarvis as servicios
from jarvis.nlp_jarvis import extraer_filtros,normalizar_texto

class Conversacion(unittest.TestCase):
    def setUp(self):
        agente.reiniciar_contexto()
        self.productos=[
            {'id_producto':1,'codigo':'FIL-001','nombre':'Filtro de aceite','stock_actual':8,'stock_minimo':10,'unidad_medida':'Unidad','estado':True},
            {'id_producto':2,'codigo':'FIL-002','nombre':'Filtro de aire','stock_actual':18,'stock_minimo':10,'unidad_medida':'Unidad','estado':True},
            {'id_producto':3,'codigo':'TOR-001','nombre':'Tornillo','stock_actual':80,'stock_minimo':20,'unidad_medida':'Unidad','estado':True},
            {'id_producto':4,'codigo':'MOT-001','nombre':'Motor eléctrico','stock_actual':3,'stock_minimo':1,'unidad_medida':'Unidad','estado':True}]
        self.ubicaciones=[{'id_ubicacion':1,'codigo_ubicacion':'A-P01-E01','cantidad':8,'unidad_medida':'Unidad','almacen':'Principal','zona':'A','pasillo':'01','estante':'E01','nivel':'01'}]
        self.anomalias=[{'id_anomalia':1,'id_movimiento':100,'producto':'Filtro de aceite','nivel':'ALTA','score':5,'estado':'PENDIENTE','motivo':'Cantidad 25, promedio previo 3, desviación 1.'},
                       {'id_anomalia':2,'id_movimiento':101,'producto':'Tornillo','nivel':'CRÍTICA','score':7,'estado':'PENDIENTE','motivo':'Cantidad 100, promedio previo 10, desviación 2.'}]
        self.parches=[patch.object(agente,'obtener_productos_activos',side_effect=lambda:self.productos),
            patch.object(servicios,'datos_producto',side_effect=lambda i:dict(next(p for p in self.productos if p['id_producto']==i))),
            patch.object(servicios,'datos_ubicaciones',return_value=self.ubicaciones),
            patch.object(servicios,'datos_prediccion',side_effect=self.prediccion),
            patch.object(servicios,'datos_inventario',side_effect=lambda estado='Todos',**_:self.productos[:1] if estado=='Stock bajo' else self.productos),
            patch.object(servicios,'datos_anomalias',side_effect=lambda filtros:list(self.anomalias)),
            patch.object(servicios,'datos_movimientos',return_value=[]),
            patch.object(servicios,'datos_contenido',return_value=[]),
            patch.object(agente,'interpretar_con_llm',return_value=(None,0,'sin servicio'))]
        self.parches.append(patch.object(agente,'obtener_empleados_activos',return_value=[{'id_empleado':7,'nombre':'Carlos López','codigo_empleado':'EMP-007'}]))
        for p in self.parches:p.start();self.addCleanup(p.stop)

    def prediccion(self,i):
        p=next(p for p in self.productos if p['id_producto']==i)
        return {'producto':p['nombre'],'datos_suficientes':True,'dias_restantes_promedio':4 if i==1 else 12,'riesgo':'ALTO' if i==1 else 'MEDIO','explicacion':'Se calcula stock dividido por consumo registrado.','mensaje':''}

    def consultar(self,texto,**kwargs):return agente.procesar_consulta(texto,True,**kwargs)

    def test_intenciones_incompletas_se_ejecutan_al_recibir_producto(self):
        for pregunta,intencion in [('Ubicacion','consultar_ubicacion'),('?Cuanto queda?','consultar_stock'),('?Cuanto durara?','prediccion_agotamiento')]:
            with self.subTest(pregunta=pregunta):
                agente.reiniciar_contexto()
                self.consultar(pregunta)
                ctx=agente.obtener_contexto()
                self.assertEqual(ctx['intencion_pendiente'],intencion)
                self.assertEqual(ctx['estado_dialogo'],'WAITING_FOR_PRODUCT')
                r=self.consultar('Filtro de aceite')
                self.assertEqual(r['intencion'],intencion)
                self.assertEqual(r['datos']['producto']['id_producto'],1)
                self.assertEqual(ctx['estado_dialogo'],'IDLE')
                self.assertIsNone(ctx['intencion_pendiente'])

    def test_ambiguedad_cambio_intencion_y_nombre_completa_ubicacion(self):
        self.consultar('stock de filtros')
        self.consultar('Ubicacion')
        self.assertEqual(agente.obtener_contexto()['intencion_pendiente'],'consultar_ubicacion')
        r=self.consultar('Filtro de aire')
        self.assertEqual(r['intencion'],'consultar_ubicacion')
        self.assertEqual(r['acciones_opcionales'][0]['id'],2)
        r=self.consultar('y el primero')
        self.assertEqual(r['intencion'],'consultar_ubicacion')
        self.assertEqual(r['acciones_opcionales'][0]['id'],1)

    def test_saludo_natural_no_pierde_consulta_pendiente(self):
        self.consultar('Ubicacion')
        r=self.consultar('Que nota dogh')
        self.assertEqual(r['intencion'],'como_estas')
        self.assertEqual(agente.obtener_contexto()['intencion_pendiente'],'consultar_ubicacion')
        self.assertEqual(self.consultar('Filtro de aceite')['intencion'],'consultar_ubicacion')

    def test_producto_sin_intencion_se_completa_con_intencion(self):
        self.consultar('Motor electrico')
        ctx=agente.obtener_contexto()
        self.assertEqual(ctx['estado_dialogo'],'WAITING_FOR_CLARIFICATION')
        self.assertEqual(ctx['entidad_pendiente']['id_producto'],4)
        self.assertEqual(self.consultar('Ubicacion')['acciones_opcionales'][0]['id'],4)

    def test_nueva_intencion_tiene_prioridad(self):
        self.consultar('Ubicacion')
        self.consultar('?Cuanto durara?')
        self.assertEqual(self.consultar('Motor electrico')['intencion'],'prediccion_agotamiento')

    def test_cancelacion_y_reinicio_eliminan_pendientes(self):
        self.consultar('Ubicacion');self.consultar('cancelar')
        self.assertIsNone(agente.obtener_contexto()['intencion_pendiente'])
        self.consultar('stock de filtros');self.consultar('reiniciar contexto')
        ctx=agente.obtener_contexto()
        self.assertFalse(ctx.turnos);self.assertFalse(ctx['candidatos_ambiguos'])
        self.assertIsNone(ctx['intencion_pendiente']);self.assertEqual(ctx['estado_dialogo'],'IDLE')

    def test_publicos_texto_y_voz_comparten_estado(self):
        # La UI entrega texto reconocido a procesar_consulta igual que el teclado.
        agente.procesar_pregunta('Ubicacion')
        r=agente.procesar_consulta_estructurada('Filtro de aceite')
        self.assertEqual(r['acciones_opcionales'][0]['id'],1)
        self.assertIn('8',agente.procesar_consulta('?Cuanto queda?'))

    def test_error_servicio_conserva_pendiente_para_reintentar(self):
        self.consultar('Ubicacion')
        with patch.object(servicios,'datos_producto',side_effect=ConnectionError('fallo')),patch('jarvis.agente_inventario.logging'):
            self.assertEqual(self.consultar('Filtro de aceite')['intencion'],'error')
        self.assertEqual(agente.obtener_contexto()['intencion_pendiente'],'consultar_ubicacion')
        self.assertEqual(self.consultar('Filtro de aceite')['intencion'],'consultar_ubicacion')

    def test_intencion_explicita_reemplaza_plan_con_candidatos(self):
        self.consultar('stock de filtros')
        self.assertEqual(self.consultar('Ubicacion del segundo')['intencion'],'consultar_ubicacion')

    def test_ubicacion_pendiente_completa_con_zona(self):
        self.consultar('?Que hay ahi?')
        self.assertEqual(agente.obtener_contexto()['estado_dialogo'],'WAITING_FOR_LOCATION')
        r=self.consultar('Zona A')
        self.assertEqual(r['intencion'],'contenido_ubicacion')
        self.assertEqual(servicios.datos_contenido.call_args.args[0]['valor_ubicacion'],'a')


    def test_medida_explicita_reduce_candidatos_sin_adivinar(self):
        self.productos[2]['nombre']='Tornillo hexagonal 1/2'
        self.productos.append(dict(self.productos[2],id_producto=5,codigo='TOR-002',nombre='Tornillo galvanizado 3/8'))
        self.consultar('Ubicación de tornillos')
        r=self.consultar('el de 1/2')
        self.assertEqual(r['intencion'],'consultar_ubicacion')
        self.assertEqual(r['datos']['producto']['id_producto'],3)

    def test_error_ubicaciones_no_borra_intencion_pendiente(self):
        self.consultar('Ubicación')
        with patch.object(servicios,'datos_ubicaciones',side_effect=ConnectionError('fallo')),patch('jarvis.agente_inventario.logging'):
            self.assertEqual(self.consultar('Filtro de aceite')['intencion'],'error')
        self.assertEqual(agente.obtener_contexto()['intencion_pendiente'],'consultar_ubicacion')
        self.assertEqual(self.consultar('Filtro de aceite')['intencion'],'consultar_ubicacion')

    def test_fecha_seguimiento_movimientos_conserva_producto(self):
        self.consultar('movimientos de filtro de aceite hoy')
        self.consultar('¿Y ayer?')
        self.assertEqual(servicios.datos_movimientos.call_args.args[1],1)
        self.assertIn('fecha_desde',servicios.datos_movimientos.call_args.args[0])

    def test_donde_queda_no_se_interpreta_como_stock(self):
        r=self.consultar('¿Dónde queda el filtro de aceite?')
        self.assertEqual(r['intencion'],'consultar_ubicacion')
        self.assertNotIn('Quedan',r['respuesta'])

    def test_producto_desconocido_pendiente_no_usa_otro_producto(self):
        self.consultar('stock de tornillo')
        self.consultar('Ubicación de computadora cuántica')
        r=self.consultar('¿Dónde está?')
        self.assertNotIn('producto',r['datos'])
        self.assertEqual(agente.obtener_contexto()['estado_dialogo'],'WAITING_FOR_PRODUCT')

    def test_small_talk_ampliado_conserva_producto_y_plan(self):
        self.consultar('stock de filtro de aceite')
        for frase in ('qué haces','perfecto','dale','ok','listo','todo bien','gracias Jarvis','nos vemos'):
            with self.subTest(frase=frase):
                r=self.consultar(frase)
                self.assertIn(r['intencion'],('actividad_social','confirmacion_social','agradecimiento','despedida'))
                self.assertEqual(agente.obtener_contexto()['ultimo_producto_id'],1)
        self.assertEqual(self.consultar('¿Dónde están?')['acciones_opcionales'][0]['id'],1)

    def test_contexto_visual_no_reemplaza_conversacion_ni_pendiente(self):
        self.consultar('stock de filtro de aceite')
        agente.establecer_producto_visual(4,'Motor eléctrico')
        self.assertEqual(self.consultar('¿Dónde están?')['acciones_opcionales'][0]['id'],1)
        agente.reiniciar_contexto()
        self.consultar('Ubicación')
        agente.establecer_producto_visual(4,'Motor eléctrico')
        self.assertEqual(agente.obtener_contexto()['intencion_pendiente'],'consultar_ubicacion')
        self.assertEqual(self.consultar('Filtro de aceite')['acciones_opcionales'][0]['id'],1)

    def test_aclaracion_pregunta_segun_intencion(self):
        r=self.consultar('¿Dónde están los filtros?')
        self.assertIn('Cuál quieres localizar',r['respuesta'])
        self.assertNotIn('Cuál quieres consultar',r['respuesta'])

    def test_media_pulgada_resuelve_medida_real(self):
        self.productos[2]['nombre']='Tornillo 1/2'
        self.productos.append(dict(self.productos[2],id_producto=5,codigo='TOR-002',nombre='Tornillo 3/8'))
        self.consultar('¿Dónde están los tornillos?')
        r=self.consultar('el de media')
        self.assertEqual(r['datos']['producto']['id_producto'],3)
        self.assertEqual(r['intencion'],'consultar_ubicacion')

    def test_el_otro_conserva_intencion(self):
        self.consultar('¿Dónde están los filtros?');self.consultar('el primero')
        r=self.consultar('¿Y el otro?')
        self.assertEqual(r['datos']['producto']['id_producto'],2)
        self.assertEqual(r['intencion'],'consultar_ubicacion')

    def test_sinonimos_consultan_servicios_reales(self):
        r=self.consultar('¿Dónde están guardados los filtros de aceite?')
        self.assertEqual(r['acciones_opcionales'][0]['id'],1)
        r=self.consultar('¿Cuánto tiempo falta para acabarse?')
        self.assertEqual(r['intencion'],'prediccion_agotamiento')

    def test_confianza_media_pide_confirmacion_antes_de_consultar(self):
        r=self.consultar('Ubicación de motr elcr')
        self.assertEqual(r['intencion'],'aclaracion')
        self.assertEqual(agente.obtener_contexto()['estado_dialogo'],'WAITING_FOR_CONFIRMATION')
        servicios.datos_producto.assert_not_called()
        self.assertIn('Te refieres',r['respuesta'])
        r=self.consultar('sí')
        self.assertEqual(r['intencion'],'consultar_ubicacion')
        self.assertEqual(r['datos']['producto']['id_producto'],4)

    def test_rechazo_sugerencia_conserva_intencion(self):
        self.consultar('Ubicación de motr elcr');self.consultar('no')
        self.assertEqual(agente.obtener_contexto()['intencion_pendiente'],'consultar_ubicacion')
        self.assertFalse(agente.obtener_contexto()['candidatos_ambiguos'])
        r=self.consultar('Filtro de aceite')
        self.assertEqual(r['acciones_opcionales'][0]['id'],1)

    def test_baja_confianza_no_sugiere_producto_inventado(self):
        r=self.consultar('stock de computadora cuántica')
        self.assertNotIn('producto',r['datos'])
        self.assertFalse(agente.obtener_contexto()['candidatos_ambiguos'])
        servicios.datos_producto.assert_not_called()

    def test_abrir_mapa_no_olvida_consulta_pendiente(self):
        self.consultar('Ubicación')
        r=self.consultar('abre el mapa')
        self.assertEqual(r['acciones_ui'],[{'tipo':'abrir_mapa'}])
        self.assertEqual(agente.obtener_contexto()['intencion_pendiente'],'consultar_ubicacion')

    def test_pregunta_no_entendida_preserva_ultimo_resultado(self):
        self.consultar('stock de filtro de aceite')
        resultado=agente.obtener_contexto()['ultimo_resultado']
        self.consultar('abcdefghijklmnop')
        self.assertEqual(agente.obtener_contexto()['ultimo_resultado'],resultado)

    def test_small_talk_no_oculta_consulta_operativa(self):
        r=self.consultar('Hola Jarvis, ¿cuánto stock queda de filtro de aceite?')
        self.assertEqual(r['datos']['producto']['id_producto'],1)

    def test_anomalia_pendiente_recuerda_que_debe_explicar(self):
        self.consultar('¿Hay anomalías?');self.consultar('¿Por qué?')
        self.assertEqual(agente.obtener_contexto()['estado_dialogo'],'WAITING_FOR_ANOMALY_SELECTION')
        r=self.consultar('1')
        self.assertEqual(r['intencion'],'explicar_anomalia')
        self.assertIn('promedio previo',r['respuesta'])
        self.assertEqual(agente.obtener_contexto()['estado_dialogo'],'IDLE')

    def test_cambiar_de_anomalia_pendiente_a_stock(self):
        self.consultar('¿Hay anomalías?');self.consultar('¿Por qué?')
        self.consultar('stock')
        self.assertEqual(self.consultar('Motor eléctrico')['intencion'],'consultar_stock')

    def test_conversacion_completa_stock_mapa_prediccion_cambio_estado(self):
        r=self.consultar('Jarvis, ¿cuántos filtros de aceite quedan?');self.assertEqual(r['datos']['producto']['id_producto'],1)
        r=self.consultar('¿Dónde están?');self.assertEqual(r['acciones_opcionales'],[{'tipo':'producto_mapa','id':1}])
        r=self.consultar('Muéstramelos.');self.assertEqual(r['acciones_ui'][0]['id'],1)
        r=self.consultar('¿Cuánto durarán?');self.assertEqual(r['datos']['prediccion']['dias_restantes_promedio'],4)
        r=self.consultar('¿Y los filtros de aire?');self.assertEqual(r['datos']['producto']['id_producto'],2);self.assertIn('18',r['respuesta'])
        r=self.consultar('¿También están bajos?');self.assertIn('por encima',r['respuesta'])

    def test_candidatos_ordinal_conserva_pregunta_compuesta(self):
        r=self.consultar('¿Cuántos filtros quedan y dónde están?');self.assertEqual(len(r['datos']['candidatos']),2)
        r=self.consultar('el segundo');self.assertEqual(r['datos']['producto']['id_producto'],2);self.assertIn('18',r['respuesta']);self.assertEqual(r['acciones_opcionales'][0]['id'],2)

    def test_candidato_por_descriptor(self):
        self.consultar('¿Dónde están los filtros?')
        r=self.consultar('el de aceite');self.assertEqual(r['datos']['producto']['id_producto'],1)

    def test_sin_contexto_no_adivina(self):
        self.assertIn('Qué producto',self.consultar('¿Dónde está?')['respuesta'])

    def test_fuzzy_sin_elegir_por_palabra_compartida(self):
        for texto,i in [('stock de filto de aseite',1),('stock de motro electrico',4),('stock de tornyo',3)]:
            with self.subTest(texto=texto):self.assertEqual(self.consultar(texto)['datos']['producto']['id_producto'],i)

    def test_producto_desconocido_no_reutiliza_contexto(self):
        self.consultar('stock de tornillo')
        r=self.consultar('¿Cuánto queda de computadora cuántica?');self.assertNotIn('producto',r['datos']);self.assertIn('No encontré',r['respuesta'])

    def test_explicacion_dominio_anomalia_y_prediccion(self):
        self.consultar('¿Hay anomalías?');self.consultar('¿Cuál es la más grave?')
        r=self.consultar('¿Por qué fue marcada?');self.assertIn('100',r['respuesta'])
        self.consultar('¿Cuánto durará el filtro de aceite?')
        r=self.consultar('¿Por qué?');self.assertIn('consumo registrado',r['respuesta']);self.assertNotIn('100',r['respuesta'])

    def test_pregunta_movimientos_no_se_confunde_con_stock(self):
        r=self.consultar('¿Cuántos movimientos hubo hoy?');self.assertEqual(r['intencion'],'consultar_movimientos')
        servicios.datos_movimientos.assert_called_once();self.assertNotIn('producto',r['datos'])

    def test_stock_se_consulta_nuevamente(self):
        self.consultar('stock de tornillo');self.productos[2]['stock_actual']=50
        self.assertIn('50',self.consultar('¿Cuánto queda?')['respuesta'])

    def test_error_sql_no_devuelve_stock_anterior(self):
        self.consultar('stock de tornillo')
        with patch.object(servicios,'datos_producto',side_effect=ConnectionError('fallo')),patch('jarvis.agente_inventario.logging'):
            r=self.consultar('¿Cuánto queda?');self.assertEqual(r['intencion'],'error');self.assertNotIn('80',r['respuesta'])

    def test_reinicio_limpia_memoria_candidatos_historial(self):
        self.consultar('stock de filtros');agente.reiniciar_contexto()
        ctx=agente.obtener_contexto();self.assertFalse(ctx.turnos);self.assertFalse(ctx['candidatos_ambiguos']);self.assertIsNone(ctx['ultimo_producto_id'])

    def test_historial_acotado_y_sesiones_aisladas(self):
        for _ in range(25):self.consultar('hola')
        self.assertEqual(len(agente.obtener_contexto().turnos),20)
        self.consultar('stock de tornillo')
        r=self.consultar('¿Dónde está?',sesion='otra_conversacion');self.assertNotIn('producto',r['datos'])

    def test_stock_bajo_y_primero_en_agotarse(self):
        r=self.consultar('¿Qué productos están bajos y cuál se agotaría primero?')
        self.assertEqual(r['datos']['prediccion']['producto'],'Filtro de aceite')

    def test_contexto_visual_y_producto_anterior(self):
        agente.establecer_producto_visual(1,'Filtro de aceite')
        self.assertEqual(self.consultar('¿Cuánto queda?')['datos']['producto']['id_producto'],1)
        self.consultar('stock de tornillo')
        self.assertEqual(self.consultar('el anterior')['datos']['producto']['id_producto'],1)

    def test_explicar_stock_critico_no_usa_prediccion_vieja(self):
        self.consultar('¿Cuánto durará el tornillo?');self.consultar('¿Cuál es el más crítico?')
        r=self.consultar('¿Por qué?');self.assertIn('mínimo',r['respuesta']);self.assertNotIn('consumo registrado',r['respuesta'])

    def test_mutacion_se_rechaza_antes_de_consultar(self):
        r=self.consultar('elimina el producto filtro');self.assertEqual(r['intencion'],'accion_no_permitida');servicios.datos_producto.assert_not_called()

    def test_numero_fuera_de_candidatos(self):
        self.consultar('stock de filtros');self.assertIn('no está',self.consultar('el quinto')['respuesta'])

    def test_fechas_inclusivas(self):
        for texto,desde in [('hoy','2026-10-11'),('ayer','2026-10-10'),('esta semana','2026-10-05'),('este mes','2026-10-01'),('últimos 7 días','2026-10-05'),('últimos 30 días','2026-09-12')]:
            with self.subTest(texto=texto):self.assertEqual(extraer_filtros(normalizar_texto(texto),date(2026,10,11))['fecha_desde'],desde)

    def test_anomalias_seguimiento_conserva_periodo(self):
        self.consultar('anomalías ayer');filtros=dict(agente.obtener_contexto()['filtros_anomalias'])
        self.consultar('¿Cuál es la más grave?');self.assertEqual(servicios.datos_anomalias.call_args.args[0],filtros)

    def test_movimientos_hoy_no_quedan_filtrados_por_producto_previo(self):
        self.consultar('stock de tornillo');self.consultar('¿Cuántos movimientos hubo hoy?')
        self.assertIsNone(servicios.datos_movimientos.call_args.args[1]);self.assertIn('fecha_desde',servicios.datos_movimientos.call_args.args[0])

    def test_movimientos_de_empleado_resuelven_actor(self):
        self.consultar('movimientos de Carlos ayer')
        self.assertEqual(servicios.datos_movimientos.call_args.args[2],7)

    def test_fuzzy_no_asume_coincidencia_debil(self):
        r=self.consultar('stock de marciano azul');self.assertEqual(r['intencion'],'aclaracion');servicios.datos_producto.assert_not_called()

    def test_voz_conserva_los_mismos_productos_que_la_respuesta(self):
        r=self.consultar('productos con stock bajo')
        self.assertIn('Filtro de aceite',r['voz']);self.assertNotIn('El detalle está en pantalla',r['voz'])

    def test_contexto_localizacion_no_afirma_accion_visual_ya_realizada(self):
        r=self.consultar('localizar filtro de aceite');self.assertTrue(r['acciones_opcionales']);self.assertNotIn('estoy resaltando',r['respuesta'].lower())
        self.assertFalse(r['acciones_ui'])

    def test_ubicacion_responde_texto_y_mapa_es_opcional(self):
        for consulta in ('¿Dónde está el filtro de aceite?','¿Dónde está?','¿En qué estante está?','¿Cuál es su ubicación?'):
            with self.subTest(consulta=consulta):
                self.consultar('stock del filtro de aceite')
                r=self.consultar(consulta)
                self.assertEqual(r['intencion'],'consultar_ubicacion')
                self.assertEqual(r['acciones_ui'],[])
                self.assertEqual(r['acciones_opcionales'],[{'tipo':'producto_mapa','id':1}])
                self.assertEqual(agente.obtener_contexto()['ultimo_producto_id'],1)
                self.assertEqual(agente.obtener_contexto()['ultima_ubicacion'],self.ubicaciones)

    def test_comandos_explicitos_abren_mapa_del_producto_recordado(self):
        for consulta in ('Muéstramelo en el mapa','Abrir mapa','Ver ubicación en mapa','Llévame al mapa','Enséñame dónde está','Muéstramelo'):
            with self.subTest(consulta=consulta):
                agente.reiniciar_contexto();self.consultar('ubicación del filtro de aceite')
                r=self.consultar(consulta)
                self.assertEqual(r['acciones_ui'],[{'tipo':'producto_mapa','id':1}])
                self.assertEqual(agente.obtener_contexto()['ultimo_producto_id'],1)

    def test_mapa_explicito_con_ambiguedad_espera_producto(self):
        r=self.consultar('Muéstrame los filtros en el mapa')
        self.assertFalse(r['acciones_ui'])
        r=self.consultar('el segundo')
        self.assertEqual(r['acciones_ui'],[{'tipo':'producto_mapa','id':2}])

    def test_varias_posiciones_y_agotado_conservan_accion_opcional(self):
        filas=[dict(self.ubicaciones[0],codigo_ubicacion='E04-N01',estante='04',nivel='01',posicion=2,cantidad=0),
               dict(self.ubicaciones[0],id_ubicacion=2,codigo_ubicacion='E05-N02',estante='05',nivel='02',posicion=1,cantidad=0)]
        with patch.object(servicios,'datos_ubicaciones',return_value=filas):
            r=self.consultar('ubicacion del filtro de aceite')
        self.assertFalse(r['acciones_ui']);self.assertTrue(r['acciones_opcionales'])
        self.assertIn('Estante 4, Nivel 1, Posición 2',r['respuesta'])
        self.assertIn('Estante 5, Nivel 2, Posición 1',r['respuesta'])
        self.assertIn('2 ubicaciones',r['respuesta']);self.assertIn('agotado',r['respuesta'])

    def test_contenido_estante_no_navega_y_negacion_no_abre_mapa(self):
        with patch.object(servicios,'datos_contenido',return_value=[{'id_ubicacion':1,'nombre':'Filtro','cantidad':8,'unidad_medida':'Unidad','codigo_ubicacion':'E04-N01'}]):
            r=self.consultar('que hay en el estante 4')
            self.assertFalse(r['acciones_ui']);self.assertTrue(r['acciones_opcionales'])
        r=self.consultar('Donde esta el filtro de aceite sin abrir mapa')
        self.assertFalse(r['acciones_ui'])

    def test_contenido_ubicacion_por_referencia(self):
        self.consultar('ubicación de filtro de aceite');self.consultar('¿Qué hay ahí?')
        self.assertEqual(servicios.datos_contenido.call_args.args[0]['valor_ubicacion'],'A-P01-E01')

    def test_contenido_ubicacion_multiple_requiere_seleccion(self):
        with patch.object(servicios,'datos_ubicaciones',return_value=self.ubicaciones+[dict(self.ubicaciones[0],id_ubicacion=2,codigo_ubicacion='B-P01-E01')]):
            self.consultar('ubicación de filtro de aceite');self.consultar('¿Qué hay ahí?');self.consultar('el segundo')
        self.assertEqual(servicios.datos_contenido.call_args.args[0]['valor_ubicacion'],'B-P01-E01')

    def test_conversacion_concurrente_se_serializa(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as e:
            resultados=list(e.map(lambda _:self.consultar('stock de filtro de aceite'),range(6)))
        self.assertEqual(len(agente.obtener_contexto().turnos),6);self.assertTrue(all(r['datos']['producto']['id_producto']==1 for r in resultados))

    def test_mostrar_esa_ubicacion_usa_antecedente(self):
        self.consultar('ubicación de filtro de aceite');self.consultar('muéstrame esa ubicación')
        self.assertEqual(servicios.datos_contenido.call_args.args[0]['valor_ubicacion'],'A-P01-E01')

if __name__=='__main__':unittest.main()
