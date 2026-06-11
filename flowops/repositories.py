"""
Capa de acceso a datos (DAO / Repository).

Una sección por motor. Cada función encapsula UNA operación contra UN producto y
no conoce la lógica de negocio: recibe/devuelve datos planos. La capa de
servicios es la única que combina varios repositorios para cumplir un caso de uso.

Persistencia políglota:
    MongoDB   → definiciones, tenants, instancias y tareas (documental)
    Redis     → caché del estado actual (clave-valor, TTL)
    Cassandra → log de auditoría inmutable (columnar, append-only)
    Neo4j     → empleados, solicitudes y sus relaciones (grafo)
"""
import json
import uuid as _uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from . import config
from .database import (procesos_col, tenants_col, instancias_col, tareas_col,
                       rdb, cass, neo4j, clean, redis_key)

# ═══════════════════════════════════════════════════════════════
#  MongoDB — procesos y tenants  (base flowops_procesos)
# ═══════════════════════════════════════════════════════════════
def provision_process(tenant_id: str):
    """Asegura que un tenant tenga su copia del proceso estándar (clona la plantilla)."""
    if procesos_col().count_documents({"tenant_id": tenant_id, "proceso_id": config.STD_PROCESS_ID}):
        return
    template = (procesos_col().find_one({"proceso_id": config.STD_PROCESS_ID})
                or procesos_col().find_one({}))
    if not template:
        return
    doc = {k: v for k, v in template.items() if k != "_id"}
    doc["tenant_id"] = tenant_id
    procesos_col().insert_one(doc)


def ensure_form_fields():
    """Asegura que el nodo 'formulario' de cada proceso tenga campos tipados (data-driven)."""
    for p in procesos_col().find({}):
        nodos = p.get("nodos", [])
        changed = False
        for n in nodos:
            if n.get("node_id") == "formulario" or n.get("tipo") == "form":
                campos = n.get("campos")
                if not campos or isinstance(campos[0], str):   # vacío o formato viejo (strings)
                    n["campos"] = config.STD_FORM_FIELDS
                    changed = True
                else:
                    for c in n["campos"]:   # dias_solicitados → campo calculado
                        if c.get("name") == "dias_solicitados" and c.get("type") != "calculated":
                            c["type"] = "calculated"
                            c["label"] = "Días solicitados (hábiles)"
                            changed = True
        if changed:
            procesos_col().update_one({"_id": p["_id"]}, {"$set": {"nodos": nodos}})


def task_nodes(tenant_id: str) -> set:
    """node_ids cuyo tipo es 'task' según la definición del proceso."""
    doc = (procesos_col().find_one({"tenant_id": tenant_id})
           or procesos_col().find_one({}))
    if not doc:
        return {"aprobacion_gerencia"}
    nodos = {n.get("node_id") for n in doc.get("nodos", []) if n.get("tipo") == "task"}
    return nodos or {"aprobacion_gerencia"}


def listar_procesos(tenant_id: str) -> List[dict]:
    return [clean(d) for d in procesos_col().find({"tenant_id": tenant_id}, {"_id": 0})]


def get_proceso(tenant_id: str, process_id: str) -> Optional[dict]:
    doc = procesos_col().find_one({"tenant_id": tenant_id, "proceso_id": process_id}, {"_id": 0})
    return clean(doc) if doc else None


def get_proceso_primero(tenant_id: str) -> dict:
    doc = procesos_col().find_one({"tenant_id": tenant_id}, {"_id": 0})
    return clean(doc) or {}


def upsert_proceso(tenant_id: str, process_id: str, doc: dict):
    procesos_col().update_one(
        {"tenant_id": tenant_id, "proceso_id": process_id}, {"$set": doc}, upsert=True)


def count_procesos() -> int:
    return procesos_col().count_documents({})


def backfill_tenant_procesos():
    procesos_col().update_many({"tenant_id": {"$exists": False}},
                               {"$set": {"tenant_id": config.DEFAULT_TENANT}})


# ─── Tenants (entidad) ───────────────────────────────────────
def count_tenants() -> int:
    return tenants_col().count_documents({})


def seed_tenants(docs: List[dict]):
    tenants_col().insert_many(docs)


def distinct_tenants() -> List[str]:
    return tenants_col().distinct("tenant_id")


def listar_tenants() -> List[dict]:
    return [clean(d) for d in tenants_col().find({}, {"_id": 0}).sort("tenant_id", 1)]


