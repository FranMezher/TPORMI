"""
load_all.py — equivalente Python de load_all.sh
Ejecutar desde PowerShell: python load_all.py
"""

import subprocess
import sys
import time

# Modo limpio: carga solo la estructura mínima (definición de proceso, empleados,
# roles, saldos) SIN instancias/eventos/solicitudes demo. Útil para correr todo
# el proceso desde cero en la demo.  Uso:  python load_all.py --limpio
MINIMAL = "--limpio" in sys.argv or "--minimal" in sys.argv

# ── Colores en consola ────────────────────────────────────────
def ok(msg):    print(f"  \033[92m✔ {msg}\033[0m")
def info(msg):  print(f"  \033[93m→ {msg}\033[0m")
def err(msg):   print(f"  \033[91m✘ {msg}\033[0m"); sys.exit(1)

def run(cmd, input_text=None, check=True):
    """Ejecuta un comando docker. input_text se pasa como stdin."""
    result = subprocess.run(
        cmd, input=input_text, capture_output=True, text=True
    )
    if check and result.returncode != 0:
        print(f"  STDOUT: {result.stdout[-500:] if result.stdout else ''}")
        print(f"  STDERR: {result.stderr[-500:] if result.stderr else ''}")
        raise RuntimeError(f"Comando falló: {' '.join(cmd)}")
    return result

def wait_for(name, test_cmd, retries=30, delay=3):
    info(f"Esperando {name}...")
    for _ in range(retries):
        r = subprocess.run(test_cmd, capture_output=True, text=True)
        if r.returncode == 0:
            ok(f"{name} listo")
            return
        time.sleep(delay)
    err(f"{name} no respondió a tiempo")

# ═══════════════════════════════════════════════════════════════
print()
print("=" * 60)
print("  FlowOps — Carga inicial de datos" + ("  [MODO LIMPIO]" if MINIMAL else ""))
print("=" * 60)
if MINIMAL:
    print("  Solo estructura: definición + empleados + saldos (sin instancias demo)")

# ── 1. Esperar containers ─────────────────────────────────────
print("\n[ 1/4 ] Esperando containers...")

wait_for("Neo4j", [
    "docker", "exec", "flowops-grafo",
    "cypher-shell", "-u", "neo4j", "-p", "flowops123", "RETURN 1"
])

wait_for("MongoDB procesos", [
    "docker", "exec", "flowops-instancias",
    "mongosh", "-u", "admin", "-p", "flowops123",
    "--authenticationDatabase", "admin",
    "--quiet", "--eval", 'db.runCommand({ping:1}).ok'
])

wait_for("Cassandra", [
    "docker", "exec", "flowops-auditoria",
    "cqlsh", "--execute", "SELECT release_version FROM system.local"
], delay=4)

wait_for("Redis", [
    "docker", "exec", "flowops-cache",
    "redis-cli", "-a", "flowops123", "ping"
])

# ── 2. Neo4j ──────────────────────────────────────────────────
print("\n[ 2/4 ] Neo4j — flujo BPM, empleados y solicitudes...")

