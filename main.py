"""
FlowOps API — TPO Ingeniería de Datos II
FastAPI backend conectado a MongoDB (x2), Redis, Cassandra y Neo4j.

Flujo del proceso (load_all.sh):
  start → formulario → validacion_saldo
      saldo_ok       → aprobacion_gerencia → notif_aprobacion → end
      saldo_insuf.   →                       notif_rechazo    → end

Contenedores Docker (load_all.sh):
  flowops-procesos   → MongoDB    → localhost:27017
  flowops-instancias → MongoDB    → localhost:27018
  flowops-cache      → Redis      → localhost:6379
  flowops-auditoria  → Cassandra  → localhost:9042   keyspace: flowops
  flowops-grafo      → Neo4j      → bolt://localhost:7687
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
import json, os, uuid as _uuid

# ─── App ─────────────────────────────────────────────────────
app = FastAPI(title="FlowOps API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

# ─── Config ──────────────────────────────────────────────────
MONGO_PROC_URL = os.getenv("MONGO_PROC_URL",
    "mongodb://admin:flowops123@localhost:27017/?authSource=admin")
MONGO_INST_URL = os.getenv("MONGO_INST_URL",
    "mongodb://admin:flowops123@localhost:27018/?authSource=admin")
REDIS_HOST     = os.getenv("REDIS_HOST",     "localhost")
REDIS_PORT     = int(os.getenv("REDIS_PORT", "6379"))
CASS_HOST      = os.getenv("CASSANDRA_HOST", "localhost")
NEO4J_URI      = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASS     = os.getenv("NEO4J_PASS",     "flowops123")

# Tenant por defecto (igual que en load_all.sh → "empresa_01")
TENANT_ID = "empresa_01"

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
    """Formato de clave Redis: instancia:{id}  (igual que en load_all.sh)"""
    return f"instancia:{iid}"

# ─── Lógica de flujo ─────────────────────────────────────────
def sig_nodo(nodo: str, accion: str) -> tuple:
    """
    Retorna (nodo_siguiente, nuevo_estado).
    Flujo: aprobacion_gerencia → notif_aprobacion | notif_rechazo → end
    El avanzar manual solo ocurre en aprobacion_gerencia.
    """
    if nodo == "aprobacion_gerencia":
        if accion == "approved":
            return ("notif_aprobacion", "aprobada")
        return ("notif_rechazo", "rechazada")
    # notif_* → end
    if nodo in ("notif_aprobacion", "notif_rechazo"):
        return ("end", "finalizada")
    return ("end", "finalizada")

# ─── Cassandra helpers ────────────────────────────────────────
CQL_INS = (
    "INSERT INTO flowops.eventos_instancia "
    "(tenant_id, instance_id, timestamp, event_id, nodo, actor_id, accion, detalle) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
)

def cass_event(iid, ts, nodo, actor, accion, detalle=None):
    cass().execute(CQL_INS, [
        TENANT_ID, iid, ts, _uuid.uuid4(), nodo,
        actor, accion, detalle
    ])

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

# ═══════════════════════════════════════════════════════════════
# STARTUP — seed MongoDB instancias con los datos del load_all.sh
# ═══════════════════════════════════════════════════════════════
@app.on_event("startup")
def seed_mongo_instancias():
    """Inserta las 3 instancias de ejemplo si la colección está vacía."""
    try:
        col = mongo_inst()["flowops_instancias"]["instancias"]
        if col.count_documents({}) == 0:
            col.insert_many([
                {
                    "instance_id": "inst_vac_2026_001",
                    "proceso_id":  "proc_vacaciones_v1",
                    "solicitante_id": "emp_001",
                    "estado": "aprobada",
                    "nodo_actual": "end",
                    "datos": {
                        "fecha_inicio":     "2026-07-01",
                        "fecha_fin":        "2026-07-18",
                        "dias_solicitados": 15,
                        "motivo":           "Vacaciones anuales"
                    },
                    "created_at": datetime(2026, 6, 10, 9, 0),
                    "updated_at": datetime(2026, 6, 10, 11, 1)
                },
                {
                    "instance_id": "inst_vac_2026_002",
                    "proceso_id":  "proc_vacaciones_v1",
                    "solicitante_id": "emp_004",
                    "estado": "rechazada",
                    "nodo_actual": "end",
                    "datos": {
                        "fecha_inicio":     "2026-07-15",
                        "fecha_fin":        "2026-07-29",
                        "dias_solicitados": 12,
                        "motivo":           "Vacaciones"
                    },
                    "created_at": datetime(2026, 6, 11, 10, 0),
                    "updated_at": datetime(2026, 6, 11, 10, 3)
                },
                {
                    "instance_id": "inst_vac_2026_003",
                    "proceso_id":  "proc_vacaciones_v1",
                    "solicitante_id": "emp_005",
                    "estado": "pendiente",
                    "nodo_actual": "aprobacion_gerencia",
                    "datos": {
                        "fecha_inicio":     "2026-08-01",
                        "fecha_fin":        "2026-08-07",
                        "dias_solicitados": 5,
                        "motivo":           "Vacaciones de invierno"
                    },
                    "created_at": datetime(2026, 6, 12, 8, 0),
                    "updated_at": datetime(2026, 6, 12, 8, 3)
                }
            ])
    except Exception:
        pass  # Si no conecta al inicio, no hay problema

# ═══════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════

# ── Sirve el frontend ────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def frontend():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    with open(path, encoding="utf-8") as f:
        return f.read()

# ── Health check — todas las bases ──────────────────────────
@app.get("/api/status")
def api_status():
    out = {}

    try:
        mongo_proc().admin.command("ping")
        n = mongo_proc()["flowops_procesos"]["procesos"].count_documents({})
        out["mongodb_procesos"] = {"ok": True, "docs": n, "label": "MongoDB Procesos"}
    except Exception as e:
        out["mongodb_procesos"] = {"ok": False, "error": str(e), "label": "MongoDB Procesos"}

    try:
        n = mongo_inst()["flowops_instancias"]["instancias"].count_documents({})
        out["mongodb_instancias"] = {"ok": True, "docs": n, "label": "MongoDB Instancias"}
    except Exception as e:
        out["mongodb_instancias"] = {"ok": False, "error": str(e), "label": "MongoDB Instancias"}

    try:
        rdb().ping()
        out["redis"] = {"ok": True, "keys": rdb().dbsize(), "label": "Redis Caché"}
    except Exception as e:
        out["redis"] = {"ok": False, "error": str(e), "label": "Redis Caché"}

    try:
        n = cass().execute(
            "SELECT COUNT(*) FROM flowops.eventos_instancia"
        ).one()[0]
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

# ── Proceso — MongoDB ────────────────────────────────────────
@app.get("/api/proceso")
def get_proceso():
    try:
        doc = mongo_proc()["flowops_procesos"]["procesos"].find_one({}, {"_id": 0})
        return clean(doc) or {}
    except Exception as e:
        raise HTTPException(500, str(e))

# ── Instancias — MongoDB + Redis ────────────────────────────
@app.get("/api/instancias")
def get_instancias():
    try:
        docs = [clean(d) for d in
                mongo_inst()["flowops_instancias"]["instancias"].find({}, {"_id": 0})]
        for d in docs:
            try:
                st = rdb().hgetall(redis_key(d["instance_id"]))
                d["redis_estado"]  = st.get("estado",      "")
                d["redis_nodo"]    = st.get("nodo_actual",  "")
                d["redis_updated"] = st.get("updated_at",   "")
            except:
                pass
        orden = {"pendiente": 0, "pendiente_gerencia": 1, "aprobada": 2, "rechazada": 3}
        docs.sort(key=lambda x: orden.get(x.get("redis_estado") or x.get("estado", ""), 9))
        return docs
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/api/instancias/{iid}")
def get_instancia(iid: str):
    try:
        doc = mongo_inst()["flowops_instancias"]["instancias"].find_one(
            {"instance_id": iid}, {"_id": 0})
        if not doc:
            raise HTTPException(404, "Instancia no encontrada")
        doc = clean(doc)
        try:
            doc["redis"] = rdb().hgetall(redis_key(iid))
        except:
            pass
        return doc
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

# ── Eventos — Cassandra ──────────────────────────────────────
@app.get("/api/instancias/{iid}/eventos")
def get_eventos(iid: str):
    try:
        # La PK requiere (tenant_id, instance_id) para evitar ALLOW FILTERING
        rows = cass().execute(
            "SELECT instance_id, timestamp, nodo, actor_id, accion, detalle "
            "FROM flowops.eventos_instancia "
            "WHERE tenant_id=%s AND instance_id=%s",
            [TENANT_ID, iid]
        )
        return [{
            "instance_id": r.instance_id,
            "timestamp":   r.timestamp.isoformat() if r.timestamp else None,
            "nodo":        r.nodo,
            "actor_id":    r.actor_id,
            "accion":      r.accion,
            "detalle":     r.detalle
        } for r in rows]
    except Exception as e:
        raise HTTPException(500, str(e))

# ── Crear instancia — escribe en los 4 motores ───────────────
@app.post("/api/instancias", status_code=201)
def crear_instancia(body: NuevaSolicitud):
    now   = datetime.utcnow()
    iid   = "inst_vac_" + now.strftime("%Y%m%d_%H%M%S")
    warns = []

    # 1. MongoDB ─────────────────────────────────────────────
    try:
        mongo_inst()["flowops_instancias"]["instancias"].insert_one({
            "instance_id":    iid,
            "proceso_id":     "proc_vacaciones_v1",
            "solicitante_id": body.empleado_id,
            "estado":         "pendiente",
            "nodo_actual":    "aprobacion_gerencia",  # tras validacion_saldo automática
            "datos": {
                "fecha_inicio":     body.fecha_inicio,
                "fecha_fin":        body.fecha_fin,
                "dias_solicitados": body.dias_solicitados,
                "motivo":           body.motivo
            },
            "created_at": now, "updated_at": now
        })
    except Exception as e:
        raise HTTPException(500, f"MongoDB: {e}")

    # 2. Redis ────────────────────────────────────────────────
    try:
        rdb().hset(redis_key(iid), mapping={
            "estado":      "pendiente",
            "nodo_actual": "aprobacion_gerencia",
            "updated_at":  now.isoformat()
        })
        rdb().expire(redis_key(iid), 86400)
    except Exception as e:
        warns.append(f"Redis: {e}")

    # 3. Cassandra ────────────────────────────────────────────
    try:
        cass_event(iid, now,                        "start",               None,             "inicio_proceso",     None)
        cass_event(iid, now + timedelta(seconds=1), "formulario",          body.empleado_id, "formulario_enviado",
                   json.dumps({"fecha_inicio": body.fecha_inicio, "fecha_fin": body.fecha_fin,
                                "dias_solicitados": body.dias_solicitados, "motivo": body.motivo}))
        cass_event(iid, now + timedelta(seconds=2), "validacion_saldo",    "sistema",        "saldo_suficiente",
                   json.dumps({"dias_solicitados": body.dias_solicitados}))
        cass_event(iid, now + timedelta(seconds=3), "aprobacion_gerencia", "sistema",        "tarea_asignada",
                   json.dumps({"asignado_a_rol": "gerencia"}))
    except Exception as e:
        warns.append(f"Cassandra: {e}")

    # 4. Neo4j ────────────────────────────────────────────────
    try:
        with neo4j().session() as sess:
            sess.run("""
                MERGE (s:Solicitud {instance_id: $iid})
                SET s.estado           = 'pendiente',
                    s.dias_solicitados = $dias,
                    s.fecha_inicio     = $fi,
                    s.fecha_fin        = $ff,
                    s.motivo           = $motivo,
                    s.created_at       = $ts
                WITH s
                MATCH (e:Empleado {empleado_id: $eid})
                MERGE (e)-[:SOLICITA {timestamp: $ts}]->(s)
            """, iid=iid, dias=body.dias_solicitados,
                fi=body.fecha_inicio, ff=body.fecha_fin,
                motivo=body.motivo, ts=now.isoformat(), eid=body.empleado_id)
    except Exception as e:
        warns.append(f"Neo4j: {e}")

    return {"ok": True, "instance_id": iid, "warnings": warns}

# ── Avanzar instancia — actualiza los 4 motores ──────────────
@app.post("/api/instancias/{iid}/avanzar")
def avanzar(iid: str, body: AccionInstancia):
    try:
        doc = mongo_inst()["flowops_instancias"]["instancias"].find_one({"instance_id": iid})
        if not doc:
            raise HTTPException(404, "Instancia no encontrada")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

    nodo_actual = doc.get("nodo_actual", "aprobacion_gerencia")
    nodo_sig, nuevo_estado = sig_nodo(nodo_actual, body.accion)
    now   = datetime.utcnow()
    warns = []

    # 1. MongoDB
    try:
        mongo_inst()["flowops_instancias"]["instancias"].update_one(
            {"instance_id": iid},
            {"$set": {"estado": nuevo_estado, "nodo_actual": nodo_sig, "updated_at": now}})
    except Exception as e:
        raise HTTPException(500, f"MongoDB: {e}")

    # 2. Redis
    try:
        rdb().hset(redis_key(iid), mapping={
            "estado":      nuevo_estado,
            "nodo_actual": nodo_sig,
            "updated_at":  now.isoformat()
        })
    except Exception as e:
        warns.append(f"Redis: {e}")

    # 3. Cassandra
    try:
        cass_event(iid, now, nodo_actual, body.actor_id, body.accion, body.comentario or "")
        if nodo_sig in ("notif_aprobacion", "notif_rechazo"):
            dest = [doc.get("solicitante_id", "")]
            if nodo_sig == "notif_aprobacion":
                dest.append("emp_002")  # RRHH también recibe aprobación (load_all.sh)
            cass_event(iid, now + timedelta(seconds=1), nodo_sig, "sistema",
                       "notificacion_enviada",
                       json.dumps({"destinatarios": dest}))
    except Exception as e:
        warns.append(f"Cassandra: {e}")

    # 4. Neo4j
    try:
        rel = "APRUEBA" if body.accion == "approved" else "RECHAZA"
        with neo4j().session() as sess:
            sess.run(
                f"MATCH (s:Solicitud {{instance_id:$iid}}),(e:Empleado {{empleado_id:$eid}}) "
                f"MERGE (e)-[:{rel} {{timestamp:$ts,comentario:$c}}]->(s) "
                f"SET s.estado=$est",
                iid=iid, eid=body.actor_id,
                ts=now.isoformat(), c=body.comentario or "", est=nuevo_estado)
    except Exception as e:
        warns.append(f"Neo4j: {e}")

    return {"ok": True, "nodo_anterior": nodo_actual,
            "nodo_actual": nodo_sig, "estado": nuevo_estado, "warnings": warns}

# ── Empleados — Neo4j ────────────────────────────────────────
@app.get("/api/empleados")
def get_empleados():
    try:
        with neo4j().session() as s:
            res = s.run("""
                MATCH (e:Empleado)
                OPTIONAL MATCH (e)-[:TIENE_ROL]->(r:Rol)
                RETURN e.empleado_id  AS id,
                       e.nombre       AS nombre,
                       e.departamento AS dep,
                       e.saldo_dias   AS saldo,
                       r.nombre       AS rol
                ORDER BY e.nombre
            """)
            return [dict(r) for r in res]
    except Exception as e:
        raise HTTPException(500, str(e))

# ── Grafo de solicitudes — Neo4j ─────────────────────────────
@app.get("/api/grafo")
def get_grafo():
    try:
        with neo4j().session() as s:
            res = s.run("""
                MATCH (e:Empleado)-[r]->(sol:Solicitud)
                RETURN e.nombre             AS empleado,
                       e.departamento       AS depto,
                       type(r)              AS relacion,
                       sol.instance_id      AS instancia,
                       sol.estado           AS estado,
                       sol.dias_solicitados  AS dias,
                       sol.fecha_inicio     AS fecha_inicio
                ORDER BY sol.instance_id, type(r)
            """)
            return [dict(r) for r in res]
    except Exception as e:
        raise HTTPException(500, str(e))

# ── Redis — estado de todas las instancias ───────────────────
@app.get("/api/redis")
def get_redis_state():
    try:
        r = rdb()
        # Claves instancia:{id} (sin `:estado`, igual que load_all.sh)
        # También incluimos empleado:*:saldo_dias
        inst_keys = sorted(r.keys("instancia:*"))
        saldo_keys = sorted(r.keys("empleado:*"))
        result = {}
        for k in inst_keys + saldo_keys:
            t = r.type(k)
            if t == "hash":
                result[k] = r.hgetall(k)
            else:
                result[k] = {"valor": r.get(k), "tipo": t}
        return result
    except Exception as e:
        raise HTTPException(500, str(e))
