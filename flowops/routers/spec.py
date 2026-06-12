"""
Capa de presentación — Rutas del spec (multi-tenant).

API mínima pedida por el TPO: /api/{tenant_id}/processes · …/instances ·
…/tasks · …/events. Los handlers son finos: validan la entrada y delegan en la
capa de servicios o de repositorios.
"""
from fastapi import APIRouter, HTTPException, Body
from typing import Optional, Any, Dict
from datetime import datetime

from .. import repositories as repo, services
from ..schemas import CompletarTarea

router = APIRouter(tags=["spec (multi-tenant)"])


@router.post("/api/{tenant_id}/processes", status_code=201)
def crear_proceso(tenant_id: str, payload: Dict[str, Any] = Body(...)):
    """Crea/actualiza una definición de proceso configurable (MongoDB)."""
    pid = payload.get("proceso_id") or payload.get("process_id")
    if not pid:
        raise HTTPException(400, "Falta 'proceso_id' en el cuerpo")
    doc = dict(payload)
    doc["tenant_id"]  = tenant_id
    doc["proceso_id"] = pid
    doc.setdefault("version", 1)
    doc.setdefault("activo", True)
    doc.setdefault("created_at", datetime.utcnow())
    try:
        repo.upsert_proceso(tenant_id, pid, doc)
    except Exception as e:
        raise HTTPException(500, str(e))
    # Refleja la topología a Neo4j y valida los caminos (best-effort)
    validacion = services.publicar_proceso(tenant_id, pid, doc.get("nodos"), doc.get("transiciones"))
    return {"ok": True, "tenant_id": tenant_id, "proceso_id": pid, "validacion": validacion}


@router.get("/api/{tenant_id}/processes")
def listar_procesos(tenant_id: str):
    try:
        return repo.listar_procesos(tenant_id)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/{tenant_id}/processes/{process_id}")
def get_proceso_tenant(tenant_id: str, process_id: str):
    try:
        doc = repo.get_proceso(tenant_id, process_id)
        if not doc:
            raise HTTPException(404, "Proceso no encontrado")
        return doc
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/api/{tenant_id}/processes/{process_id}/instances", status_code=201)
def crear_instancia_tenant(tenant_id: str, process_id: str, body: Dict[str, Any] = Body(...)):
    emp, datos = services.extract_solicitud(body)
    return services.core_crear_instancia(tenant_id, emp, datos, process_id)


@router.get("/api/{tenant_id}/instances/{instance_id}")
def get_instance_tenant(tenant_id: str, instance_id: str):
    try:
        doc = repo.get_instancia(tenant_id, instance_id)
        if not doc:
            raise HTTPException(404, "Instancia no encontrada")
        try:
            doc["redis"] = repo.cache_get(instance_id)
        except Exception:
            pass
        return doc
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/{tenant_id}/instances/{instance_id}/events")
def eventos_tenant(tenant_id: str, instance_id: str):
    try:
        return services.core_eventos(tenant_id, instance_id)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/{tenant_id}/events/by-date")
def eventos_por_fecha(tenant_id: str, date: str):
    """Reporte de auditoría del tenant en una fecha (YYYY-MM-DD). Tabla particionada
    por (tenant_id, fecha) en Cassandra: una sola partición, sin afectar a otros tenants."""
    from datetime import date as _date
    try:
        f = _date.fromisoformat(date)
    except Exception:
        raise HTTPException(400, "Parámetro 'date' debe ser YYYY-MM-DD")
    try:
        return repo.cass_eventos_por_fecha(tenant_id, f)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/{tenant_id}/tasks")
def listar_tareas(tenant_id: str, status: Optional[str] = None):
    """Lista las tareas humanas del tenant (opcional ?status=pending|completed)."""
    try:
        return repo.listar_tareas(tenant_id, status)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/api/{tenant_id}/tasks/{task_id}/complete")
def completar_tarea(tenant_id: str, task_id: str, body: CompletarTarea):
    """Completa una tarea humana y avanza la instancia asociada."""
    return services.core_completar_tarea(tenant_id, task_id, body.actor_id, body.accion, body.comentario or "")