CYPHER = """
CREATE CONSTRAINT empleado_id_unique  IF NOT EXISTS FOR (e:Empleado)    REQUIRE e.empleado_id  IS UNIQUE;
CREATE CONSTRAINT solicitud_id_unique IF NOT EXISTS FOR (s:Solicitud)   REQUIRE s.instance_id  IS UNIQUE;
CREATE CONSTRAINT nodo_id_unique      IF NOT EXISTS FOR (n:NodoProceso) REQUIRE n.node_id      IS UNIQUE;
CREATE CONSTRAINT rol_nombre_unique   IF NOT EXISTS FOR (r:Rol)         REQUIRE r.nombre       IS UNIQUE;
CREATE INDEX empleado_nombre  IF NOT EXISTS FOR (e:Empleado)  ON (e.nombre);
CREATE INDEX solicitud_estado IF NOT EXISTS FOR (s:Solicitud) ON (s.estado);
MATCH (n) DETACH DELETE n;
MERGE (:Rol {nombre: 'empleado'});
MERGE (:Rol {nombre: 'rrhh'});
MERGE (:Rol {nombre: 'gerencia'});
MERGE (e1:Empleado {empleado_id: 'emp_001'}) SET e1.nombre = 'Juan Pérez',     e1.departamento = 'Tecnología',       e1.saldo_dias = 15;
MERGE (e2:Empleado {empleado_id: 'emp_002'}) SET e2.nombre = 'María González', e2.departamento = 'Recursos Humanos', e2.saldo_dias = 20;
MERGE (e3:Empleado {empleado_id: 'emp_003'}) SET e3.nombre = 'Carlos López',   e3.departamento = 'Dirección',        e3.saldo_dias = 25;
MERGE (e4:Empleado {empleado_id: 'emp_004'}) SET e4.nombre = 'Ana Martínez',   e4.departamento = 'Tecnología',       e4.saldo_dias = 10;
MERGE (e5:Empleado {empleado_id: 'emp_005'}) SET e5.nombre = 'Luis Rodríguez', e5.departamento = 'Marketing',        e5.saldo_dias = 18;
MATCH (e:Empleado {empleado_id: 'emp_001'}), (r:Rol {nombre: 'empleado'})  MERGE (e)-[:TIENE_ROL]->(r);
MATCH (e:Empleado {empleado_id: 'emp_002'}), (r:Rol {nombre: 'rrhh'})      MERGE (e)-[:TIENE_ROL]->(r);
MATCH (e:Empleado {empleado_id: 'emp_003'}), (r:Rol {nombre: 'gerencia'})  MERGE (e)-[:TIENE_ROL]->(r);
MATCH (e:Empleado {empleado_id: 'emp_004'}), (r:Rol {nombre: 'empleado'})  MERGE (e)-[:TIENE_ROL]->(r);
MATCH (e:Empleado {empleado_id: 'emp_005'}), (r:Rol {nombre: 'empleado'})  MERGE (e)-[:TIENE_ROL]->(r);
MATCH (e1:Empleado {empleado_id: 'emp_001'}), (e3:Empleado {empleado_id: 'emp_003'}) MERGE (e1)-[:REPORTA_A]->(e3);
MATCH (e4:Empleado {empleado_id: 'emp_004'}), (e3:Empleado {empleado_id: 'emp_003'}) MERGE (e4)-[:REPORTA_A]->(e3);
MATCH (e5:Empleado {empleado_id: 'emp_005'}), (e3:Empleado {empleado_id: 'emp_003'}) MERGE (e5)-[:REPORTA_A]->(e3);
MATCH (e2:Empleado {empleado_id: 'emp_002'}), (e3:Empleado {empleado_id: 'emp_003'}) MERGE (e2)-[:REPORTA_A]->(e3);
MERGE (:NodoProceso {node_id: 'start',               tipo: 'start',        nombre: 'Inicio'});
MERGE (:NodoProceso {node_id: 'formulario',          tipo: 'form',         nombre: 'Formulario de Solicitud'});
MERGE (:NodoProceso {node_id: 'validacion_saldo',    tipo: 'decision',     nombre: 'Validar Saldo de Días'});
MERGE (:NodoProceso {node_id: 'aprobacion_gerencia', tipo: 'task',         nombre: 'Aprobación Gerencia'});
MERGE (:NodoProceso {node_id: 'notif_aprobacion',    tipo: 'notification', nombre: 'Notificación Aprobación'});
MERGE (:NodoProceso {node_id: 'notif_rechazo',       tipo: 'notification', nombre: 'Notificación Rechazo'});
MERGE (:NodoProceso {node_id: 'end',                 tipo: 'end',          nombre: 'Fin'});
MATCH (a:NodoProceso {node_id: 'start'}),               (b:NodoProceso {node_id: 'formulario'})          MERGE (a)-[:SIGUIENTE {condicion: 'always'}]->(b);
MATCH (a:NodoProceso {node_id: 'formulario'}),           (b:NodoProceso {node_id: 'validacion_saldo'})    MERGE (a)-[:SIGUIENTE {condicion: 'always'}]->(b);
MATCH (a:NodoProceso {node_id: 'validacion_saldo'}),     (b:NodoProceso {node_id: 'aprobacion_gerencia'}) MERGE (a)-[:SIGUIENTE {condicion: 'saldo_suficiente'}]->(b);
MATCH (a:NodoProceso {node_id: 'validacion_saldo'}),     (b:NodoProceso {node_id: 'notif_rechazo'})       MERGE (a)-[:SIGUIENTE {condicion: 'saldo_insuficiente'}]->(b);
MATCH (a:NodoProceso {node_id: 'aprobacion_gerencia'}),  (b:NodoProceso {node_id: 'notif_aprobacion'})    MERGE (a)-[:SIGUIENTE {condicion: 'aprobado'}]->(b);
MATCH (a:NodoProceso {node_id: 'aprobacion_gerencia'}),  (b:NodoProceso {node_id: 'notif_rechazo'})       MERGE (a)-[:SIGUIENTE {condicion: 'rechazado'}]->(b);
MATCH (a:NodoProceso {node_id: 'notif_aprobacion'}),     (b:NodoProceso {node_id: 'end'})                 MERGE (a)-[:SIGUIENTE {condicion: 'always'}]->(b);
MATCH (a:NodoProceso {node_id: 'notif_rechazo'}),        (b:NodoProceso {node_id: 'end'})                 MERGE (a)-[:SIGUIENTE {condicion: 'always'}]->(b);
MATCH (st:Step {tenant_id:'empresa_01', proceso_id:'proc_vacaciones_v1'}) DETACH DELETE st;
MERGE (s_start:Step {tenant_id:'empresa_01', proceso_id:'proc_vacaciones_v1', node_id:'start'})               SET s_start.tipo='start',        s_start.nombre='Inicio';
MERGE (s_form:Step {tenant_id:'empresa_01', proceso_id:'proc_vacaciones_v1', node_id:'formulario'})          SET s_form.tipo='form',          s_form.nombre='Formulario';
MERGE (s_val:Step {tenant_id:'empresa_01', proceso_id:'proc_vacaciones_v1', node_id:'validacion_saldo'})     SET s_val.tipo='decision',       s_val.nombre='Validar Saldo';
MERGE (s_apr:Step {tenant_id:'empresa_01', proceso_id:'proc_vacaciones_v1', node_id:'aprobacion_gerencia'})  SET s_apr.tipo='task',           s_apr.nombre='Aprobacion Gerencia';
MERGE (s_na:Step {tenant_id:'empresa_01', proceso_id:'proc_vacaciones_v1', node_id:'notif_aprobacion'})      SET s_na.tipo='notification',    s_na.nombre='Notificacion Aprobacion';
MERGE (s_nr:Step {tenant_id:'empresa_01', proceso_id:'proc_vacaciones_v1', node_id:'notif_rechazo'})         SET s_nr.tipo='notification',    s_nr.nombre='Notificacion Rechazo';
MERGE (s_end:Step {tenant_id:'empresa_01', proceso_id:'proc_vacaciones_v1', node_id:'end'})                  SET s_end.tipo='end',            s_end.nombre='Fin';
MATCH (a:Step {proceso_id:'proc_vacaciones_v1', node_id:'start'}),               (b:Step {proceso_id:'proc_vacaciones_v1', node_id:'formulario'})          MERGE (a)-[:NEXT {condicion:'always'}]->(b);
MATCH (a:Step {proceso_id:'proc_vacaciones_v1', node_id:'formulario'}),          (b:Step {proceso_id:'proc_vacaciones_v1', node_id:'validacion_saldo'})    MERGE (a)-[:NEXT {condicion:'always'}]->(b);
MATCH (a:Step {proceso_id:'proc_vacaciones_v1', node_id:'validacion_saldo'}),    (b:Step {proceso_id:'proc_vacaciones_v1', node_id:'aprobacion_gerencia'}) MERGE (a)-[:NEXT {condicion:'saldo_suficiente'}]->(b);
MATCH (a:Step {proceso_id:'proc_vacaciones_v1', node_id:'validacion_saldo'}),    (b:Step {proceso_id:'proc_vacaciones_v1', node_id:'notif_rechazo'})       MERGE (a)-[:NEXT {condicion:'saldo_insuficiente'}]->(b);
MATCH (a:Step {proceso_id:'proc_vacaciones_v1', node_id:'aprobacion_gerencia'}), (b:Step {proceso_id:'proc_vacaciones_v1', node_id:'notif_aprobacion'})    MERGE (a)-[:NEXT {condicion:'aprobado'}]->(b);
MATCH (a:Step {proceso_id:'proc_vacaciones_v1', node_id:'aprobacion_gerencia'}), (b:Step {proceso_id:'proc_vacaciones_v1', node_id:'notif_rechazo'})       MERGE (a)-[:NEXT {condicion:'rechazado'}]->(b);
MATCH (a:Step {proceso_id:'proc_vacaciones_v1', node_id:'notif_aprobacion'}),    (b:Step {proceso_id:'proc_vacaciones_v1', node_id:'end'})                 MERGE (a)-[:NEXT {condicion:'always'}]->(b);
MATCH (a:Step {proceso_id:'proc_vacaciones_v1', node_id:'notif_rechazo'}),       (b:Step {proceso_id:'proc_vacaciones_v1', node_id:'end'})                 MERGE (a)-[:NEXT {condicion:'always'}]->(b);
"""

