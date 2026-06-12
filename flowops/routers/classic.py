"""
Capa de presentación — Rutas clásicas (tenant por defecto) + operación.

Las usa el frontend (operan sobre ?tenant= o empresa_01). Incluye el health
check con evaluación de conectividad por motor (Clase 13), el alta de empresas
(entidad Tenant) y las consultas a Redis/Neo4j que alimentan las vistas.
"""
import time
from fastapi import APIRouter, HTTPException, Body
from typing import Optional, Any, Dict

from .. import config, repositories as repo, services
from ..schemas import AccionInstancia, NuevoTenant
from ..database import mongo_proc, rdb

router = APIRouter(tags=["clásicas (frontend)"])


# ─── Health check / evaluación de conectividad ───────────────
@router.get("/api/status")
def api_status():
    """Health check + evaluación de conectividad: mide la latencia (ms) de cada motor.
    (Clase 13 — Evaluación de la conectividad a los distintos productos.)"""
    out = {}

    def measure(key, label, fn):
        t0 = time.perf_counter()
        try:
            extra = fn() or {}
            out[key] = {"ok": True, "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                        "label": label, **extra}
        except Exception as e:
            out[key] = {"ok": False, "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                        "error": str(e), "label": label}

    def f_proc():
        mongo_proc().admin.command("ping")
        return {"docs": repo.count_procesos()}
    measure("mongodb_procesos", "MongoDB Procesos", f_proc)

    measure("mongodb_instancias", "MongoDB Instancias",
            lambda: {"docs": repo.count_instancias()})

    def f_redis():
        rdb().ping()
        return {"keys": repo.redis_dbsize()}
    measure("redis", "Redis Caché", f_redis)

    measure("cassandra", "Cassandra Auditoría",
            lambda: {"docs": repo.cass_count_eventos()})

    measure("neo4j", "Neo4j Grafo", repo.graph_counts)

    return out


# ─── Tenants (entidad) ───────────────────────────────────────
@router.get("/api/tenants")
def listar_tenants():
    """Lista las empresas (entidad Tenant) para el selector del frontend."""
    try:
        docs = repo.listar_tenants()
        if docs:
            return docs
        # Fallback: derivar de los datos si aún no hay colección tenants
        ids = repo.distinct_tenants_de_datos()
        return [{"tenant_id": x, "name": x, "status": "active"} for x in ids] \
               or [{"tenant_id": config.DEFAULT_TENANT, "name": config.DEFAULT_TENANT, "status": "active"}]
    except Exception:
        return [{"tenant_id": config.DEFAULT_TENANT, "name": config.DEFAULT_TENANT, "status": "active"}]


@router.post("/api/tenants", status_code=201)
def crear_tenant(body: NuevoTenant):
    """Crea una empresa y le aprovisiona el proceso estándar."""
    tid = (body.tenant_id or "").strip()
    if not tid:
        raise HTTPException(400, "Falta 'tenant_id'")
    try:
        repo.upsert_tenant(tid, body.name or tid, body.plan)
        repo.provision_process(tid)  # la empresa nueva arranca con "Solicitud de Vacaciones"
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"ok": True, "tenant_id": tid, "name": body.name or tid}


# ─── Proceso / instancias (tenant por defecto) ───────────────
@router.get("/api/proceso")
def get_proceso(tenant: str = config.DEFAULT_TENANT):
    """Definición del proceso con cache-aside en Redis (TTL 15 min)."""
    try:
        return services.get_proceso_cached(tenant)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/instancias")
def get_instancias(tenant: str = config.DEFAULT_TENANT):
    try:
        docs = repo.listar_instancias(tenant)
        for d in docs:
            try:
                st = repo.cache_get(d["instance_id"])
                d["redis_estado"]  = st.get("estado",      "")
                d["redis_nodo"]    = st.get("nodo_actual", "")
                d["redis_updated"] = st.get("updated_at",  "")
            except Exception:
                pass
        orden = {"pendiente": 0, "pendiente_gerencia": 1, "aprobada": 2, "rechazada": 3}
        docs.sort(key=lambda x: orden.get(x.get("redis_estado") or x.get("estado", ""), 9))
        return docs
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/instancias/{iid}")
def get_instancia(iid: str, tenant: str = config.DEFAULT_TENANT):
    try:
        doc = repo.get_instancia(tenant, iid)
        if not doc:
            raise HTTPException(404, "Instancia no encontrada")
        try:
            doc["redis"] = repo.cache_get(iid)
        except Exception:
            pass
        return doc
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/instancias/{iid}/eventos")
def get_eventos(iid: str, tenant: str = config.DEFAULT_TENANT):
    try:
        return services.core_eventos(tenant, iid)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/api/instancias", status_code=201)
def crear_instancia(body: Dict[str, Any] = Body(...), tenant: str = config.DEFAULT_TENANT):
    emp, datos = services.extract_solicitud(body)
    return services.core_crear_instancia(tenant, emp, datos)


@router.post("/api/instancias/{iid}/avanzar")
def avanzar(iid: str, body: AccionInstancia, tenant: str = config.DEFAULT_TENANT):
    return services.core_avanzar(tenant, iid, body.actor_id, body.accion, body.comentario or "")


# ─── Neo4j / Redis (vistas del frontend) ─────────────────────
@router.get("/api/empleados")
def get_empleados():
    try:
        return repo.graph_empleados()
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/grafo")
def get_grafo():
    try:
        return repo.graph_grafo()
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/redis")
def get_redis_state():
    try:
        return repo.redis_dump()
    except Exception as e:
        raise HTTPException(500, str(e))
