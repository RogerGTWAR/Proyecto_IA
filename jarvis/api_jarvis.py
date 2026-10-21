"""API opcional; la aplicación Tkinter no depende de este servicio."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from jarvis.agente_inventario import reiniciar_contexto
from jarvis.jarvis import procesar

app = FastAPI(title="API de Jarvis", version="1.0.0")


class ConsultaAgente(BaseModel):
    mensaje: str = Field(min_length=1, max_length=500)
    sesion: str = Field(default='escritorio',min_length=1,max_length=70,pattern=r'^[a-zA-Z0-9:_-]+$')


@app.get("/salud")
def salud():
    return {"estado": "activo", "servicio": "Jarvis"}


@app.post("/agente/consultar")
def consultar(consulta: ConsultaAgente):
    return procesar(consulta.mensaje, session_id=consulta.sesion, origen='api').to_dict()


@app.post('/agente/reiniciar')
def reiniciar(consulta: ConsultaAgente):
    reiniciar_contexto(consulta.sesion)
    return {'respuesta':'Contexto reiniciado.'}