# Solicitudes demo (instancias ya iniciadas/finalizadas). Se omiten con --limpio.
CYPHER_DEMO = """
MERGE (s1:Solicitud {instance_id: 'inst_vac_2026_001'}) SET s1.estado = 'aprobada',  s1.dias_solicitados = 15, s1.fecha_inicio = '2026-07-01', s1.fecha_fin = '2026-07-18', s1.created_at = '2026-06-10T09:00:00Z';
MERGE (s2:Solicitud {instance_id: 'inst_vac_2026_002'}) SET s2.estado = 'rechazada', s2.dias_solicitados = 12, s2.fecha_inicio = '2026-07-15', s2.fecha_fin = '2026-07-29', s2.created_at = '2026-06-11T10:00:00Z';
MERGE (s3:Solicitud {instance_id: 'inst_vac_2026_003'}) SET s3.estado = 'pendiente', s3.dias_solicitados = 5,  s3.fecha_inicio = '2026-08-01', s3.fecha_fin = '2026-08-07',  s3.created_at = '2026-06-12T08:00:00Z';
MATCH (e:Empleado {empleado_id: 'emp_001'}), (s:Solicitud {instance_id: 'inst_vac_2026_001'}) MERGE (e)-[:SOLICITA  {timestamp: '2026-06-10T09:00:00Z'}]->(s);
MATCH (e:Empleado {empleado_id: 'emp_003'}), (s:Solicitud {instance_id: 'inst_vac_2026_001'}) MERGE (e)-[:APRUEBA   {timestamp: '2026-06-10T11:00:00Z', comentario: 'Aprobado'}]->(s);
MATCH (e:Empleado {empleado_id: 'emp_001'}), (s:Solicitud {instance_id: 'inst_vac_2026_001'}) MERGE (e)-[:NOTIFICADO {timestamp: '2026-06-10T11:01:00Z', tipo: 'aprobacion'}]->(s);
MATCH (e:Empleado {empleado_id: 'emp_002'}), (s:Solicitud {instance_id: 'inst_vac_2026_001'}) MERGE (e)-[:NOTIFICADO {timestamp: '2026-06-10T11:01:00Z', tipo: 'aprobacion'}]->(s);
MATCH (e:Empleado {empleado_id: 'emp_004'}), (s:Solicitud {instance_id: 'inst_vac_2026_002'}) MERGE (e)-[:SOLICITA   {timestamp: '2026-06-11T10:00:00Z'}]->(s);
MATCH (e:Empleado {empleado_id: 'emp_004'}), (s:Solicitud {instance_id: 'inst_vac_2026_002'}) MERGE (e)-[:NOTIFICADO {timestamp: '2026-06-11T10:02:00Z', tipo: 'rechazo', motivo: 'saldo_insuficiente'}]->(s);
MATCH (e:Empleado {empleado_id: 'emp_005'}), (s:Solicitud {instance_id: 'inst_vac_2026_003'}) MERGE (e)-[:SOLICITA   {timestamp: '2026-06-12T08:00:00Z'}]->(s);
"""