def distinct_tenants_de_datos() -> List[str]:
    ids = set(procesos_col().distinct("tenant_id")) | set(instancias_col().distinct("tenant_id"))
    return sorted(x for x in ids if x)


def upsert_tenant(tid: str, name: str, plan: Optional[str]):
    tenants_col().update_one(
        {"tenant_id": tid},
        {"$set": {"tenant_id": tid, "name": name, "status": "active", "plan": plan},
         "$setOnInsert": {"created_at": datetime.utcnow()}},
        upsert=True)


# ═══════════════════════════════════════════════════════════════
#  MongoDB — instancias y tareas  (base flowops_instancias)
# ═══════════════════════════════════════════════════════════════
def insert_instancia(doc: dict):
    instancias_col().insert_one(doc)


def find_instancia(tenant_id: str, iid: str) -> Optional[dict]:
    return (instancias_col().find_one({"tenant_id": tenant_id, "instance_id": iid})
            or instancias_col().find_one({"instance_id": iid}))


def get_instancia(tenant_id: str, iid: str) -> Optional[dict]:
    doc = instancias_col().find_one({"tenant_id": tenant_id, "instance_id": iid}, {"_id": 0})
    return clean(doc) if doc else None


def update_instancia(iid: str, campos: dict):
    instancias_col().update_one({"instance_id": iid}, {"$set": campos})


def listar_instancias(tenant_id: str) -> List[dict]:
    return [clean(d) for d in instancias_col().find({"tenant_id": tenant_id}, {"_id": 0})]


def count_instancias() -> int:
    return instancias_col().count_documents({})


def seed_instancias(docs: List[dict]):
    instancias_col().insert_many(docs)


def backfill_tenant_instancias():
    instancias_col().update_many({"tenant_id": {"$exists": False}},
                                 {"$set": {"tenant_id": config.DEFAULT_TENANT}})


def instancias_pendientes() -> List[dict]:
    return list(instancias_col().find({"estado": {"$in": ["pendiente", "pendiente_gerencia"]}}))


# ─── Tareas humanas (entidad Task) ───────────────────────────
def make_task_id(iid: str, nodo: str) -> str:
    return f"task_{iid}_{nodo}"


def crear_task(tenant_id: str, iid: str, nodo: str, role: str = "gerencia") -> str:
    """Crea (idempotente) una tarea humana pendiente para una instancia en un nodo task."""
    tid = make_task_id(iid, nodo)
    tareas_col().update_one(
        {"task_id": tid},
        {"$setOnInsert": {
            "task_id":       tid,
            "tenant_id":     tenant_id,
            "instance_id":   iid,
            "node_id":       nodo,
            "assigned_role": role,
            "status":        "pending",
            "created_at":    datetime.utcnow(),
        }},
        upsert=True)
    return tid


def completar_task_doc(tenant_id: str, iid: str, nodo: str, actor: str, accion: str):
    """Marca como completada la tarea pendiente de (instancia, nodo)."""
    tareas_col().update_one(
        {"task_id": make_task_id(iid, nodo), "status": "pending"},
        {"$set": {
            "status":       "completed",
            "completed_at": datetime.utcnow(),
            "completed_by": actor,
            "decision":     accion,
        }})


def find_task(tenant_id: str, task_id: str) -> Optional[dict]:
    return (tareas_col().find_one({"tenant_id": tenant_id, "task_id": task_id})
            or tareas_col().find_one({"task_id": task_id}))


def listar_tareas(tenant_id: str, status: Optional[str] = None) -> List[dict]:
    q: Dict[str, Any] = {"tenant_id": tenant_id}
    if status:
        q["status"] = status
    return [clean(t) for t in tareas_col().find(q, {"_id": 0})]


# ═══════════════════════════════════════════════════════════════
#  Redis — caché del estado actual (clave-valor, TTL)
# ═══════════════════════════════════════════════════════════════
def cache_set_estado(iid: str, estado: str, nodo: str, updated_at: str, ttl: Optional[int] = None):
    rdb().hset(redis_key(iid), mapping={
        "estado": estado, "nodo_actual": nodo, "updated_at": updated_at})
    if ttl:
        rdb().expire(redis_key(iid), ttl)


def cache_get(iid: str) -> dict:
    return rdb().hgetall(redis_key(iid))


def redis_dbsize() -> int:
    return rdb().dbsize()


