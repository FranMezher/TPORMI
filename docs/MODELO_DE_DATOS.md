# Modelo de Datos — FlowOps

Modelo físico por motor, con claves, particionamiento e índices. Consolida el diseño de las **Actividades 5 (MongoDB), 6 (Cassandra), 7 (Neo4j) y 8 (Redis)**. La marca **[Prototipo]** indica qué implementa el código que corre.

---

## 1. MongoDB — modelo documental (Actividad 5)

### Colecciones del diseño

| Colección | Representa | Estructura | Versionado |
|-----------|-----------|-----------|:---:|
| `tenants` | Empresa cliente y config visual | Estructurada | — |
| `process_definitions` | Definición del flujo por versión | Semi-estructurada | ✅ |
| `process_instances` | Estado de cada ejecución | Semi-estructurada (`data` dinámico) | referencia versión |
| `tasks` | Tareas humanas pendientes/completadas | Estructurada/semi | — |
| `forms` | Formularios reutilizables | Semi-estructurada | — |
| `notification_templates` | Plantillas de notificación | Semi-estructurada | — |

**Embedding vs Referencing (Act 5-C):** se **embeben** los datos que forman parte del flujo (nodos, edges, campos del formulario, roles como string); se **referencian** los datos con ciclo de vida propio o compartidos (usuarios, integraciones, plantillas, reglas).

**Versionado (Act 5-D):** estrategia elegida = **un documento por versión**. Clave única `(tenant_id, process_id, version)`. Estados: `draft → published → archived`; solo una versión `published` por proceso y tenant. La instancia guarda `process_version`.

### Ejemplo — process_definition

```json
{
  "tenant_id": "tenant_grupo7",
  "process_id": "solicitud_vacaciones",
  "version": 2,
  "status": "published",
  "name": "Solicitud de Vacaciones",
  "nodes": [
    { "id": "start", "type": "start" },
    { "id": "formulario_solicitud", "type": "form", "fields": ["fecha_inicio","fecha_fin","dias_solicitados"] },
    { "id": "validacion_dias", "type": "decision", "condition": "dias_solicitados <= saldo_disponible" },
    { "id": "pendiente_aprobacion", "type": "task", "assigned_role": "aprobador" },
    { "id": "notif_aprobacion", "type": "notification", "destinatarios": ["solicitante","rrhh"] },
    { "id": "notif_rechazo", "type": "notification", "destinatarios": ["solicitante"] },
    { "id": "end", "type": "end" }
  ],
  "edges": [ { "from": "start", "to": "formulario_solicitud" }, ... ],
  "roles": ["solicitante","aprobador","rrhh"]
}
```

### Índices conceptuales (Act 5-F)

```js
db.process_definitions.createIndex({ tenant_id:1, process_id:1, status:1, version:-1 })
db.process_definitions.createIndex({ tenant_id:1, process_id:1, version:1 }, { unique:true })
db.process_instances.createIndex({ tenant_id:1, instance_id:1 }, { unique:true })
db.process_instances.createIndex({ tenant_id:1, status:1, updated_at:-1 })
db.tasks.createIndex({ tenant_id:1, assigned_role:1, status:1, created_at:1 })
```

> **[Prototipo]** Implementa `procesos` (≡ process_definitions), `instancias` (≡ process_instances) y `tareas` (≡ tasks), todas con `tenant_id`. Nombres de nodos del prototipo: `formulario`, `validacion_saldo`, `aprobacion_gerencia` (mismo concepto que `formulario_solicitud / validacion_dias / pendiente_aprobacion`). Las colecciones `forms`, `tenants` y `notification_templates` quedan como diseño.

---

## 2. Cassandra — event log columnar (Actividad 6)

Diseño orientado a consultas: **3 tablas**. Proyección: ~180 M eventos/mes.

### Tabla 1 — events_by_instance (reconstrucción de estado / timeline)

```sql
CREATE TABLE flowops.events_by_instance (
  tenant_id text, instance_id text, event_time timestamp, event_id timeuuid,
  process_id text, node_id text, event_type text, actor text, payload text,
  PRIMARY KEY ((tenant_id, instance_id), event_time, event_id)
) WITH CLUSTERING ORDER BY (event_time ASC, event_id ASC)
  AND default_time_to_live = 15552000; -- 180 días
```

### Tabla 2 — events_by_tenant_date (reportes y errores por período)

```sql
PRIMARY KEY ((tenant_id, date_bucket), event_time, instance_id, event_id)
-- date_bucket = 'YYYY-MM-DD'; clustering event_time DESC
```

### Tabla 3 — events_by_actor (auditoría por usuario)

```sql
PRIMARY KEY ((tenant_id, actor, date_bucket), event_time, event_id)
```