run(
    ["docker", "exec", "-i", "flowops-grafo",
     "cypher-shell", "-u", "neo4j", "-p", "flowops123"],
    input_text=CYPHER if MINIMAL else CYPHER + CYPHER_DEMO
)
ok("Neo4j cargado" + (" (mínimo)" if MINIMAL else ""))

# ── 3. MongoDB ────────────────────────────────────────────────
print("\n[ 3/4 ] MongoDB — definición del proceso...")

MONGO_JS = """
db = db.getSiblingDB('flowops_procesos');
db.procesos.drop();
db.procesos.insertOne({
  tenant_id:   "empresa_01",
  proceso_id:  "proc_vacaciones_v1",
  nombre:      "Solicitud de Vacaciones",
  version:     1,
  activo:      true,
  created_at:  new Date("2026-01-01T00:00:00Z"),
  descripcion: "Proceso de solicitud y aprobación de vacaciones para empleados.",
  validaciones: { regla_saldo: "dias_solicitados <= empleado.saldo_dias" },
  nodos: [
    { node_id: "start",               tipo: "start",        nombre: "Inicio" },
    { node_id: "formulario",          tipo: "form",         nombre: "Formulario de Solicitud",
      campos: [
        { name: "empleado_id",      label: "Empleado ID",      type: "text",     required: true },
        { name: "fecha_inicio",     label: "Fecha inicio",     type: "date",     required: true },
        { name: "fecha_fin",        label: "Fecha fin",        type: "date",     required: true },
        { name: "dias_solicitados", label: "Días solicitados (hábiles)", type: "calculated", required: true },
        { name: "motivo",           label: "Motivo",           type: "textarea", required: false }
      ],
      campos_calculados: ["dias_solicitados"], rol_ejecutor: "empleado" },
    { node_id: "validacion_saldo",    tipo: "decision",     nombre: "Validar Saldo de Días",
      automatico: true, condicion: "dias_solicitados <= empleado.saldo_dias" },
    { node_id: "aprobacion_gerencia", tipo: "task",         nombre: "Aprobación Gerencia",
      rol_ejecutor: "gerencia", acciones: ["aprobar","rechazar"], sla_horas: 48 },
    { node_id: "notif_aprobacion",    tipo: "notification", nombre: "Notificación Aprobación",
      destinatarios: ["empleado","rrhh"] },
    { node_id: "notif_rechazo",       tipo: "notification", nombre: "Notificación Rechazo",
      destinatarios: ["empleado"] },
    { node_id: "end",                 tipo: "end",          nombre: "Fin" }
  ],
  transiciones: [
    { desde: "start",               hasta: "formulario",          condicion: "always" },
    { desde: "formulario",          hasta: "validacion_saldo",    condicion: "always" },
    { desde: "validacion_saldo",    hasta: "aprobacion_gerencia", condicion: "saldo_suficiente" },
    { desde: "validacion_saldo",    hasta: "notif_rechazo",       condicion: "saldo_insuficiente" },
    { desde: "aprobacion_gerencia", hasta: "notif_aprobacion",    condicion: "aprobado" },
    { desde: "aprobacion_gerencia", hasta: "notif_rechazo",       condicion: "rechazado" },
    { desde: "notif_aprobacion",    hasta: "end",                 condicion: "always" },
    { desde: "notif_rechazo",       hasta: "end",                 condicion: "always" }
  ]
});

// Limpieza de instancias y tareas previas (las "cosas raras" acumuladas).
// El arranque de la API resiembra 3 instancias demo, salvo FLOWOPS_SEED_DEMO=0.
db = db.getSiblingDB('flowops_instancias');
db.instancias.drop();
db.tareas.drop();
"""

