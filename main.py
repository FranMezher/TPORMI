"""
FlowOps API — TPO Ingeniería de Datos II
FastAPI backend conectado a MongoDB (x2), Redis, Cassandra y Neo4j.

Multi-tenant: todos los datos principales llevan `tenant_id`.
Expone dos familias de rutas equivalentes:
  · Rutas "clásicas"  (/api/proceso, /api/instancias, …) usadas por el frontend,
    que operan sobre el tenant por defecto (empresa_01).
  · Rutas del spec    (/api/{tenant_id}/processes, …/instances, …/tasks, …/events)
    multi-tenant, según la API mínima pedida por el TPO.

Flujo del proceso (load_all):
  start → formulario → validacion_saldo
      saldo_ok       → aprobacion_gerencia → notif_aprobacion → end
      saldo_insuf.   →                       notif_rechazo    → end

Contenedores Docker (docker-compose / load_all):
  flowops-instancias → MongoDB    → localhost:27018  (bases: flowops_procesos + flowops_instancias)
  flowops-cache      → Redis      → localhost:6379
  flowops-auditoria  → Cassandra  → localhost:9042   keyspace: flowops
  flowops-grafo      → Neo4j      → bolt://localhost:7687
"""

from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Any, Dict, List
from datetime import datetime, timedelta
import json, os, uuid as _uuid

