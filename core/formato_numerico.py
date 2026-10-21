"""Presentación numérica sin modificar valores usados por servicios y SQL."""
from decimal import Decimal, InvalidOperation
from datetime import datetime,date

def format_numero(valor, agrupar=False, compactar=False):
    if valor is None:return '—'
    try:
        numero=Decimal(str(valor))
        if not numero.is_finite():return '—'
        texto=format(numero,',.2f' if agrupar else '.2f')
        return texto.rstrip('0').rstrip('.') if compactar else texto
    except (InvalidOperation,ValueError,TypeError):return str(valor)

def format_moneda(valor):return 'C$ '+format_numero(valor,agrupar=True)
def format_porcentaje(valor):return format_numero(valor)+'%'
def format_cantidad(valor):return format_numero(valor)
def format_score(valor):return format_numero(valor)

CAMPOS_DECIMALES={'cantidad','stock','stock_actual','stock_minimo','stock_total','precio','costo','valor','valor_stock','consumo','consumo_promedio_diario','dias','dias_restantes_promedio','score','similitud','confianza','fps','cobertura','promedio','minimo',
                  'cantidad_sistema','cantidad_fisica','diferencia','costo_unitario',
                  'costo_total','latencia','dias_restantes'}

def format_campo(clave,valor):
    if isinstance(valor,datetime):return valor.strftime('%d/%m/%Y %H:%M:%S')
    if isinstance(valor,date):return valor.strftime('%d/%m/%Y')
    if isinstance(valor,str) and any(k in str(clave).lower() for k in ('fecha','timestamp','actualizado')):
        try:
            return datetime.fromisoformat(valor.replace('Z','+00:00')).strftime('%d/%m/%Y %H:%M:%S')
        except ValueError:pass
    return format_numero(valor) if str(clave).lower() in CAMPOS_DECIMALES else valor