run(
    ["docker", "exec", "-i", "flowops-instancias",
     "mongosh", "-u", "admin", "-p", "flowops123",
     "--authenticationDatabase", "admin", "--quiet"],
    input_text=MONGO_JS
)
ok("MongoDB cargado")

# ── 4. Cassandra ──────────────────────────────────────────────
print("\n[ 4/4 ] Cassandra — event log de auditoría...")

CQL = """
CREATE KEYSPACE IF NOT EXISTS flowops
  WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};
USE flowops;
DROP TABLE IF EXISTS eventos_instancia;
CREATE TABLE eventos_instancia (
  tenant_id   TEXT,
  instance_id TEXT,
  timestamp   TIMESTAMP,
  event_id    UUID,
  nodo        TEXT,
  actor_id    TEXT,
  accion      TEXT,
  detalle     TEXT,
  PRIMARY KEY ((tenant_id, instance_id), timestamp, event_id)
) WITH CLUSTERING ORDER BY (timestamp ASC, event_id ASC);

DROP TABLE IF EXISTS eventos_por_fecha;
CREATE TABLE eventos_por_fecha (
  tenant_id   TEXT,
  fecha       DATE,
  timestamp   TIMESTAMP,
  event_id    UUID,
  instance_id TEXT,
  nodo        TEXT,
  actor_id    TEXT,
  accion      TEXT,
  detalle     TEXT,
  PRIMARY KEY ((tenant_id, fecha), timestamp, event_id)
) WITH CLUSTERING ORDER BY (timestamp DESC, event_id ASC);
"""

