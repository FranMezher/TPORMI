"""
Capa de configuración.

Centraliza los parámetros de conexión a cada producto (leídos de variables de
entorno, con valores por defecto para desarrollo) y las constantes del dominio.
Ninguna otra capa hardcodea hosts/puertos: todas leen de acá.
"""
import os

# ─── Conexiones a los motores ────────────────────────────────
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

# Nombres de bases lógicas de MongoDB
DB_PROCESOS    = "flowops_procesos"
DB_INSTANCIAS  = "flowops_instancias"
# Keyspace de Cassandra
CASS_KEYSPACE  = "flowops"

# ─── Dominio ─────────────────────────────────────────────────
# Tenant por defecto (igual que en load_all → "empresa_01")
DEFAULT_TENANT = "empresa_01"
TENANT_ID      = DEFAULT_TENANT  # compat

# Si FLOWOPS_SEED_DEMO="0" el arranque NO siembra las 3 instancias demo:
# deja la base limpia para correr todo el proceso desde cero (demo en vivo).
SEED_DEMO_INSTANCES = os.getenv("FLOWOPS_SEED_DEMO", "1") != "0"

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
