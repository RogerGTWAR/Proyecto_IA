"""Consultas de presencia sobre la observación real de Cámara 2."""
import re


def responder(texto,ctx):
    room=re.search(r'\b(?:habitacion|sala de personal|camara 2|presencia|presentes)\b',texto)
    if 'dentro' in texto and re.search(r'\b(?:quien|quienes|personas|empleados)\b',texto):room=True
    simple=texto in ('quienes estan','quien esta','hay desconocidos','quien entro ultimo','quien salio recientemente')
    seguimiento=ctx.get('ultimo_dominio')=='presencia' and re.search(r'\b(?:quienes|cuantos|desconocidos|entro|salio)\b',texto)
    if not (room or simple or seguimiento):return None
    if re.search(r'\b(?:inicia|deten|enciende|apaga|configura)\w*',texto):return None
    from surveillance import presencia_empleados as p
    from jarvis import herramientas_jarvis as h
    if 'camara 2' in texto and re.search(r'\b(?:activa|estado|funciona|linea)\b',texto):
        state=h.ejecutar('vigilancia.estado_camara',{'camera':2})
        result=f"Cámara de presencia: {state['estado']}. {state['detalle']}"
    elif re.search(r'\b(?:entro|salio|entraron|salieron)\b',texto):
        salida=bool(re.search(r'\b(?:salio|salieron)\b',texto))
        rows=[e for e in p.obtener_historial() if ('SALIO' if salida else 'ENTRO') in e['tipo_evento']]
        if rows:
            e=rows[0];result=f"Última {'salida' if salida else 'entrada'} observada: {e.get('nombre') or e.get('estado_identidad') or 'persona'}, track {e['track_id']}, {e['fecha_hora']}."
        else:result='No hay entradas o salidas registradas para esa consulta.'
    else:
        c=h.ejecutar('vigilancia.obtener_ocupacion')
        if not c['disponible']:result=p.resumen_presencia()
        elif 'cuantos empleados' in texto or 'cuantas empleadas' in texto:result=f"Hay {c['identificados']} empleados identificados."
        elif 'desconocid' in texto:result=f"Hay {c['desconocidos']} personas desconocidas confirmadas y {c['pendientes']} con identidad pendiente."
        else:result=p.resumen_presencia()
    ctx['ultimo_dominio']='presencia'
    return dict(respuesta=result,intencion='presencia_habitacion',datos=p.obtener_conteo_actual())