# ─── App ─────────────────────────────────────────────────────
app = FastAPI(title="FlowOps API", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

# ─── Config ──────────────────────────────────────────────────
# Una sola instancia MongoDB en 27018 aloja ambas bases lógicas
# (flowops_procesos y flowops_instancias). Se mantienen dos URLs por claridad.
MONGO_PROC_URL = os.getenv("MONGO_PROC_URL",
    "mongodb://admin:flowops123@localhost:27018/?authSource=admin")
MONGO_INST_URL = os.getenv("MONGO_INST_URL",
    "mongodb://admin:flowops123@localhost:27018/?authSource=admin")
REDIS_HOST     = os.getenv("REDIS_HOST",     "localhost")
REDIS_PORT     = int(os.getenv("REDIS_PORT", "6379"))
CASS_HOST      = os.getenv("CASSANDRA_HOST", "localhost")
NEO4J_URI      = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASS     = os.getenv("NEO4J_PASS",     "flowops123")

# Tenant por defecto (igual que en load_all → "empresa_01")
DEFAULT_TENANT = "empresa_01"
TENANT_ID = DEFAULT_TENANT  # compat

# ─── Conexiones lazy ─────────────────────────────────────────
_c = {}

def mongo_proc():
    if "mp" not in _c:
        import pymongo
        _c["mp"] = pymongo.MongoClient(MONGO_PROC_URL, serverSelectionTimeoutMS=3000)
    return _c["mp"]

def mongo_inst():
    if "mi" not in _c:
        import pymongo
        _c["mi"] = pymongo.MongoClient(MONGO_INST_URL, serverSelectionTimeoutMS=3000)
    return _c["mi"]

def rdb():
    if "r" not in _c:
        import redis
        _c["r"] = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    return _c["r"]

def cass():
    if "c" not in _c:
        from cassandra.cluster import Cluster
        _c["c"] = Cluster([CASS_HOST]).connect("flowops")
    return _c["c"]

def neo4j():
    if "n" not in _c:
        from neo4j import GraphDatabase
        _c["n"] = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    return _c["n"]

# ─── Accesos a colecciones ───────────────────────────────────
def procesos_col():   return mongo_proc()["flowops_procesos"]["procesos"]
def tenants_col():    return mongo_proc()["flowops_procesos"]["tenants"]
def instancias_col(): return mongo_inst()["flowops_instancias"]["instancias"]
def tareas_col():     return mongo_inst()["flowops_instancias"]["tareas"]

# Proceso estándar que toda empresa tiene disponible
STD_PROCESS_ID = "proc_vacaciones_v1"

# Campos del formulario (data-driven): el frontend los renderiza desde la definición.
# Agregar un campo acá (o vía la API/Compass) hace que aparezca en el form sin tocar código.
STD_FORM_FIELDS = [
    {"name": "empleado_id",      "label": "Empleado ID",      "type": "text",     "required": True,  "placeholder": "emp_001"},
    {"name": "fecha_inicio",     "label": "Fecha inicio",     "type": "date",     "required": True},
    {"name": "fecha_fin",        "label": "Fecha fin",        "type": "date",     "required": True},
    {"name": "dias_solicitados", "label": "Días solicitados (hábiles)", "type": "calculated", "required": True},
    {"name": "motivo",           "label": "Motivo",           "type": "textarea", "required": False, "placeholder": "Vacaciones anuales"},
]

def dias_habiles(fi, ff):
    """Días hábiles (lun–vie) entre dos fechas ISO, inclusive. None si inválidas."""
    from datetime import date
    try:
        d0 = date.fromisoformat(str(fi)[:10])
        d1 = date.fromisoformat(str(ff)[:10])
    except Exception:
        return None
    if d1 < d0:
        return 0
    n, cur = 0, d0
    while cur <= d1:
        if cur.weekday() < 5:   # 0=lun … 4=vie
            n += 1
        cur += timedelta(days=1)
    return n

def _extract_solicitud(body: Dict[str, Any]):
    """Acepta {empleado_id, datos:{...}} o un objeto plano; devuelve (empleado_id, datos)."""
    if not isinstance(body, dict):
        raise HTTPException(400, "Cuerpo inválido")
    if isinstance(body.get("datos"), dict):
        datos = dict(body["datos"])
        empleado_id = body.get("empleado_id") or datos.get("empleado_id")
    else:
        empleado_id = body.get("empleado_id")
        datos = {k: v for k, v in body.items() if k != "empleado_id"}
    datos.pop("empleado_id", None)
    if not empleado_id:
        raise HTTPException(400, "Falta 'empleado_id'")
    # dias_solicitados es CALCULADO: se deriva de las fechas, no se confía en el cliente
    if datos.get("fecha_inicio") and datos.get("fecha_fin"):
        d = dias_habiles(datos["fecha_inicio"], datos["fecha_fin"])
        if d is not None:
            datos["dias_solicitados"] = d
    return empleado_id, datos

def provision_process(tenant_id: str):
    """Asegura que un tenant tenga su copia del proceso estándar (clona la plantilla)."""
    if procesos_col().count_documents({"tenant_id": tenant_id, "proceso_id": STD_PROCESS_ID}):
        return
    template = (procesos_col().find_one({"proceso_id": STD_PROCESS_ID})
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
                    n["campos"] = STD_FORM_FIELDS
                    changed = True
                else:
                    for c in n["campos"]:   # dias_solicitados → campo calculado
                        if c.get("name") == "dias_solicitados" and c.get("type") != "calculated":
                            c["type"] = "calculated"
                            c["label"] = "Días solicitados (hábiles)"
                            changed = True
        if changed:
            procesos_col().update_one({"_id": p["_id"]}, {"$set": {"nodos": nodos}})

# ─── Helpers ─────────────────────────────────────────────────
def clean(obj):
    """Serializa documentos MongoDB (elimina _id, convierte datetime)."""
    if obj is None:        return None
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items() if k != "_id"}
    if isinstance(obj, list):
        return [clean(i) for i in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj

def redis_key(iid: str) -> str:
    """Formato de clave Redis: instancia:{id}  (igual que en load_all)"""
    return f"instancia:{iid}"

# ─── Lógica de flujo ─────────────────────────────────────────
def sig_nodo(nodo: str, accion: str) -> tuple:
    """Retorna (nodo_siguiente, nuevo_estado). El avance manual ocurre en aprobacion_gerencia."""
    if nodo == "aprobacion_gerencia":
        if accion == "approved":
            return ("notif_aprobacion", "aprobada")
        return ("notif_rechazo", "rechazada")
    if nodo in ("notif_aprobacion", "notif_rechazo"):
        return ("end", "finalizada")
    return ("end", "finalizada")

# ─── Tareas humanas (entidad Task) ───────────────────────────
def task_nodes(tenant_id: str) -> set:
    """node_ids cuyo tipo es 'task' según la definición del proceso."""
    doc = (procesos_col().find_one({"tenant_id": tenant_id})
           or procesos_col().find_one({}))
    if not doc:
        return {"aprobacion_gerencia"}
    nodos = {n.get("node_id") for n in doc.get("nodos", []) if n.get("tipo") == "task"}
    return nodos or {"aprobacion_gerencia"}

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

# ─── Cassandra helpers ───────────────────────────────────────
CQL_INS = (
    "INSERT INTO flowops.eventos_instancia "
    "(tenant_id, instance_id, timestamp, event_id, nodo, actor_id, accion, detalle) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
)

def cass_event(tenant_id, iid, ts, nodo, actor, accion, detalle=None):
    cass().execute(CQL_INS, [tenant_id, iid, ts, _uuid.uuid4(), nodo, actor, accion, detalle])

# ─── Modelos ─────────────────────────────────────────────────
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

# ═══════════════════════════════════════════════════════════════
#  LÓGICA CORE (tenant-aware) — reutilizada por ambas familias de rutas
# ═══════════════════════════════════════════════════════════════
def core_crear_instancia(tenant_id: str, empleado_id: str, datos: Dict[str, Any],
                         process_id: str = "proc_vacaciones_v1") -> dict:
    datos = dict(datos or {})
    now   = datetime.utcnow()
    iid   = "inst_vac_" + now.strftime("%Y%m%d_%H%M%S")
    warns = []

    # 1. MongoDB ─────────────────────────────────────────────
    try:
        instancias_col().insert_one({
            "tenant_id":      tenant_id,
            "instance_id":    iid,
            "proceso_id":     process_id,
            "solicitante_id": empleado_id,
            "estado":         "pendiente",
            "nodo_actual":    "aprobacion_gerencia",  # tras validacion_saldo automática
            "datos":          datos,                  # flexible: lo que defina el formulario
            "created_at": now, "updated_at": now
        })
    except Exception as e:
        raise HTTPException(500, f"MongoDB: {e}")

    # 1b. Tarea humana pendiente (entidad Task)
    task_id = None
    try:
        task_id = crear_task(tenant_id, iid, "aprobacion_gerencia", role="gerencia")
    except Exception as e:
        warns.append(f"Task: {e}")

    # 2. Redis ────────────────────────────────────────────────
    try:
        rdb().hset(redis_key(iid), mapping={
            "estado": "pendiente", "nodo_actual": "aprobacion_gerencia",
            "updated_at": now.isoformat()
        })
        rdb().expire(redis_key(iid), 86400)
    except Exception as e:
        warns.append(f"Redis: {e}")

    # 3. Cassandra ────────────────────────────────────────────
    try:
        cass_event(tenant_id, iid, now,                        "start",            None,        "inicio_proceso",     None)
        cass_event(tenant_id, iid, now + timedelta(seconds=1), "formulario",       empleado_id, "formulario_enviado",
                   json.dumps(datos))
        cass_event(tenant_id, iid, now + timedelta(seconds=2), "validacion_saldo", "sistema",   "saldo_suficiente",
                   json.dumps({"dias_solicitados": datos.get("dias_solicitados")}))
        cass_event(tenant_id, iid, now + timedelta(seconds=3), "aprobacion_gerencia", "sistema",        "tarea_asignada",
                   json.dumps({"asignado_a_rol": "gerencia", "task_id": task_id}))
    except Exception as e:
        warns.append(f"Cassandra: {e}")

    # 4. Neo4j ────────────────────────────────────────────────
    try:
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
                ts=now.isoformat(), eid=empleado_id, tenant=tenant_id)
    except Exception as e:
        warns.append(f"Neo4j: {e}")

    return {"ok": True, "instance_id": iid, "task_id": task_id, "warnings": warns}


def core_avanzar(tenant_id: str, iid: str, actor_id: str, accion: str, comentario: str = "") -> dict:
    # Buscar la instancia (preferente por tenant, con fallback)
    doc = (instancias_col().find_one({"tenant_id": tenant_id, "instance_id": iid})
           or instancias_col().find_one({"instance_id": iid}))
    if not doc:
        raise HTTPException(404, "Instancia no encontrada")

    estado_actual = doc.get("estado")
    nodo_actual   = doc.get("nodo_actual", "aprobacion_gerencia")

    # Idempotencia / estado inválido (CAP: evita doble avance / doble completar tarea)
    if nodo_actual == "end" or estado_actual not in ("pendiente", "pendiente_gerencia"):
        raise HTTPException(409,
            f"La instancia ya fue avanzada (estado={estado_actual}, nodo={nodo_actual})")

    nodo_sig, nuevo_estado = sig_nodo(nodo_actual, accion)
    now   = datetime.utcnow()
    warns = []

    # El nodo de notificación es AUTOMÁTICO → la instancia encadena hasta 'end'
    notif_node = nodo_sig if nodo_sig in ("notif_aprobacion", "notif_rechazo") else None
    final_nodo = "end" if notif_node else nodo_sig

    # 1. MongoDB
    try:
        instancias_col().update_one(
            {"instance_id": iid},
            {"$set": {"estado": nuevo_estado, "nodo_actual": final_nodo, "updated_at": now}})
    except Exception as e:
        raise HTTPException(500, f"MongoDB: {e}")

    # 1b. Completar tarea humana si el nodo de origen era una tarea
    try:
        if nodo_actual in task_nodes(tenant_id):
            completar_task_doc(tenant_id, iid, nodo_actual, actor_id, accion)
    except Exception as e:
        warns.append(f"Task: {e}")

    # 2. Redis
    try:
        rdb().hset(redis_key(iid), mapping={
            "estado": nuevo_estado, "nodo_actual": final_nodo, "updated_at": now.isoformat()})
    except Exception as e:
        warns.append(f"Redis: {e}")

    # 3. Cassandra: decisión → notificación (automática) → fin
    try:
        cass_event(tenant_id, iid, now, nodo_actual, actor_id, accion, comentario or "")
        if notif_node:
            dest = [doc.get("solicitante_id", "")]
            if notif_node == "notif_aprobacion":
                dest.append("emp_002")  # RRHH también recibe aprobación
            cass_event(tenant_id, iid, now + timedelta(seconds=1), notif_node, "sistema",
                       "notificacion_enviada", json.dumps({"destinatarios": dest}))
            cass_event(tenant_id, iid, now + timedelta(seconds=2), "end", None,
                       "proceso_finalizado", None)
    except Exception as e:
        warns.append(f"Cassandra: {e}")

    # 4. Neo4j
    try:
        rel = "APRUEBA" if accion == "approved" else "RECHAZA"
        with neo4j().session() as sess:
            sess.run(
                f"MATCH (s:Solicitud {{instance_id:$iid}}),(e:Empleado {{empleado_id:$eid}}) "
                f"MERGE (e)-[:{rel} {{timestamp:$ts,comentario:$c}}]->(s) SET s.estado=$est",
                iid=iid, eid=actor_id, ts=now.isoformat(), c=comentario or "", est=nuevo_estado)
    except Exception as e:
        warns.append(f"Neo4j: {e}")

    return {"ok": True, "nodo_anterior": nodo_actual, "nodo_actual": final_nodo,
            "notif_node": notif_node, "estado": nuevo_estado, "warnings": warns}


def core_completar_tarea(tenant_id: str, task_id: str, actor_id: str, accion: str, comentario: str = "") -> dict:
    t = (tareas_col().find_one({"tenant_id": tenant_id, "task_id": task_id})
         or tareas_col().find_one({"task_id": task_id}))
    if not t:
        raise HTTPException(404, "Tarea no encontrada")
    if t.get("status") == "completed":
        raise HTTPException(409, "La tarea ya fue completada")
    res = core_avanzar(tenant_id, t["instance_id"], actor_id, accion, comentario)
    res["task_id"] = task_id
    return res


def core_eventos(tenant_id: str, iid: str) -> list:
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

# ═══════════════════════════════════════════════════════════════
# STARTUP — seed + migración tenant_id + tareas pendientes
# ═══════════════════════════════════════════════════════════════
@app.on_event("startup")
def seed_and_migrate():
    try:
        col = instancias_col()
        if col.count_documents({}) == 0:
            base = {"proceso_id": "proc_vacaciones_v1", "tenant_id": DEFAULT_TENANT}
            col.insert_many([
                {**base, "instance_id": "inst_vac_2026_001", "solicitante_id": "emp_001",
                 "estado": "aprobada", "nodo_actual": "end",
                 "datos": {"fecha_inicio": "2026-07-01", "fecha_fin": "2026-07-18",
                           "dias_solicitados": 15, "motivo": "Vacaciones anuales"},
                 "created_at": datetime(2026, 6, 10, 9, 0), "updated_at": datetime(2026, 6, 10, 11, 1)},
                {**base, "instance_id": "inst_vac_2026_002", "solicitante_id": "emp_004",
                 "estado": "rechazada", "nodo_actual": "end",
                 "datos": {"fecha_inicio": "2026-07-15", "fecha_fin": "2026-07-29",
                           "dias_solicitados": 12, "motivo": "Vacaciones"},
                 "created_at": datetime(2026, 6, 11, 10, 0), "updated_at": datetime(2026, 6, 11, 10, 3)},
                {**base, "instance_id": "inst_vac_2026_003", "solicitante_id": "emp_005",
                 "estado": "pendiente", "nodo_actual": "aprobacion_gerencia",
                 "datos": {"fecha_inicio": "2026-08-01", "fecha_fin": "2026-08-07",
                           "dias_solicitados": 5, "motivo": "Vacaciones de invierno"},
                 "created_at": datetime(2026, 6, 12, 8, 0), "updated_at": datetime(2026, 6, 12, 8, 3)},
            ])
        # Migración: backfill tenant_id en datos preexistentes
        col.update_many({"tenant_id": {"$exists": False}}, {"$set": {"tenant_id": DEFAULT_TENANT}})
        procesos_col().update_many({"tenant_id": {"$exists": False}}, {"$set": {"tenant_id": DEFAULT_TENANT}})
        # Entidad Tenant: seed de empresas demo si la colección está vacía
        tcol = tenants_col()
        if tcol.count_documents({}) == 0:
            tcol.insert_many([
                {"tenant_id": "empresa_01", "name": "Grupo 7 S.A.",   "status": "active", "plan": "demo", "created_at": datetime.utcnow()},
                {"tenant_id": "empresa_02", "name": "Acme Logística",  "status": "active", "plan": "demo", "created_at": datetime.utcnow()},
                {"tenant_id": "empresa_03", "name": "Delta Salud",     "status": "active", "plan": "demo", "created_at": datetime.utcnow()},
            ])
        # Cada empresa tiene aprovisionado el proceso estándar "Solicitud de Vacaciones"
        for t in tcol.distinct("tenant_id"):
            provision_process(t)
        # Form data-driven: asegurar campos tipados en el nodo formulario de cada proceso
        ensure_form_fields()
        # Crear tareas pendientes para instancias detenidas en un nodo task
        tnodes = task_nodes(DEFAULT_TENANT)
        for d in col.find({"estado": {"$in": ["pendiente", "pendiente_gerencia"]}}):
            if d.get("nodo_actual") in tnodes:
                crear_task(d.get("tenant_id", DEFAULT_TENANT), d["instance_id"], d["nodo_actual"])
    except Exception:
        pass  # Si no conecta al inicio, no hay problema

# ═══════════════════════════════════════════════════════════════
# FRONTEND
# ═══════════════════════════════════════════════════════════════
@app.get("/", response_class=HTMLResponse)
def frontend():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    with open(path, encoding="utf-8") as f:
        return f.read()

# ═══════════════════════════════════════════════════════════════
# RUTAS DEL SPEC (multi-tenant) — API mínima del TPO
# ═══════════════════════════════════════════════════════════════
@app.post("/api/{tenant_id}/processes", status_code=201)
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
        procesos_col().update_one(
            {"tenant_id": tenant_id, "proceso_id": pid}, {"$set": doc}, upsert=True)
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"ok": True, "tenant_id": tenant_id, "proceso_id": pid}

