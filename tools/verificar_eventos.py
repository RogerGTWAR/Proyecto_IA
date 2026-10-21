"""Repeatable isolated regression: no live SQL writes, HTTP, audio or devices."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))


def main():
    modules=['probar_auditoria_tecnica','probar_automatizacion','probar_ux_global','probar_system_state','probar_dashboard','probar_event_bus','probar_integracion_eventos','probar_cerebro_central',
        'probar_orquestador_jarvis','probar_contexto_jarvis','probar_nlp_jarvis',
        'probar_agente_avanzado','probar_cobertura_jarvis','probar_consultas_historial',
        'probar_telegram_bidireccional','probar_integracion_voz','probar_tts',
        'probar_led_service','probar_telegram_automatico','probar_telegram_modulos',
        'probar_eventos_visuales_telegram','probar_vigilancia','probar_identidad_vigilancia',
        'probar_codificacion']
    names=['tests.'+name for name in modules]+[
        'tests.probar_alertas_prediccion.Resolucion',
        'tests.probar_alertas_prediccion.CalculoIndependiente']
    names.append('tests.probar_presencia_empleados')
    stream=io.StringIO()
    from core.audit_service import audit, AuditService
    isolated_audit=AuditService(BASE/'outputs/eventos/auditoria_regresion')
    with contextlib.redirect_stdout(stream),contextlib.redirect_stderr(stream), \
         patch('core.database.conectar',side_effect=AssertionError('SQL real deshabilitado en regresión.')) as sql_guard, \
         patch('requests.sessions.Session.request',side_effect=AssertionError('HTTP real deshabilitado en regresión.')) as http_guard, \
         patch.object(audit,'record',new=isolated_audit.record):
        suite=unittest.defaultTestLoader.loadTestsFromNames(names)
        result=unittest.TextTestRunner(stream=stream,verbosity=1).run(suite)
    isolated_audit.close()
    output=BASE/'outputs'/'eventos';output.mkdir(parents=True,exist_ok=True)
    report=dict(ejecutadas=result.testsRun,
        correctas=result.testsRun-len(result.errors)-len(result.failures)-len(result.skipped),
        fallidas=[str(t) for t,e in result.failures],errores=[str(t) for t,e in result.errors],
        omitidas=[dict(caso=str(t),motivo=reason) for t,reason in result.skipped],
        exito=result.wasSuccessful(),suites=names,
        conexiones_reales_bloqueadas=sql_guard.call_count,peticiones_reales_bloqueadas=http_guard.call_count,
        alcance='Persistencia y transporte sustituidos; sin dispositivos ni cambios en registros SQL.')
    (output/'regresion.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'ejecucion.txt').write_text(stream.getvalue(),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':raise SystemExit(main())
