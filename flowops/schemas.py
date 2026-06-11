"""
Modelos de datos (contratos de la API).

Validación de entrada/salida con Pydantic. Son los DTO que viajan por HTTP;
no se acoplan al formato interno de cada motor.
"""
from pydantic import BaseModel
from typing import Optional, Any, Dict, List


class NuevaSolicitud(BaseModel):
    empleado_id:      str
    fecha_inicio:     str
    fecha_fin:        str
    dias_solicitados: int
    motivo:           str


class AccionInstancia(BaseModel):
    actor_id:   str
    accion:     str            # "approved" | "rejected"
    comentario: Optional[str] = ""


class CompletarTarea(BaseModel):
    actor_id:   str
    accion:     str            # "approved" | "rejected"
    comentario: Optional[str] = ""


class ProcessDefinition(BaseModel):
    """Definición de proceso configurable (se persiste en MongoDB)."""
    model_config = {"extra": "allow"}
    proceso_id:   str
    nombre:       str
    nodos:        List[Dict[str, Any]]
    transiciones: List[Dict[str, Any]]
    version:      int  = 1
    activo:       bool = True
    descripcion:  Optional[str] = ""
    validaciones: Optional[Dict[str, Any]] = None


class NuevoTenant(BaseModel):
    tenant_id: str
    name:      Optional[str] = None
    plan:      Optional[str] = "demo"
