#!/bin/bash
# ============================================================
# FlowOps - Solicitud de Vacaciones
# load_all.sh — Carga completa de todas las bases de datos
# ============================================================

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}  ✔ $1${NC}"; }
info() { echo -e "${YELLOW}  → $1${NC}"; }
err()  { echo -e "${RED}  ✘ $1${NC}"; exit 1; }

echo ""
echo "============================================================"
echo "  FlowOps — Carga inicial de datos"
echo "============================================================"

# ── 1. Esperar containers ─────────────────────────────────────
echo ""
echo "[ 1/4 ] Esperando containers..."

info "Neo4j..."
until docker exec flowops-grafo cypher-shell -u neo4j -p flowops123 "RETURN 1" &>/dev/null; do sleep 2; done
ok "Neo4j listo"

info "MongoDB procesos..."
until docker exec flowops-procesos mongosh -u admin -p flowops123 \
  --authenticationDatabase admin --quiet \
  --eval "db.runCommand({ping:1})" 2>/dev/null | grep -q "ok"; do sleep 2; done
ok "MongoDB listo"

info "Cassandra..."
until docker exec flowops-auditoria cqlsh \
  --execute "SELECT release_version FROM system.local" &>/dev/null; do sleep 3; done
ok "Cassandra lista"

info "Redis..."
until docker exec flowops-cache redis-cli -a flowops123 ping 2>/dev/null | grep -q "PONG"; do sleep 2; done
ok "Redis listo"

# ── 2. Neo4j ──────────────────────────────────────────────────
echo ""
echo "[ 2/4 ] Neo4j — flujo BPM, empleados y solicitudes..."

docker exec -i flowops-grafo cypher-shell -u neo4j -p flowops123 <<'CYPHER'

// --- Constraints e índices ---
CREATE CONSTRAINT empleado_id_unique  IF NOT EXISTS FOR (e:Empleado)    REQUIRE e.empleado_id  IS UNIQUE;
CREATE CONSTRAINT solicitud_id_unique IF NOT EXISTS FOR (s:Solicitud)   REQUIRE s.instance_id  IS UNIQUE;
CREATE CONSTRAINT nodo_id_unique      IF NOT EXISTS FOR (n:NodoProceso) REQUIRE n.node_id      IS UNIQUE;
CREATE CONSTRAINT rol_nombre_unique   IF NOT EXISTS FOR (r:Rol)         REQUIRE r.nombre       IS UNIQUE;
CREATE INDEX empleado_nombre  IF NOT EXISTS FOR (e:Empleado)  ON (e.nombre);
CREATE INDEX solicitud_estado IF NOT EXISTS FOR (s:Solicitud) ON (s.estado);

// --- Limpiar datos previos ---
MATCH (n) DETACH DELETE n;

// --- Roles ---
MERGE (:Rol {nombre: 'empleado'});
MERGE (:Rol {nombre: 'rrhh'});
MERGE (:Rol {nombre: 'gerencia'});

// --- Empleados ---
// saldo_dias: contador propio de cada empleado, de 0 a infinito
MERGE (e1:Empleado {empleado_id: 'emp_001'}) SET e1.nombre = 'Juan Pérez',     e1.departamento = 'Tecnología',       e1.saldo_dias = 15;
MERGE (e2:Empleado {empleado_id: 'emp_002'}) SET e2.nombre = 'María González', e2.departamento = 'Recursos Humanos', e2.saldo_dias = 20;
MERGE (e3:Empleado {empleado_id: 'emp_003'}) SET e3.nombre = 'Carlos López',   e3.departamento = 'Dirección',        e3.saldo_dias = 25;
MERGE (e4:Empleado {empleado_id: 'emp_004'}) SET e4.nombre = 'Ana Martínez',   e4.departamento = 'Tecnología',       e4.saldo_dias = 10;
MERGE (e5:Empleado {empleado_id: 'emp_005'}) SET e5.nombre = 'Luis Rodríguez', e5.departamento = 'Marketing',        e5.saldo_dias = 18;