@app.get("/api/{tenant_id}/processes")
def listar_procesos(tenant_id: str):
    try:
        return [clean(d) for d in procesos_col().find({"tenant_id": tenant_id}, {"_id": 0})]
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/api/{tenant_id}/processes/{process_id}")
def get_proceso_tenant(tenant_id: str, process_id: str):
    try:
        doc = procesos_col().find_one({"tenant_id": tenant_id, "proceso_id": process_id}, {"_id": 0})
        if not doc:
            raise HTTPException(404, "Proceso no encontrado")
        return clean(doc)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/api/{tenant_id}/processes/{process_id}/instances", status_code=201)
def crear_instancia_tenant(tenant_id: str, process_id: str, body: Dict[str, Any] = Body(...)):
    emp, datos = _extract_solicitud(body)
    return core_crear_instancia(tenant_id, emp, datos, process_id)

@app.get("/api/{tenant_id}/instances/{instance_id}")
def get_instance_tenant(tenant_id: str, instance_id: str):
    try:
        doc = instancias_col().find_one({"tenant_id": tenant_id, "instance_id": instance_id}, {"_id": 0})
        if not doc:
            raise HTTPException(404, "Instancia no encontrada")
        doc = clean(doc)
        try:
            doc["redis"] = rdb().hgetall(redis_key(instance_id))
        except Exception:
            pass
        return doc
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/api/{tenant_id}/instances/{instance_id}/events")
def eventos_tenant(tenant_id: str, instance_id: str):
    try:
        return core_eventos(tenant_id, instance_id)
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/api/{tenant_id}/tasks")
def listar_tareas(tenant_id: str, status: Optional[str] = None):
    """Lista las tareas humanas del tenant (opcional ?status=pending|completed)."""
    try:
        q: Dict[str, Any] = {"tenant_id": tenant_id}
        if status:
            q["status"] = status
        return [clean(t) for t in tareas_col().find(q, {"_id": 0})]
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/api/{tenant_id}/tasks/{task_id}/complete")
def completar_tarea(tenant_id: str, task_id: str, body: CompletarTarea):
    """Completa una tarea humana y avanza la instancia asociada."""
    return core_completar_tarea(tenant_id, task_id, body.actor_id, body.accion, body.comentario or "")