- **Particiones / hotspots (Act 6-D):** `date_bucket` acota el tamaño de partición en las tablas de reporting; si un tenant supera ~100 K eventos/día, subdividir a `YYYY-MM-DD-HH`.
- **Consistencia (Act 6-E):** escritura `ONE` (prioriza disponibilidad, append-only); lecturas críticas y reconstrucción de estado `QUORUM`.

> **[Prototipo]** Implementa una tabla equivalente a *events_by_instance*: `eventos_instancia (tenant_id, instance_id, timestamp, event_id, nodo, actor_id, accion, detalle)` con PK `((tenant_id, instance_id), timestamp, event_id)`. Las tablas por fecha y por actor quedan como diseño.

---

## 3. Neo4j — grafo organizacional y de flujo (Actividad 7)

### Nodos (8 tipos)

`:Tenant`, `:Process`, `:Step`, `:Role`, `:Regla`, `:Integración`, `:Usuario`, `:Instancia` — cada uno con sus propiedades (ver Act 7-B).

### Relaciones (11 tipos)

`[:BELONGS_TO]` (Process→Tenant), `[:HAS_STEP]` (Process→Step, con `position`), `[:NEXT]` (Step→Step, transiciones), `[:ASSIGNED_TO]` (Step→Role), `[:EVALUATES]` (Step→Regla), `[:INVOKES]` (Step→Integración), `[:HAS_ROLE]` (Usuario→Role), `[:STARTED_BY] / [:APPROVED_BY] / [:REJECTED_BY]` (Instancia→Usuario), `[:NOTIFIED]` (Usuario→Instancia).

**Constraints (Act 7):**
```cypher
CREATE CONSTRAINT FOR (e:Empleado)  REQUIRE e.empleado_id IS UNIQUE;
CREATE CONSTRAINT FOR (s:Solicitud) REQUIRE s.instance_id IS UNIQUE;
CREATE INDEX FOR (s:Solicitud) ON (s.estado);
```

**Consultas que justifican el grafo (Act 7-E/F):** caminos posibles `start→end` (`[:NEXT*1..10]`), pasos huérfanos (`NOT EXISTS { (:Step{start})-[:NEXT*0..]->(s) }`), convergencias del flujo. Imposibles de resolver eficientemente con SQL/JSON.

> **[Prototipo]** Implementa `Empleado` (≡ Usuario), `Rol`, `Solicitud` (≡ Instancia), `NodoProceso` (≡ Step) y las relaciones `TIENE_ROL`, `REPORTA_A`, `SIGUIENTE` (≡ NEXT), `SOLICITA` (≡ STARTED_BY), `APRUEBA/RECHAZA`, `NOTIFICADO`. Nodos `Tenant/Process/Regla/Integración` quedan como diseño.

---

## 4. Redis — caché, estado y patrones operativos (Actividad 8)

### Convención de claves

`{entidad}:{tenant_id}[:{id}]:{tipo}` — separador `:`, `tenant_id` siempre presente.

### Estructuras por caso (Act 8-C)

| Caso | Estructura | Clave | TTL |
|------|-----------|-------|-----|
| Estado de instancia | **Hash** | `instance:{tenant}:{id}:state` | 24 h |
| Sesión de usuario | **Hash** | `session:{session_id}` | 8 h |
| Tareas pendientes por rol | **Sorted Set** | `tasks:{tenant}:{role}:pending` | — |
| Cola de notificaciones | **List** | `queue:{tenant}:notifications` | sin TTL |
| Rate limit | **String** (`INCR`) | `rate_limit:{tenant}:{yyyyMMddTHHmm}` | 60 s |
| Contador diario | **String** (`INCR`) | `metrics:{tenant}:{yyyyMMdd}:{metrica}` | 30 d |
| Caché de definición | **String/Hash** | `cache:process:{tenant}:{process_id}` | 15 min |

- **Riesgos (Act 8-G):** pérdida en memoria → persistencia **AOF** `everysec`; caché desactualizada → **invalidación manual + TTL** como fallback; memoria → política **allkeys-lru**.

> **[Prototipo]** Implementa el **estado de instancia** como Hash (`instancia:{id}` con `estado, nodo_actual, updated_at`, TTL 24 h) y el **saldo de días** (`empleado:{id}:saldo_dias`). Sesiones, colas, rate-limit, ranking y contadores quedan como diseño.

---

## 5. Justificación de claves (resumen)

| Clave | Dónde | Por qué |
|-------|-------|---------|
| `tenant_id` | Todas | Aislamiento multi-tenant; partition key en Cassandra |
| `process_id` + `version` | MongoDB procesos | Versionado de definiciones (Act 5-D) |
| `instance_id` | Todos los motores | Identidad de la ejecución; correlaciona los 5 motores |
| `event_time` / `event_id` | Cassandra | Orden cronológico + unicidad ante duplicados |
| `task_id` | MongoDB tareas | Identidad de la tarea humana; idempotencia |
| `(tenant, actor, date_bucket)` | Cassandra events_by_actor | Auditoría por usuario sin hotspot |