// --- Roles de empleados ---
MATCH (e:Empleado {empleado_id: 'emp_001'}), (r:Rol {nombre: 'empleado'})  MERGE (e)-[:TIENE_ROL]->(r);
MATCH (e:Empleado {empleado_id: 'emp_002'}), (r:Rol {nombre: 'rrhh'})      MERGE (e)-[:TIENE_ROL]->(r);
MATCH (e:Empleado {empleado_id: 'emp_003'}), (r:Rol {nombre: 'gerencia'})  MERGE (e)-[:TIENE_ROL]->(r);
MATCH (e:Empleado {empleado_id: 'emp_004'}), (r:Rol {nombre: 'empleado'})  MERGE (e)-[:TIENE_ROL]->(r);
MATCH (e:Empleado {empleado_id: 'emp_005'}), (r:Rol {nombre: 'empleado'})  MERGE (e)-[:TIENE_ROL]->(r);

// --- Jerarquía organizacional ---
MATCH (e1:Empleado {empleado_id: 'emp_001'}), (e3:Empleado {empleado_id: 'emp_003'}) MERGE (e1)-[:REPORTA_A]->(e3);
MATCH (e4:Empleado {empleado_id: 'emp_004'}), (e3:Empleado {empleado_id: 'emp_003'}) MERGE (e4)-[:REPORTA_A]->(e3);
MATCH (e5:Empleado {empleado_id: 'emp_005'}), (e3:Empleado {empleado_id: 'emp_003'}) MERGE (e5)-[:REPORTA_A]->(e3);
MATCH (e2:Empleado {empleado_id: 'emp_002'}), (e3:Empleado {empleado_id: 'emp_003'}) MERGE (e2)-[:REPORTA_A]->(e3);

// --- Nodos del proceso BPM ---
// Flujo:
// START
// → FORMULARIO (empleado ingresa fechas)
// → VALIDACION_SALDO (sistema: dias_solicitados <= empleado.saldo_dias)
//     → saldo_insuficiente → NOTIF_RECHAZO (solo empleado) → END
//     → saldo_suficiente   → APROBACION_GERENCIA (gerente decide)
//         → rechazado → NOTIF_RECHAZO (solo empleado) → END
//         → aprobado  → NOTIF_APROBACION (empleado + RRHH) → END

MERGE (:NodoProceso {node_id: 'start',               tipo: 'start',        nombre: 'Inicio'});
MERGE (:NodoProceso {node_id: 'formulario',          tipo: 'form',         nombre: 'Formulario de Solicitud'});
MERGE (:NodoProceso {node_id: 'validacion_saldo',    tipo: 'decision',     nombre: 'Validar Saldo de Días',
                     descripcion: 'El sistema verifica que dias_solicitados <= empleado.saldo_dias'});
MERGE (:NodoProceso {node_id: 'aprobacion_gerencia', tipo: 'task',         nombre: 'Aprobación Gerencia',
                     rol_ejecutor: 'gerencia', sla_horas: 48});
MERGE (:NodoProceso {node_id: 'notif_aprobacion',    tipo: 'notification', nombre: 'Notificación Aprobación',
                     destinatarios: ['empleado', 'rrhh']});
MERGE (:NodoProceso {node_id: 'notif_rechazo',       tipo: 'notification', nombre: 'Notificación Rechazo',
                     destinatarios: ['empleado']});
MERGE (:NodoProceso {node_id: 'end',                 tipo: 'end',          nombre: 'Fin'});