def redis_dump() -> dict:
    r = rdb()
    inst_keys  = sorted(r.keys("instancia:*"))
    saldo_keys = sorted(r.keys("empleado:*"))
    result = {}
    for k in inst_keys + saldo_keys:
        t = r.type(k)
        result[k] = r.hgetall(k) if t == "hash" else {"valor": r.get(k), "tipo": t}
    return result


# ═══════════════════════════════════════════════════════════════
#  Cassandra — log de auditoría (columnar, append-only)
# ═══════════════════════════════════════════════════════════════
CQL_INS = (
    "INSERT INTO flowops.eventos_instancia "
    "(tenant_id, instance_id, timestamp, event_id, nodo, actor_id, accion, detalle) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
)


def cass_event(tenant_id, iid, ts, nodo, actor, accion, detalle=None):
    cass().execute(CQL_INS, [tenant_id, iid, ts, _uuid.uuid4(), nodo, actor, accion, detalle])


def cass_eventos(tenant_id: str, iid: str) -> List[dict]:
    rows = cass().execute(
        "SELECT instance_id, timestamp, nodo, actor_id, accion, detalle "
        "FROM flowops.eventos_instancia WHERE tenant_id=%s AND instance_id=%s",
        [tenant_id, iid])
    return [{
        "instance_id": r.instance_id,
        "timestamp":   r.timestamp.isoformat() if r.timestamp else None,
        "nodo":        r.nodo, "actor_id": r.actor_id,
        "accion":      r.accion, "detalle": r.detalle
    } for r in rows]


def cass_count_eventos() -> int:
    return int(cass().execute("SELECT COUNT(*) FROM flowops.eventos_instancia").one()[0])


# ═══════════════════════════════════════════════════════════════
#  Neo4j — empleados, solicitudes y relaciones (grafo)
# ═══════════════════════════════════════════════════════════════
def graph_crear_solicitud(iid, datos, ts, eid, tenant_id):
    with neo4j().session() as sess:
        sess.run("""
            MERGE (s:Solicitud {instance_id: $iid})
            SET s.estado='pendiente', s.dias_solicitados=$dias,
                s.fecha_inicio=$fi, s.fecha_fin=$ff, s.motivo=$motivo,
                s.created_at=$ts, s.tenant_id=$tenant
            WITH s
            MATCH (e:Empleado {empleado_id: $eid})
            MERGE (e)-[:SOLICITA {timestamp: $ts}]->(s)
        """, iid=iid, dias=datos.get("dias_solicitados"), fi=datos.get("fecha_inicio"),
            ff=datos.get("fecha_fin"), motivo=datos.get("motivo"),
            ts=ts, eid=eid, tenant=tenant_id)


def graph_decision(iid, actor_id, accion, ts, comentario, nuevo_estado):
    rel = "APRUEBA" if accion == "approved" else "RECHAZA"
    with neo4j().session() as sess:
        sess.run(
            f"MATCH (s:Solicitud {{instance_id:$iid}}),(e:Empleado {{empleado_id:$eid}}) "
            f"MERGE (e)-[:{rel} {{timestamp:$ts,comentario:$c}}]->(s) SET s.estado=$est",
            iid=iid, eid=actor_id, ts=ts, c=comentario or "", est=nuevo_estado)


def graph_empleados() -> List[dict]:
    with neo4j().session() as s:
        res = s.run("""
            MATCH (e:Empleado)
            OPTIONAL MATCH (e)-[:TIENE_ROL]->(r:Rol)
            RETURN e.empleado_id AS id, e.nombre AS nombre,
                   e.departamento AS dep, e.saldo_dias AS saldo, r.nombre AS rol
            ORDER BY e.nombre
        """)
        return [dict(r) for r in res]


def graph_grafo() -> List[dict]:
    with neo4j().session() as s:
        res = s.run("""
            MATCH (e:Empleado)-[r]->(sol:Solicitud)
            RETURN e.nombre AS empleado, e.departamento AS depto,
                   type(r) AS relacion, sol.instance_id AS instancia,
                   sol.estado AS estado, sol.dias_solicitados AS dias,
                   sol.fecha_inicio AS fecha_inicio
            ORDER BY sol.instance_id, type(r)
        """)
        return [dict(r) for r in res]


def graph_counts() -> dict:
    with neo4j().session() as s:
        nodos = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        rels  = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
    return {"nodos": nodos, "relaciones": rels}
