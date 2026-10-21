"""Reservas por fuente: dos cámaras nunca comparten una captura por accidente."""
import os
from threading import RLock
from core.paths import PROJECT_ROOT

_lock=RLock()
_reservas={}


def resolver_fuente(cfg, camera_id):
    key='camera_source_employees' if camera_id==2 else 'camera_source_intrusion'
    source=cfg.get(key)
    if source is None: source=cfg['camera_source']
    env='VIGILANCIA_EMPLOYEES_VIDEO_SOURCE' if camera_id==2 else 'VIGILANCIA_VIDEO_SOURCE'
    try:
        from dotenv import dotenv_values
        source=os.getenv(env) or dotenv_values(PROJECT_ROOT/'.env',encoding='utf-8').get(env) or source
    except ImportError: source=os.getenv(env) or source
    return int(source) if isinstance(source,str) and source.isdecimal() else source


def reservar(source, owner):
    with _lock:
        key=str(source)
        if key in _reservas: raise ValueError('La fuente ya está abierta por otra cámara de Vigilancia. Seleccione otra fuente.')
        _reservas[key]=owner


def liberar(source, owner):
    with _lock:
        if _reservas.get(str(source)) is owner: _reservas.pop(str(source),None)