# Eventos demo de auditoría. Se omiten con --limpio (la tabla queda vacía).
CQL_DEMO = """
USE flowops;
INSERT INTO eventos_instancia (tenant_id,instance_id,timestamp,event_id,nodo,actor_id,accion,detalle) VALUES ('empresa_01','inst_vac_2026_001','2026-06-10 09:00:00+0000',uuid(),'start',null,'inicio_proceso',null);
INSERT INTO eventos_instancia (tenant_id,instance_id,timestamp,event_id,nodo,actor_id,accion,detalle) VALUES ('empresa_01','inst_vac_2026_001','2026-06-10 09:01:00+0000',uuid(),'formulario','emp_001','formulario_enviado','{"fecha_inicio":"2026-07-01","fecha_fin":"2026-07-18","dias_solicitados":15}');
INSERT INTO eventos_instancia (tenant_id,instance_id,timestamp,event_id,nodo,actor_id,accion,detalle) VALUES ('empresa_01','inst_vac_2026_001','2026-06-10 09:02:00+0000',uuid(),'validacion_saldo','sistema','saldo_suficiente','{"saldo_disponible":15,"dias_solicitados":15}');
INSERT INTO eventos_instancia (tenant_id,instance_id,timestamp,event_id,nodo,actor_id,accion,detalle) VALUES ('empresa_01','inst_vac_2026_001','2026-06-10 11:00:00+0000',uuid(),'aprobacion_gerencia','emp_003','aprobado','{"comentario":"Aprobado"}');
INSERT INTO eventos_instancia (tenant_id,instance_id,timestamp,event_id,nodo,actor_id,accion,detalle) VALUES ('empresa_01','inst_vac_2026_001','2026-06-10 11:01:00+0000',uuid(),'notif_aprobacion','sistema','notificacion_enviada','{"destinatarios":["emp_001","emp_002"]}');
INSERT INTO eventos_instancia (tenant_id,instance_id,timestamp,event_id,nodo,actor_id,accion,detalle) VALUES ('empresa_01','inst_vac_2026_001','2026-06-10 11:01:30+0000',uuid(),'end',null,'proceso_finalizado',null);

INSERT INTO eventos_instancia (tenant_id,instance_id,timestamp,event_id,nodo,actor_id,accion,detalle) VALUES ('empresa_01','inst_vac_2026_002','2026-06-11 10:00:00+0000',uuid(),'start',null,'inicio_proceso',null);
INSERT INTO eventos_instancia (tenant_id,instance_id,timestamp,event_id,nodo,actor_id,accion,detalle) VALUES ('empresa_01','inst_vac_2026_002','2026-06-11 10:01:00+0000',uuid(),'formulario','emp_004','formulario_enviado','{"fecha_inicio":"2026-07-15","fecha_fin":"2026-07-29","dias_solicitados":12}');
INSERT INTO eventos_instancia (tenant_id,instance_id,timestamp,event_id,nodo,actor_id,accion,detalle) VALUES ('empresa_01','inst_vac_2026_002','2026-06-11 10:02:00+0000',uuid(),'validacion_saldo','sistema','saldo_insuficiente','{"saldo_disponible":10,"dias_solicitados":12}');
INSERT INTO eventos_instancia (tenant_id,instance_id,timestamp,event_id,nodo,actor_id,accion,detalle) VALUES ('empresa_01','inst_vac_2026_002','2026-06-11 10:02:30+0000',uuid(),'notif_rechazo','sistema','notificacion_enviada','{"destinatarios":["emp_004"],"motivo":"saldo_insuficiente"}');
INSERT INTO eventos_instancia (tenant_id,instance_id,timestamp,event_id,nodo,actor_id,accion,detalle) VALUES ('empresa_01','inst_vac_2026_002','2026-06-11 10:03:00+0000',uuid(),'end',null,'proceso_finalizado',null);

INSERT INTO eventos_instancia (tenant_id,instance_id,timestamp,event_id,nodo,actor_id,accion,detalle) VALUES ('empresa_01','inst_vac_2026_003','2026-06-12 08:00:00+0000',uuid(),'start',null,'inicio_proceso',null);
INSERT INTO eventos_instancia (tenant_id,instance_id,timestamp,event_id,nodo,actor_id,accion,detalle) VALUES ('empresa_01','inst_vac_2026_003','2026-06-12 08:01:00+0000',uuid(),'formulario','emp_005','formulario_enviado','{"fecha_inicio":"2026-08-01","fecha_fin":"2026-08-07","dias_solicitados":5}');
INSERT INTO eventos_instancia (tenant_id,instance_id,timestamp,event_id,nodo,actor_id,accion,detalle) VALUES ('empresa_01','inst_vac_2026_003','2026-06-12 08:02:00+0000',uuid(),'validacion_saldo','sistema','saldo_suficiente','{"saldo_disponible":18,"dias_solicitados":5}');
INSERT INTO eventos_instancia (tenant_id,instance_id,timestamp,event_id,nodo,actor_id,accion,detalle) VALUES ('empresa_01','inst_vac_2026_003','2026-06-12 08:03:00+0000',uuid(),'aprobacion_gerencia','sistema','tarea_asignada','{"asignado_a_rol":"gerencia"}');
"""

