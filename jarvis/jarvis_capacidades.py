"""Capacidades declarativas adicionales del mismo planificador, sin otro contexto."""
import re
from jarvis.nlp_jarvis import normalizar_texto
from core.formato_numerico import format_numero


def seguimiento(t, ctx):
    from jarvis.jarvis_router import Plan, ejecutar_consulta
    dominio = {'alerta':'alertas','alertas':'alertas','anomalia':'anomalias',
               'anomalias':'anomalias','facial':'facial','conteos':'conteos'}.get(ctx.get('ultimo_dominio'))
    if not dominio:
        return None
    reglas = ((r'(?:y )?cuant[oa]s?(?: (?:hay|critic[oa]s?))*', 'contar'),
              (r'(?:y )?(?:cual (?:es |fue )?)?(?:la |el )?(?:ultima|ultimo|mas reciente)', 'ultimo'))
    op = next((op for patron, op in reglas if re.fullmatch(patron, t)), None)
    if op is None:
        return None
    anterior=ctx.get('ultimo_plan_orquestador',{})
    filtros=dict(anterior.get('filtros',{})) if anterior.get('dominio')==dominio else {}
    if 'critic' in t:filtros['nivel']='CRÍTICA'
    return ejecutar_consulta(Plan(dominio, op, filtros, 1 if op == 'ultimo' else 5, texto=t), ctx)


def compuesta(t, ctx):
    from jarvis.jarvis_router import Plan, _filtrar, _linea, respuesta
    from jarvis import jarvis_consultas as datos
    from jarvis import herramientas_jarvis as servicios
    if re.search(r'\banomalias?\b', t) and re.search(r'\balertas?\b', t):
        filtros = {'nivel':'CRÍTICA'} if 'critic' in t else {}
        alertas = _filtrar(datos.alertas(filtros), Plan('alertas', filtros=filtros))
        anomalias = _filtrar(datos.anomalias(filtros), Plan('anomalias', filtros=filtros))
        vinculados = {f.get('id_movimiento') for f in anomalias if f.get('id_movimiento')}
        independientes = [f for f in alertas if f.get('id_movimiento') not in vinculados]
        return respuesta(f'Hay {len(alertas)} alertas y {len(anomalias)} anomalías; {len(independientes)+len(anomalias)} eventos sin duplicar vínculos.'+
                         '\n'+'\n'.join(_linea(f,'alertas') for f in alertas[:3])+
                         '\n'+'\n'.join(_linea(f,'anomalias') for f in anomalias[:3]),
                         'alertas_y_anomalias', {'alertas':alertas,'anomalias':anomalias})
    if re.search(r'\bcuantos?\b', t) and re.search(r'\b(?:bajos|stock bajo)\b', t) and re.search(r'\bcuales\b', t):
        from inventory.inventario_service import estado_stock
        filas = [p for p in servicios.datos_inventario() if estado_stock(p['stock_actual'],p['stock_minimo']) in ('BAJO','CRÍTICO')]
        if len(filas) == 1:ctx.recordar_producto(filas[0])
        return respuesta(f'Hay {len(filas)} productos con stock bajo.\n'+'\n'.join(_linea(p,'productos') for p in filas),
                         'stock_bajo_resumen', filas)
    return None


def _resolver_producto(t, ctx, accion):
    from jarvis.jarvis_router import coincidencias, respuesta
    from jarvis import herramientas_jarvis as servicios
    catalogo = servicios.datos_inventario()
    candidatos = ctx.get('candidatos_ambiguos', [])
    if ctx.get('capacidad_pendiente') and t.isdigit() and 1 <= int(t) <= len(candidatos):
        ids = {candidatos[int(t)-1]['id_producto']}
        filas = [p for p in catalogo if p['id_producto'] in ids]
    else:filas = coincidencias(t, catalogo, 'producto')
    if not filas and ctx.get('ultimo_producto_id') and re.search(r'\b(?:su|ese|el mismo|dias quedan|durara)\b', t):
        filas = [p for p in catalogo if p['id_producto'] == ctx['ultimo_producto_id']]
    if len(filas) != 1:
        ctx['capacidad_pendiente'] = accion
        ctx.esperar([accion], 'producto', filas)
        return None, respuesta('¿Qué producto quieres consultar?'+ ('\n'+'\n'.join(f'{i+1}. {p["nombre"]} ({p["codigo"]})' for i,p in enumerate(filas)) if filas else ''),
                                'aclaracion', clarification=True)
    ctx.pop('capacidad_pendiente',None);ctx.completar();ctx.recordar_producto(filas[0])
    return filas[0], None


def buscar(t, ctx):
    from jarvis.jarvis_router import respuesta, _linea
    from jarvis import herramientas_jarvis as servicios
    p, pregunta = _resolver_producto(t, ctx, 'buscar_producto')
    if pregunta:return pregunta
    p = servicios.datos_producto(p['id_producto'])
    ctx['ultimo_dominio'] = 'producto'
    return respuesta(_linea(p,'productos'), 'buscar_producto', p)


def predecir(t, ctx):
    from jarvis.jarvis_router import respuesta
    from jarvis import herramientas_jarvis as servicios
    from jarvis.jarvis_personality import prediccion
    p, pregunta = _resolver_producto(t, ctx, 'prediccion_producto')
    if pregunta:return pregunta
    r = servicios.datos_prediccion(p['id_producto'])
    ctx['ultima_prediccion'] = r;ctx['ultimo_dominio'] = 'producto'
    if not r or not r.get('datos_suficientes'):
        return respuesta('No hay una predicción calculada actualmente para ese producto. '+
                         (r.get('mensaje','Datos insuficientes para generar una predicción confiable.') if r else ''),
                         'prediccion_agotamiento', r or {})
    return respuesta(prediccion(r), 'prediccion_agotamiento', r)


def agotados(t, ctx):
    from jarvis.jarvis_router import respuesta, _linea
    from jarvis import herramientas_jarvis as servicios
    filas=servicios.datos_inventario('Agotados')
    ctx['lista_productos']=filas;ctx['ultimo_dominio']='producto';ctx['ultimos_resultados']=filas
    if len(filas)==1:ctx.recordar_producto(filas[0])
    texto=(f'Hay {len(filas)} productos agotados.' if re.search(r'\bcuantos\b',t) else
           '\n'.join(_linea(p,'productos') for p in filas) if filas else 'No hay productos agotados.')
    return respuesta(texto,'productos_agotados',{'productos':filas})


REGLAS = (
    ('productos_agotados', r'\b(?:productos? (?:esta[n]? )?agotados?|hay algo agotado)\b', agotados),
    ('buscar_producto', r'^(?:busca|buscar|encuentra)\b', buscar),
    ('prediccion_producto', r'\b(?:se va a acabar|se va a agotar|cuantos dias quedan|cuantos dias le quedan)\b', predecir),
)


def capacidad(t, ctx):
    pendiente = ctx.get('capacidad_pendiente')
    if pendiente:
        if re.match(r'^(?:que|quien|cuant|donde|hay|abre|genera)',t):
            ctx.pop('capacidad_pendiente',None);ctx.completar()
        else:
            fn = next((fn for nombre,_,fn in REGLAS if nombre == pendiente),None)
            if fn:return fn(t,ctx)
    fn = next((fn for _,patron,fn in REGLAS if re.search(patron,t)),None)
    return fn(t,ctx) if fn else None
