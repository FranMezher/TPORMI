"""
Capa de conexión.

Factories *lazy* a los cinco motores: la conexión se abre la primera vez que se
usa y se cachea (patrón singleton simple). Esto desacopla el acceso a datos del
arranque de la app: si un motor no está disponible al inicio, el resto funciona.

Expone también los accesos a colecciones de MongoDB y utilidades de
serialización compartidas por la capa de acceso a datos.
"""
from datetime import datetime
from . import config

# Cache de conexiones abiertas
_c = {}


def mongo_proc():
    if "mp" not in _c:
        import pymongo
        _c["mp"] = pymongo.MongoClient(config.MONGO_PROC_URL, serverSelectionTimeoutMS=3000)
    return _c["mp"]


def mongo_inst():
    if "mi" not in _c:
        import pymongo
        _c["mi"] = pymongo.MongoClient(config.MONGO_INST_URL, serverSelectionTimeoutMS=3000)
    return _c["mi"]


def rdb():
    if "r" not in _c:
        import redis
        _c["r"] = redis.Redis(host=config.REDIS_HOST, port=config.REDIS_PORT, decode_responses=True)
    return _c["r"]


def cass():
    if "c" not in _c:
        from cassandra.cluster import Cluster
        _c["c"] = Cluster([config.CASS_HOST]).connect(config.CASS_KEYSPACE)
    return _c["c"]


def neo4j():
    if "n" not in _c:
        from neo4j import GraphDatabase
        _c["n"] = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASS))
    return _c["n"]


# ─── Accesos a colecciones ───────────────────────────────────
def procesos_col():   return mongo_proc()[config.DB_PROCESOS]["procesos"]
def tenants_col():    return mongo_proc()[config.DB_PROCESOS]["tenants"]
def instancias_col(): return mongo_inst()[config.DB_INSTANCIAS]["instancias"]
def tareas_col():     return mongo_inst()[config.DB_INSTANCIAS]["tareas"]


# ─── Utilidades de serialización ─────────────────────────────
def clean(obj):
    """Serializa documentos MongoDB (elimina _id, convierte datetime)."""
    if obj is None:
        return None
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