run(
    ["docker", "exec", "-i", "flowops-auditoria", "cqlsh"],
    input_text=CQL if MINIMAL else CQL + CQL_DEMO
)
ok("Cassandra cargada" + (" (mínimo)" if MINIMAL else ""))

# ── Redis ─────────────────────────────────────────────────────
print("\n[ + ] Redis — estado actual y saldos...")

redis_commands = [["FLUSHALL"]]
if not MINIMAL:
    # Estado cacheado de las instancias demo (en --limpio no se cargan).
    # EXPIRE 86400 (24 h): el estado en Redis es CACHÉ con TTL; Mongo es la verdad.
    redis_commands += [
        ["HSET", "instancia:inst_vac_2026_001", "estado", "aprobada",  "nodo_actual", "end",                  "updated_at", "2026-06-10T11:01:30Z"],
        ["EXPIRE", "instancia:inst_vac_2026_001", "86400"],
        ["HSET", "instancia:inst_vac_2026_002", "estado", "rechazada", "nodo_actual", "end",                  "updated_at", "2026-06-11T10:03:00Z", "motivo_rechazo", "saldo_insuficiente"],
        ["EXPIRE", "instancia:inst_vac_2026_002", "86400"],
        ["HSET", "instancia:inst_vac_2026_003", "estado", "pendiente", "nodo_actual", "aprobacion_gerencia",  "updated_at", "2026-06-12T08:03:00Z"],
        ["EXPIRE", "instancia:inst_vac_2026_003", "86400"],
    ]