// --- Transiciones ---
MATCH (a:NodoProceso {node_id: 'start'}),               (b:NodoProceso {node_id: 'formulario'})          MERGE (a)-[:SIGUIENTE {condicion: 'always'}]->(b);
MATCH (a:NodoProceso {node_id: 'formulario'}),           (b:NodoProceso {node_id: 'validacion_saldo'})    MERGE (a)-[:SIGUIENTE {condicion: 'always'}]->(b);
MATCH (a:NodoProceso {node_id: 'validacion_saldo'}),     (b:NodoProceso {node_id: 'aprobacion_gerencia'}) MERGE (a)-[:SIGUIENTE {condicion: 'saldo_suficiente'}]->(b);
MATCH (a:NodoProceso {node_id: 'validacion_saldo'}),     (b:NodoProceso {node_id: 'notif_rechazo'})       MERGE (a)-[:SIGUIENTE {condicion: 'saldo_insuficiente'}]->(b);
MATCH (a:NodoProceso {node_id: 'aprobacion_gerencia'}),  (b:NodoProceso {node_id: 'notif_aprobacion'})    MERGE (a)-[:SIGUIENTE {condicion: 'aprobado'}]->(b);
MATCH (a:NodoProceso {node_id: 'aprobacion_gerencia'}),  (b:NodoProceso {node_id: 'notif_rechazo'})       MERGE (a)-[:SIGUIENTE {condicion: 'rechazado'}]->(b);
MATCH (a:NodoProceso {node_id: 'notif_aprobacion'}),     (b:NodoProceso {node_id: 'end'})                 MERGE (a)-[:SIGUIENTE {condicion: 'always'}]->(b);
MATCH (a:NodoProceso {node_id: 'notif_rechazo'}),        (b:NodoProceso {node_id: 'end'})                 MERGE (a)-[:SIGUIENTE {condicion: 'always'}]->(b);

// --- Solicitudes ---
// inst_001: 15 días solicitados, saldo 15 → saldo ok → gerencia aprueba
MERGE (s1:Solicitud {instance_id: 'inst_vac_2026_001'})
  SET s1.estado = 'aprobada', s1.dias_solicitados = 15,
      s1.fecha_inicio = '2026-07-01', s1.fecha_fin = '2026-07-18',
      s1.created_at = '2026-06-10T09:00:00Z';

// inst_002: 12 días solicitados, saldo 10 → saldo insuficiente → rechazo automático
MERGE (s2:Solicitud {instance_id: 'inst_vac_2026_002'})
  SET s2.estado = 'rechazada', s2.dias_solicitados = 12,
      s2.fecha_inicio = '2026-07-15', s2.fecha_fin = '2026-07-29',
      s2.created_at = '2026-06-11T10:00:00Z';

// inst_003: 5 días solicitados, saldo 18 → saldo ok → pendiente en gerencia
MERGE (s3:Solicitud {instance_id: 'inst_vac_2026_003'})
  SET s3.estado = 'pendiente', s3.dias_solicitados = 5,
      s3.fecha_inicio = '2026-08-01', s3.fecha_fin = '2026-08-07',
      s3.created_at = '2026-06-12T08:00:00Z';

// --- Relaciones de solicitudes ---
// inst_001: Juan solicita, Carlos (gerencia) aprueba
MATCH (e:Empleado {empleado_id: 'emp_001'}), (s:Solicitud {instance_id: 'inst_vac_2026_001'}) MERGE (e)-[:SOLICITA {timestamp: '2026-06-10T09:00:00Z'}]->(s);
MATCH (e:Empleado {empleado_id: 'emp_003'}), (s:Solicitud {instance_id: 'inst_vac_2026_001'}) MERGE (e)-[:APRUEBA  {timestamp: '2026-06-10T11:00:00Z', comentario: 'Aprobado'}]->(s);
// Notificados: empleado + RRHH
MATCH (e:Empleado {empleado_id: 'emp_001'}), (s:Solicitud {instance_id: 'inst_vac_2026_001'}) MERGE (e)-[:NOTIFICADO {timestamp: '2026-06-10T11:01:00Z', tipo: 'aprobacion'}]->(s);
MATCH (e:Empleado {empleado_id: 'emp_002'}), (s:Solicitud {instance_id: 'inst_vac_2026_001'}) MERGE (e)-[:NOTIFICADO {timestamp: '2026-06-10T11:01:00Z', tipo: 'aprobacion'}]->(s);