# ═══════════════════════════════════════════════════════════════
# RUTAS CLÁSICAS (tenant por defecto) — usadas por el frontend
# ═══════════════════════════════════════════════════════════════
@app.get("/api/status")
def api_status():
    out = {}
    try:
        mongo_proc().admin.command("ping")
        n = procesos_col().count_documents({})
        out["mongodb_procesos"] = {"ok": True, "docs": n, "label": "MongoDB Procesos"}
    except Exception as e:
        out["mongodb_procesos"] = {"ok": False, "error": str(e), "label": "MongoDB Procesos"}
    try:
        n = instancias_col().count_documents({})
        out["mongodb_instancias"] = {"ok": True, "docs": n, "label": "MongoDB Instancias"}
    except Exception as e:
        out["mongodb_instancias"] = {"ok": False, "error": str(e), "label": "MongoDB Instancias"}
    try:
        rdb().ping()
        out["redis"] = {"ok": True, "keys": rdb().dbsize(), "label": "Redis Caché"}
    except Exception as e:
        out["redis"] = {"ok": False, "error": str(e), "label": "Redis Caché"}
    try:
        n = cass().execute("SELECT COUNT(*) FROM flowops.eventos_instancia").one()[0]
        out["cassandra"] = {"ok": True, "docs": int(n), "label": "Cassandra Auditoría"}
    except Exception as e:
        out["cassandra"] = {"ok": False, "error": str(e), "label": "Cassandra Auditoría"}
    try:
        with neo4j().session() as s:
            nodos = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            rels  = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        out["neo4j"] = {"ok": True, "nodos": nodos, "relaciones": rels, "label": "Neo4j Grafo"}
    except Exception as e:
        out["neo4j"] = {"ok": False, "error": str(e), "label": "Neo4j Grafo"}
    return out

