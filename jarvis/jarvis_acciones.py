"""Preparación conversacional de movimientos, sin escribir ni generar SQL."""
import re
from decimal import Decimal
from jarvis.nlp_jarvis import normalizar_texto, singular
from core.formato_numerico import format_numero

PATRON = re.compile(r'\b(?:registra(?:r)?|anota|haz)\s+(?:un[ao]?\s+)?(entrada|salida|transferencia)\b|\b(transfiere|transferir)\b')


def preparar_movimiento(texto, ctx):
    from jarvis.jarvis_router import coincidencias, respuesta, _pedir_confirmacion
    from jarvis import herramientas_jarvis as servicios
    from jarvis import jarvis_consultas as datos
    from inventory.inventario_service import decimal_inventario
    t = normalizar_texto(texto)
    inicio = PATRON.search(t)
    if not inicio and not ctx.get('borrador_movimiento'):
        return None
    if inicio:
        ctx['borrador_movimiento'] = {'tipo': (inicio.group(1) or 'transferencia').title()}
    b = ctx['borrador_movimiento']

    def preguntar(mensaje, tipo, candidatos=None):
        ctx.esperar(['registrar_'+b['tipo'].lower()], tipo, candidatos)
        return respuesta(mensaje, 'aclaracion', clarification=True)

    cantidad = re.search(r'\b(?:entrada|salida|transferencia|transfiere|transferir)\s+(?:de\s+)?(-?\d+(?:[.,]\d+)?)\b', str(texto).lower())
    if cantidad or re.fullmatch(r'\d+(?:[.,]\d+)?', str(texto).strip()) and not b.get('candidatos'):
        b['cantidad'] = decimal_inventario(cantidad.group(1).replace(',', '.') if cantidad else str(texto).strip().replace(',', '.'), positivo=True)
    catalogo = servicios.datos_inventario()
    codigos_producto=[c for c in re.findall(r'\b[a-z]{2,8}-\d+\b',t) if not c.startswith('emp-')]
    if any(not any(normalizar_texto(p['codigo'])==c for p in catalogo) for c in codigos_producto):
        b.pop('producto',None)
        return preguntar('No encontré ese producto. Indica un código registrado.', 'producto')
    ps = coincidencias(' '.join(singular(p) for p in t.split()), catalogo, 'producto')
    if b.get('candidatos') and t.isdigit() and 1 <= int(t) <= len(b['candidatos']):
        ps = [b['candidatos'][int(t)-1]]
    if len(ps) > 1:
        b['candidatos'] = ps
        return preguntar('¿Qué producto?\n'+'\n'.join(f'{i+1}. {p["nombre"]} ({p["codigo"]})' for i,p in enumerate(ps)), 'producto', ps)
    if len(ps) == 1:
        b['producto'] = ps[0]; b.pop('candidatos', None)
    if 'producto' not in b and ctx.get('ultimo_producto_id') and re.search(r'\b(?:ese|su|mismo)\b', t):
        b['producto'] = next((p for p in catalogo if p['id_producto'] == ctx['ultimo_producto_id']), None)
    if not b.get('producto'):
        return preguntar('¿Qué producto quieres mover? Indica su nombre o código.', 'producto')
    p = servicios.datos_producto(b['producto']['id_producto'])
    if p.get('control_lotes'):
        ctx.pop('borrador_movimiento', None);ctx.completar()
        return respuesta('Este producto requiere seleccionar lote. Registra el movimiento desde Movimientos; no modifiqué existencias.', 'accion_no_disponible')
    if 'cantidad' not in b:
        return preguntar('¿Qué cantidad quieres registrar?', 'cantidad')
    us = servicios.datos_ubicaciones(p['id_producto'])
    codigos = re.findall(r'\be\d{1,2}-n\d{1,2}\b', t)
    if codigos:
        todas = datos.ubicaciones({})
        seleccion = [next((u for u in todas if normalizar_texto(u['codigo_ubicacion']) == c), None) for c in codigos]
        if any(u is None for u in seleccion):
            return preguntar('No encontré una de esas ubicaciones. Indica el código registrado.', 'ubicacion')
        if b['tipo'] == 'Transferencia':
            if len(seleccion)==1 and b.get('origen') and ('destino' in t or not re.search(r'\b(?:desde|origen)\b',t)):
                b['destino']=seleccion[0]['id_ubicacion']
            else:
                b['origen'] = seleccion[0]['id_ubicacion']
                if len(seleccion) > 1:b['destino'] = seleccion[1]['id_ubicacion']
        else:b['destino' if b['tipo'] == 'Entrada' else 'origen'] = seleccion[0]['id_ubicacion']
    elif len(us) == 1:
        b.setdefault('destino' if b['tipo'] == 'Entrada' else 'origen', us[0]['id_ubicacion'])
    requeridas = {'Entrada':('destino',), 'Salida':('origen',), 'Transferencia':('origen','destino')}[b['tipo']]
    if any(k not in b for k in requeridas):
        return preguntar('Indica '+('origen y destino, por ejemplo E01-N01 a E02-N01.' if b['tipo'] == 'Transferencia' else 'el código de ubicación del movimiento.'), 'ubicacion')
    if b.get('origen') == b.get('destino'):
        return preguntar('Origen y destino deben ser diferentes.', 'ubicacion')
    empleados = coincidencias(t, datos.empleados({}), 'empleado')
    if len(empleados) == 1:b['empleado'] = empleados[0]
    if 'empleado' not in b or len(empleados) > 1:
        return preguntar('¿Qué empleado será responsable? Indica su código.', 'empleado')
    actual = next((u for u in us if u['id_ubicacion'] == b.get('origen')), None)
    if b.get('origen') and (actual is None or Decimal(str(actual['cantidad'])) < b['cantidad']):
        ctx.pop('borrador_movimiento', None);ctx.completar()
        return respuesta('La ubicación de origen no tiene existencias suficientes. No registré el movimiento.', 'accion_no_disponible')
    payload = dict(tipo=b['tipo'], id_producto=p['id_producto'], id_empleado=b['empleado']['id_empleado'],
                   origen=b.get('origen'), destino=b.get('destino'), cantidad=b['cantidad'],
                   stock_anterior=Decimal(str(actual['cantidad'])) if actual else None)
    resumen = f"{b['tipo']} de {format_numero(b['cantidad'])} {p['unidad_medida']} de {p['nombre']}. Responsable: {b['empleado']['nombre']}."
    if actual:resumen += f" Stock en origen: {format_numero(actual['cantidad'])}; restante: {format_numero(Decimal(str(actual['cantidad']))-b['cantidad'])}."
    resumen += f" Origen: {b.get('origen') or 'no aplica'}; destino: {b.get('destino') or 'no aplica'}."
    ctx.pop('borrador_movimiento', None)
    return _pedir_confirmacion(ctx, 'registrar_'+b['tipo'].lower(), payload, resumen)