// inst_002: Ana solicita, rechazo automático por saldo insuficiente
MATCH (e:Empleado {empleado_id: 'emp_004'}), (s:Solicitud {instance_id: 'inst_vac_2026_002'}) MERGE (e)-[:SOLICITA  {timestamp: '2026-06-11T10:00:00Z'}]->(s);
// Notificado: solo empleado
MATCH (e:Empleado {empleado_id: 'emp_004'}), (s:Solicitud {instance_id: 'inst_vac_2026_002'}) MERGE (e)-[:NOTIFICADO {timestamp: '2026-06-11T10:02:00Z', tipo: 'rechazo', motivo: 'saldo_insuficiente'}]->(s);

// inst_003: Luis solicita, pendiente en gerencia
MATCH (e:Empleado {empleado_id: 'emp_005'}), (s:Solicitud {instance_id: 'inst_vac_2026_003'}) MERGE (e)-[:SOLICITA {timestamp: '2026-06-12T08:00:00Z'}]->(s);
CYPHER

ok "Neo4j cargado"

# ── 3. MongoDB ────────────────────────────────────────────────
echo ""
echo "[ 3/4 ] MongoDB — definición del proceso..."

docker exec -i flowops-procesos mongosh \
  -u admin -p flowops123 \
  --authenticationDatabase admin --quiet <<'MONGO'
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
  validaciones: {
    regla_saldo: "dias_solicitados <= empleado.saldo_dias"
  },
  nodos: [
    { node_id: "start",
      tipo: "start", nombre: "Inicio" },
    { node_id: "formulario",
      tipo: "form", nombre: "Formulario de Solicitud",
      campos: ["fecha_inicio", "fecha_fin"],
      campos_calculados: ["dias_solicitados"],
      rol_ejecutor: "empleado" },
    { node_id: "validacion_saldo",
      tipo: "decision", nombre: "Validar Saldo de Días",
      descripcion: "El sistema verifica automaticamente que dias_solicitados <= empleado.saldo_dias",
      automatico: true,
      condicion: "dias_solicitados <= empleado.saldo_dias" },
    { node_id: "aprobacion_gerencia",
      tipo: "task", nombre: "Aprobación Gerencia",
      rol_ejecutor: "gerencia",
      acciones: ["aprobar", "rechazar"],
      sla_horas: 48 },
    { node_id: "notif_aprobacion",
      tipo: "notification", nombre: "Notificación Aprobación",
      destinatarios: ["empleado", "rrhh"],
      descripcion: "Se notifica al empleado solicitante y a RRHH" },
    { node_id: "notif_rechazo",
      tipo: "notification", nombre: "Notificación Rechazo",
      destinatarios: ["empleado"],
      descripcion: "Se notifica solo al empleado solicitante" },
    { node_id: "end",
      tipo: "end", nombre: "Fin" }
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
MONGO

ok "MongoDB cargado"

# ── 4. Cassandra ──────────────────────────────────────────────
echo ""
echo "[ 4/4 ] Cassandra — event log de auditoría..."

docker exec -i flowops-auditoria cqlsh <<'CQL'
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

-- inst_001: aprobada (15 días, saldo 15 → ok → gerencia aprueba → notifica empleado + RRHH)
INSERT INTO eventos_instancia (tenant_id, instance_id, timestamp, event_id, nodo, actor_id, accion, detalle)
VALUES ('empresa_01','inst_vac_2026_001','2026-06-10 09:00:00+0000',uuid(),'start',               null,      'inicio_proceso',     null);
INSERT INTO eventos_instancia (tenant_id, instance_id, timestamp, event_id, nodo, actor_id, accion, detalle)
VALUES ('empresa_01','inst_vac_2026_001','2026-06-10 09:01:00+0000',uuid(),'formulario',          'emp_001', 'formulario_enviado', '{"fecha_inicio":"2026-07-01","fecha_fin":"2026-07-18","dias_solicitados":15}');
INSERT INTO eventos_instancia (tenant_id, instance_id, timestamp, event_id, nodo, actor_id, accion, detalle)
VALUES ('empresa_01','inst_vac_2026_001','2026-06-10 09:02:00+0000',uuid(),'validacion_saldo',    'sistema', 'saldo_suficiente',   '{"saldo_disponible":15,"dias_solicitados":15}');
INSERT INTO eventos_instancia (tenant_id, instance_id, timestamp, event_id, nodo, actor_id, accion, detalle)
VALUES ('empresa_01','inst_vac_2026_001','2026-06-10 11:00:00+0000',uuid(),'aprobacion_gerencia', 'emp_003', 'aprobado',           '{"comentario":"Aprobado"}');
INSERT INTO eventos_instancia (tenant_id, instance_id, timestamp, event_id, nodo, actor_id, accion, detalle)
VALUES ('empresa_01','inst_vac_2026_001','2026-06-10 11:01:00+0000',uuid(),'notif_aprobacion',    'sistema', 'notificacion_enviada','{"destinatarios":["emp_001","emp_002"]}');
INSERT INTO eventos_instancia (tenant_id, instance_id, timestamp, event_id, nodo, actor_id, accion, detalle)
VALUES ('empresa_01','inst_vac_2026_001','2026-06-10 11:01:30+0000',uuid(),'end',                 null,      'proceso_finalizado', null);

-- inst_002: rechazada automáticamente (12 días solicitados, saldo 10 → insuficiente → notifica solo empleado)
INSERT INTO eventos_instancia (tenant_id, instance_id, timestamp, event_id, nodo, actor_id, accion, detalle)
VALUES ('empresa_01','inst_vac_2026_002','2026-06-11 10:00:00+0000',uuid(),'start',            null,      'inicio_proceso',     null);
INSERT INTO eventos_instancia (tenant_id, instance_id, timestamp, event_id, nodo, actor_id, accion, detalle)
VALUES ('empresa_01','inst_vac_2026_002','2026-06-11 10:01:00+0000',uuid(),'formulario',       'emp_004', 'formulario_enviado', '{"fecha_inicio":"2026-07-15","fecha_fin":"2026-07-29","dias_solicitados":12}');
INSERT INTO eventos_instancia (tenant_id, instance_id, timestamp, event_id, nodo, actor_id, accion, detalle)
VALUES ('empresa_01','inst_vac_2026_002','2026-06-11 10:02:00+0000',uuid(),'validacion_saldo', 'sistema', 'saldo_insuficiente',  '{"saldo_disponible":10,"dias_solicitados":12}');
INSERT INTO eventos_instancia (tenant_id, instance_id, timestamp, event_id, nodo, actor_id, accion, detalle)
VALUES ('empresa_01','inst_vac_2026_002','2026-06-11 10:02:30+0000',uuid(),'notif_rechazo',    'sistema', 'notificacion_enviada','{"destinatarios":["emp_004"],"motivo":"saldo_insuficiente"}');
INSERT INTO eventos_instancia (tenant_id, instance_id, timestamp, event_id, nodo, actor_id, accion, detalle)
VALUES ('empresa_01','inst_vac_2026_002','2026-06-11 10:03:00+0000',uuid(),'end',              null,      'proceso_finalizado', null);

-- inst_003: pendiente en gerencia (5 días, saldo 18 → ok → esperando gerencia)
INSERT INTO eventos_instancia (tenant_id, instance_id, timestamp, event_id, nodo, actor_id, accion, detalle)
VALUES ('empresa_01','inst_vac_2026_003','2026-06-12 08:00:00+0000',uuid(),'start',            null,      'inicio_proceso',     null);
INSERT INTO eventos_instancia (tenant_id, instance_id, timestamp, event_id, nodo, actor_id, accion, detalle)
VALUES ('empresa_01','inst_vac_2026_003','2026-06-12 08:01:00+0000',uuid(),'formulario',       'emp_005', 'formulario_enviado', '{"fecha_inicio":"2026-08-01","fecha_fin":"2026-08-07","dias_solicitados":5}');
INSERT INTO eventos_instancia (tenant_id, instance_id, timestamp, event_id, nodo, actor_id, accion, detalle)
VALUES ('empresa_01','inst_vac_2026_003','2026-06-12 08:02:00+0000',uuid(),'validacion_saldo', 'sistema', 'saldo_suficiente',   '{"saldo_disponible":18,"dias_solicitados":5}');
INSERT INTO eventos_instancia (tenant_id, instance_id, timestamp, event_id, nodo, actor_id, accion, detalle)
VALUES ('empresa_01','inst_vac_2026_003','2026-06-12 08:03:00+0000',uuid(),'aprobacion_gerencia','sistema','tarea_asignada',    '{"asignado_a_rol":"gerencia"}');
CQL

ok "Cassandra cargada"

# ── Redis ─────────────────────────────────────────────────────
echo ""
echo "[ + ] Redis — estado actual y saldos..."

docker exec flowops-cache redis-cli -a flowops123 FLUSHALL > /dev/null

# Estado actual de cada instancia
docker exec flowops-cache redis-cli -a flowops123 HSET instancia:inst_vac_2026_001 \
  estado aprobada nodo_actual end updated_at "2026-06-10T11:01:30Z" > /dev/null

docker exec flowops-cache redis-cli -a flowops123 HSET instancia:inst_vac_2026_002 \
  estado rechazada nodo_actual end updated_at "2026-06-11T10:03:00Z" \
  motivo_rechazo saldo_insuficiente > /dev/null

docker exec flowops-cache redis-cli -a flowops123 HSET instancia:inst_vac_2026_003 \
  estado pendiente nodo_actual aprobacion_gerencia updated_at "2026-06-12T08:03:00Z" > /dev/null

# Saldo de días por empleado
# emp_001: tenía 15, usó 15 → queda 0
docker exec flowops-cache redis-cli -a flowops123 SET empleado:emp_001:saldo_dias 0  > /dev/null
docker exec flowops-cache redis-cli -a flowops123 SET empleado:emp_002:saldo_dias 20 > /dev/null
docker exec flowops-cache redis-cli -a flowops123 SET empleado:emp_003:saldo_dias 25 > /dev/null
# emp_004: saldo no se descuenta porque fue rechazada automáticamente
docker exec flowops-cache redis-cli -a flowops123 SET empleado:emp_004:saldo_dias 10 > /dev/null
# emp_005: pendiente, saldo no descontado hasta aprobación
docker exec flowops-cache redis-cli -a flowops123 SET empleado:emp_005:saldo_dias 18 > /dev/null

ok "Redis cargado"

# ── Resumen ───────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  Verificación final"
echo "============================================================"

NEO_NODOS=$(docker exec flowops-grafo cypher-shell -u neo4j -p flowops123 --format plain "MATCH (n) RETURN count(n)" 2>/dev/null | tail -1)
NEO_RELS=$(docker exec flowops-grafo  cypher-shell -u neo4j -p flowops123 --format plain "MATCH ()-[r]->() RETURN count(r)" 2>/dev/null | tail -1)
MONGO_PROC=$(docker exec flowops-procesos mongosh -u admin -p flowops123 --authenticationDatabase admin --quiet --eval "db.getSiblingDB('flowops_procesos').procesos.countDocuments()" 2>/dev/null | tail -1)
CASS_EVENTS=$(docker exec flowops-auditoria cqlsh --execute "SELECT COUNT(*) FROM flowops.eventos_instancia" 2>/dev/null | grep -E '^\s+[0-9]' | tr -d ' ')
REDIS_KEYS=$(docker exec flowops-cache redis-cli -a flowops123 DBSIZE 2>/dev/null)

echo ""
echo "  Neo4j     → ${NEO_NODOS} nodos  |  ${NEO_RELS} relaciones"
echo "  MongoDB   → ${MONGO_PROC} proceso(s) definido(s)"
echo "  Cassandra → ${CASS_EVENTS} evento(s) de auditoría"
echo "  Redis     → ${REDIS_KEYS} clave(s) activas"
echo ""
echo -e "${GREEN}  Todo cargado correctamente.${NC}"
echo "============================================================"
echo ""