class NuevoTenant(BaseModel):
    tenant_id: str
    name:      Optional[str] = None
    plan:      Optional[str] = "demo"

@app.get("/api/tenants")
def listar_tenants():
    """Lista las empresas (entidad Tenant) para el selector del frontend."""
    try:
        docs = [clean(d) for d in tenants_col().find({}, {"_id": 0}).sort("tenant_id", 1)]
        if docs:
            return docs
        # Fallback: derivar de los datos si aún no hay colección tenants
        ids = set(procesos_col().distinct("tenant_id")) | set(instancias_col().distinct("tenant_id"))
        return [{"tenant_id": x, "name": x, "status": "active"} for x in sorted(ids) if x] \
               or [{"tenant_id": DEFAULT_TENANT, "name": DEFAULT_TENANT, "status": "active"}]
    except Exception:
        return [{"tenant_id": DEFAULT_TENANT, "name": DEFAULT_TENANT, "status": "active"}]

@app.post("/api/tenants", status_code=201)
def crear_tenant(body: NuevoTenant):
    """Crea una empresa y le aprovisiona el proceso estándar."""
    tid = (body.tenant_id or "").strip()
    if not tid:
        raise HTTPException(400, "Falta 'tenant_id'")
    try:
        tenants_col().update_one(
            {"tenant_id": tid},
            {"$set": {"tenant_id": tid, "name": body.name or tid, "status": "active", "plan": body.plan},
             "$setOnInsert": {"created_at": datetime.utcnow()}},
            upsert=True)
        provision_process(tid)  # la empresa nueva arranca con "Solicitud de Vacaciones"
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"ok": True, "tenant_id": tid, "name": body.name or tid}