redis_commands += [
    # En --limpio emp_001 arranca con saldo completo (15) para poder solicitar desde cero
    ["SET",  "empleado:emp_001:saldo_dias", "15" if MINIMAL else "0"],
    ["SET",  "empleado:emp_002:saldo_dias", "20"],
    ["SET",  "empleado:emp_003:saldo_dias", "25"],
    ["SET",  "empleado:emp_004:saldo_dias", "10"],
    ["SET",  "empleado:emp_005:saldo_dias", "18"],
]

for cmd in redis_commands:
    run(["docker", "exec", "flowops-cache", "redis-cli", "-a", "flowops123"] + cmd)

ok("Redis cargado")

# ── Resumen ───────────────────────────────────────────────────
print()
print("=" * 60)
print("  Verificación final")
print("=" * 60)

try:
    neo_n = run(["docker", "exec", "flowops-grafo", "cypher-shell", "-u", "neo4j", "-p", "flowops123", "--format", "plain", "MATCH (n) RETURN count(n)"], check=False).stdout.strip().split("\n")[-1]
    neo_r = run(["docker", "exec", "flowops-grafo", "cypher-shell", "-u", "neo4j", "-p", "flowops123", "--format", "plain", "MATCH ()-[r]->() RETURN count(r)"], check=False).stdout.strip().split("\n")[-1]
    print(f"  Neo4j     → {neo_n} nodos  |  {neo_r} relaciones")
except: print("  Neo4j     → (no se pudo verificar)")

try:
    mp = run(["docker", "exec", "flowops-instancias", "mongosh", "-u", "admin", "-p", "flowops123", "--authenticationDatabase", "admin", "--quiet", "--eval", "db.getSiblingDB('flowops_procesos').procesos.countDocuments()"], check=False).stdout.strip().split("\n")[-1]
    print(f"  MongoDB   → {mp} proceso(s) definido(s)")
except: print("  MongoDB   → (no se pudo verificar)")

try:
    ce = run(["docker", "exec", "flowops-auditoria", "cqlsh", "--execute", "SELECT COUNT(*) FROM flowops.eventos_instancia"], check=False).stdout
    import re; m = re.search(r'\d+', ce); print(f"  Cassandra → {m.group()} evento(s) de auditoría")
except: print("  Cassandra → (no se pudo verificar)")

try:
    rk = run(["docker", "exec", "flowops-cache", "redis-cli", "-a", "flowops123", "DBSIZE"], check=False).stdout.strip()
    print(f"  Redis     → {rk} clave(s) activas")
except: print("  Redis     → (no se pudo verificar)")

print()
print("\033[92m  Todo cargado correctamente.\033[0m")
if MINIMAL:
    print()
    print("  Para que la API NO resiembre instancias demo, levantala así:")
    print("\033[93m    $env:FLOWOPS_SEED_DEMO=0; python -m uvicorn main:app --port 8000 --reload\033[0m")
print("=" * 60)
print()
