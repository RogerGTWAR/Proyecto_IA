"""Identidad y formatos comunes a PDF, Excel y presentación de reportes."""
from ui.ui_theme import COLORES

PALETA = {k: COLORES[k] for k in ('primario', 'azul_secundario', 'acento', 'verde',
    'aviso', 'peligro', 'fondo', 'texto', 'secundario', 'borde', 'azul_claro')}
FUENTE_PDF = 'Helvetica'
FUENTE_EXCEL = 'Calibri'
FORMATOS = {'cantidad': '#,##0.00', 'dinero': '"C$ "#,##0.00',
            'entero': '#,##0', 'fecha': 'dd/mm/yyyy', 'hora': 'dd/mm/yyyy hh:mm'}
NUMERICAS = {'stock_actual', 'stock_minimo', 'cantidad', 'precio', 'valor',
             'consumo_promedio_diario', 'dias_restantes_promedio', 'score'}
ESTADOS = {
    'NORMAL': ('E7F7F0', '087F5B'), 'BAJO': ('FFF4DF', '9A5B09'),
    'MEDIA': ('FFF4DF', '9A5B09'), 'MEDIO': ('FFF4DF', '9A5B09'),
    'BAJA': ('E7F7F0', '087F5B'), 'ALTA': ('FFF0E5', 'A94708'),
    'ALTO': ('FFF0E5', 'A94708'), 'CRÍTICO': ('FDECEC', 'B42332'),
    'CRÍTICA': ('FDECEC', 'B42332'), 'AGOTADO': ('FDECEC', 'B42332'),
    'PENDIENTE': ('FFF4DF', '9A5B09'), 'REVISADA': ('EAF2FA', '214C73'),
    'JUSTIFICADA': ('E7F7F0', '087F5B'), 'ATENDIDA': ('E7F7F0', '087F5B'),
    'SIN DATOS': ('F4F7FB', '64748B'), 'ACTIVO': ('E7F7F0', '087F5B'),
    'INACTIVO': ('F4F7FB', '64748B')}

def colores_estado(valor, campo=''):
    estado = str(valor or '').upper()
    if estado in ('CRITICO', 'CRITICA'): estado = estado.replace('I', 'Í', 1)
    if campo == 'estado_stock' and estado == 'CRÍTICO': return ('FFF0E5', 'A94708')
    if campo == 'riesgo' and estado == 'BAJO': return ESTADOS['NORMAL']
    return ESTADOS.get(estado)

def ancho_columna(clave):
    if clave in ('mensaje', 'motivo', 'observacion', 'ubicaciones'): return 3.0
    if clave in ('producto', 'nombre', 'empleado', 'indicador'): return 2.2
    if clave.startswith('fecha'): return 1.7
    return 1.2