@app.get("/api/proceso")
def get_proceso(tenant: str = DEFAULT_TENANT):
    try:
        doc = procesos_col().find_one({"tenant_id": tenant}, {"_id": 0})
        return clean(doc) or {}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/api/instancias")
def get_instancias(tenant: str = DEFAULT_TENANT):
    try:
        docs = [clean(d) for d in
                instancias_col().find({"tenant_id": tenant}, {"_id": 0})]
        for d in docs:
            try:
                st = rdb().hgetall(redis_key(d["instance_id"]))
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

@app.get("/api/instancias/{iid}")
def get_instancia(iid: str, tenant: str = DEFAULT_TENANT):
    try:
        doc = instancias_col().find_one(
            {"tenant_id": tenant, "instance_id": iid}, {"_id": 0})
        if not doc:
            raise HTTPException(404, "Instancia no encontrada")
        doc = clean(doc)
        try:
            doc["redis"] = rdb().hgetall(redis_key(iid))
        except Exception:
            pass
        return doc
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/api/instancias/{iid}/eventos")
def get_eventos(iid: str, tenant: str = DEFAULT_TENANT):
    try:
        return core_eventos(tenant, iid)
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/api/instancias", status_code=201)
def crear_instancia(body: Dict[str, Any] = Body(...), tenant: str = DEFAULT_TENANT):
    emp, datos = _extract_solicitud(body)
    return core_crear_instancia(tenant, emp, datos)

@app.post("/api/instancias/{iid}/avanzar")
def avanzar(iid: str, body: AccionInstancia, tenant: str = DEFAULT_TENANT):
    return core_avanzar(tenant, iid, body.actor_id, body.accion, body.comentario or "")

@app.get("/api/empleados")
def get_empleados():
    try:
        with neo4j().session() as s:
            res = s.run("""
                MATCH (e:Empleado)
                OPTIONAL MATCH (e)-[:TIENE_ROL]->(r:Rol)
                RETURN e.empleado_id AS id, e.nombre AS nombre,
                       e.departamento AS dep, e.saldo_dias AS saldo, r.nombre AS rol
                ORDER BY e.nombre
            """)
            return [dict(r) for r in res]
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/api/grafo")
def get_grafo():
    try:
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
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/api/redis")
def get_redis_state():
    try:
        r = rdb()
        inst_keys  = sorted(r.keys("instancia:*"))
        saldo_keys = sorted(r.keys("empleado:*"))
        result = {}
        for k in inst_keys + saldo_keys:
            t = r.type(k)
            result[k] = r.hgetall(k) if t == "hash" else {"valor": r.get(k), "tipo": t}
        return result
    except Exception as e:
        raise HTTPException(500, str(e))
