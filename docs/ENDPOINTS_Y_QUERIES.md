# Endpoints y queries por motor — FlowOps

Mapa de **cada endpoint** de la API y las **operaciones concretas** que ejecuta
contra cada base de datos. Útil para la defensa: muestra exactamente qué motor se
toca en cada acción.

## Convenciones

| Motor | Acceso | Colección / Keyspace |
|-------|--------|----------------------|
| 🍃 **MongoDB** | `pymongo` | `flowops_procesos.procesos`, `.tenants` · `flowops_instancias.instancias`, `.tareas` |
| ⚡ **Redis** | `redis-py` | claves `instancia:{id}` (hash), `empleado:{id}:saldo_dias` |
| 💎 **Cassandra** | `cassandra-driver` | `flowops.eventos_instancia` |
| 🕸️ **Neo4j** | `neo4j` (Bolt) | nodos `:Empleado :Solicitud :Rol :NodoProceso` |

> Capas: cada handler (`flowops/routers/*`) llama a la lógica (`services.py`) o
> directo al DAO (`repositories.py`). Las queries de abajo son las del DAO.

---

# 1. Rutas del spec (multi-tenant)

## `POST /api/{tenant_id}/processes`
Crea/actualiza una definición de proceso **y valida su topología en Neo4j**.
- 🍃 **MongoDB** — `procesos`:
  ```js
  db.procesos.updateOne(
    { tenant_id, proceso_id },
    { $set: <definición completa> },
    { upsert: true })
  ```
- 🕸️ **Neo4j** — refleja la topología como `(:Step)-[:NEXT]->(:Step)` y valida:
  ```cypher
  // sincroniza (reescribe la topología del proceso)
  MATCH (st:Step {tenant_id:$t, proceso_id:$p}) DETACH DELETE st;
  UNWIND $nodos AS n MERGE (st:Step {tenant_id:$t, proceso_id:$p, node_id:n.node_id}) SET st.tipo=n.tipo, st.nombre=n.nombre;
  UNWIND $trans AS tr MATCH (a:Step{...node_id:tr.desde}),(b:Step{...node_id:tr.hasta}) MERGE (a)-[:NEXT {condicion:tr.condicion}]->(b);
  // valida caminos (devuelve pasos sin salida a 'end')
  MATCH (st:Step {tenant_id:$t, proceso_id:$p}) WHERE st.tipo <> 'end'
    AND NOT EXISTS { MATCH (st)-[:NEXT*1..]->(e:Step {tenant_id:$t, proceso_id:$p}) WHERE e.tipo='end' }
  RETURN st.node_id;
  ```
  > La respuesta incluye `validacion: { ok, errores, sin_camino_a_fin, inalcanzables, loops }`.
  > Detalle en [VALIDACION_NEO4J.md](VALIDACION_NEO4J.md).

## `GET /api/{tenant_id}/processes`
Lista las definiciones del tenant.
- 🍃 **MongoDB** — `procesos`:
  ```js
  db.procesos.find({ tenant_id }, { _id: 0 })
  ```

## `GET /api/{tenant_id}/processes/{process_id}`
Devuelve una definición.
- 🍃 **MongoDB** — `procesos`:
  ```js
  db.procesos.findOne({ tenant_id, proceso_id }, { _id: 0 })
  ```

## `POST /api/{tenant_id}/processes/{process_id}/instances`
Inicia una instancia → **escritura distribuida en 4 motores** (`core_crear_instancia`).
- 🍃 **MongoDB** — `instancias`:
  ```js
  db.instancias.insertOne({
    tenant_id, instance_id, proceso_id, solicitante_id,
    estado: "pendiente", nodo_actual: "aprobacion_gerencia",
    datos: {...}, created_at, updated_at })
  ```
- 🍃 **MongoDB** — `tareas` (entidad Task, idempotente):
  ```js
  db.tareas.updateOne({ task_id },
    { $setOnInsert: { task_id, tenant_id, instance_id, node_id,
                      assigned_role: "gerencia", status: "pending", created_at } },
    { upsert: true })
  ```
- ⚡ **Redis** — caché de estado con TTL:
  ```
  HSET instancia:{id} estado "pendiente" nodo_actual "aprobacion_gerencia" updated_at <iso>
  EXPIRE instancia:{id} 86400
  ```
- 💎 **Cassandra** — 4 eventos de auditoría, **escritura dual** (mismo `event_id` en
  las dos tablas: una por instancia, otra por fecha):
  ```sql
  INSERT INTO flowops.eventos_instancia
    (tenant_id, instance_id, timestamp, event_id, nodo, actor_id, accion, detalle)
    VALUES (?, ?, ?, uuid(), ?, ?, ?, ?);
  INSERT INTO flowops.eventos_por_fecha
    (tenant_id, fecha, timestamp, event_id, instance_id, nodo, actor_id, accion, detalle)
    VALUES (?, ?, ?, <mismo event_id>, ?, ?, ?, ?, ?);
  -- nodos: start · formulario · validacion_saldo · aprobacion_gerencia
  ```
- 🕸️ **Neo4j** — crea la solicitud y la relación con el empleado:
  ```cypher
  MERGE (s:Solicitud {instance_id: $iid})
  SET s.estado='pendiente', s.dias_solicitados=$dias,
      s.fecha_inicio=$fi, s.fecha_fin=$ff, s.motivo=$motivo,
      s.created_at=$ts, s.tenant_id=$tenant
  WITH s
  MATCH (e:Empleado {empleado_id: $eid})
  MERGE (e)-[:SOLICITA {timestamp: $ts}]->(s)
  ```

## `GET /api/{tenant_id}/instances/{instance_id}`
Estado de una instancia (Mongo = verdad, Redis = caché).
- 🍃 **MongoDB** — `instancias`:
  ```js
  db.instancias.findOne({ tenant_id, instance_id }, { _id: 0 })
  ```
- ⚡ **Redis**:
  ```
  HGETALL instancia:{id}
  ```

## `GET /api/{tenant_id}/instances/{instance_id}/events`
Timeline de auditoría (`core_eventos`).
- 💎 **Cassandra** — `eventos_instancia` (lee **una sola partición**, ya ordenada):
  ```sql
  SELECT instance_id, timestamp, nodo, actor_id, accion, detalle
  FROM flowops.eventos_instancia
  WHERE tenant_id = ? AND instance_id = ?;
  ```

## `GET /api/{tenant_id}/events/by-date?date=YYYY-MM-DD`
Reporte de auditoría de un tenant en una fecha (reportes mensuales/diarios).
- 💎 **Cassandra** — `eventos_por_fecha` (partición `(tenant_id, fecha)`, una sola lectura):
  ```sql
  SELECT instance_id, timestamp, nodo, actor_id, accion, detalle
  FROM flowops.eventos_por_fecha
  WHERE tenant_id = ? AND fecha = ?;
  ```

## `GET /api/{tenant_id}/tasks?status=pending`
Lista tareas humanas del tenant.
- 🍃 **MongoDB** — `tareas`:
  ```js
  db.tareas.find({ tenant_id, status? }, { _id: 0 })
  ```

## `POST /api/{tenant_id}/tasks/{task_id}/complete`
Completa una tarea y **avanza la instancia** (`core_completar_tarea` → `core_avanzar`).
- 🍃 **MongoDB** — `tareas` (busca la tarea, valida idempotencia → **409** si ya está `completed`):
  ```js
  db.tareas.findOne({ tenant_id, task_id })
  ```
- Luego ejecuta el avance (ver `POST .../avanzar` abajo: Mongo + Tarea + Redis + Cassandra + Neo4j).

---

# 2. Rutas clásicas (usadas por el frontend)

## `POST /api/instancias/{iid}/avanzar`  ·  núcleo `core_avanzar`
Aprueba/rechaza y propaga el cambio a 4 motores. Incluye **guarda de idempotencia**
(si la instancia ya está finalizada → **HTTP 409**).
- 🍃 **MongoDB** — busca la instancia:
  ```js
  db.instancias.findOne({ tenant_id, instance_id })   // fallback: { instance_id }
  ```
- 🍃 **MongoDB** — actualiza estado/nodo:
  ```js
  db.instancias.updateOne({ instance_id },
    { $set: { estado, nodo_actual, updated_at } })
  ```
- 🍃 **MongoDB** — cierra la tarea humana del nodo:
  ```js
  db.tareas.updateOne({ task_id, status: "pending" },
    { $set: { status: "completed", completed_at, completed_by, decision } })
  ```
- ⚡ **Redis** — actualiza la caché:
  ```
  HSET instancia:{id} estado <estado> nodo_actual <final> updated_at <iso>
  ```
- 💎 **Cassandra** — evento de decisión + (si corresponde) notificación y fin:
  ```sql
  INSERT INTO flowops.eventos_instancia (...) VALUES (...);  -- decisión (approved/rejected)
  INSERT INTO flowops.eventos_instancia (...) VALUES (...);  -- notif_aprobacion/notif_rechazo
  INSERT INTO flowops.eventos_instancia (...) VALUES (...);  -- end (proceso_finalizado)
  ```
- 🕸️ **Neo4j** — relación de decisión:
  ```cypher
  MATCH (s:Solicitud {instance_id:$iid}), (e:Empleado {empleado_id:$eid})
  MERGE (e)-[:APRUEBA {timestamp:$ts, comentario:$c}]->(s)   // o :RECHAZA
  SET s.estado = $est
  ```

## `POST /api/instancias`
Igual que `POST .../instances` del spec → `core_crear_instancia` (4 motores, ver arriba).

## `GET /api/proceso?tenant=`
Primera definición del tenant (la usa el canvas). **Cache-aside con TTL.**
- ⚡ **Redis** — intenta el cache primero (`cache:proceso:{tenant}`, TTL 900 s):
  ```
  GET cache:proceso:{tenant}        // hit → devuelve y no toca Mongo
  ```
- 🍃 **MongoDB** — solo si hay miss (lee la fuente de verdad y recachea):
  ```js
  db.procesos.findOne({ tenant_id }, { _id: 0 })
  ```
  ```
  SET cache:proceso:{tenant} <json> EX 900     // recachea con TTL 15 min
  ```
  > La respuesta trae `_cache: "hit" | "miss"`. Al publicar un proceso se invalida
  > la clave (`DEL cache:proceso:{tenant}`). Las claves `instancia:*` también usan
  > TTL (24 h): el estado en Redis es caché, MongoDB es la verdad.

## `GET /api/instancias?tenant=`
Lista instancias + enriquece con el estado de Redis.
- 🍃 **MongoDB** — `instancias`:
  ```js
  db.instancias.find({ tenant_id }, { _id: 0 })
  ```
- ⚡ **Redis** — por cada instancia:
  ```
  HGETALL instancia:{id}
  ```

## `GET /api/instancias/{iid}?tenant=`
Una instancia + su caché.
- 🍃 **MongoDB**: `db.instancias.findOne({ tenant_id, instance_id }, { _id: 0 })`
- ⚡ **Redis**: `HGETALL instancia:{id}`

## `GET /api/instancias/{iid}/eventos?tenant=`
Auditoría. Idéntico al `GET .../events` del spec.
- 💎 **Cassandra**: `SELECT ... WHERE tenant_id=? AND instance_id=?`

## `GET /api/empleados`
- 🕸️ **Neo4j**:
  ```cypher
  MATCH (e:Empleado)
  OPTIONAL MATCH (e)-[:TIENE_ROL]->(r:Rol)
  RETURN e.empleado_id AS id, e.nombre AS nombre,
         e.departamento AS dep, e.saldo_dias AS saldo, r.nombre AS rol
  ORDER BY e.nombre
  ```

## `GET /api/grafo`
Relaciones empleado → solicitud (alimenta el modal del grafo).
- 🕸️ **Neo4j**:
  ```cypher
  MATCH (e:Empleado)-[r]->(sol:Solicitud)
  RETURN e.nombre AS empleado, e.departamento AS depto,
         type(r) AS relacion, sol.instance_id AS instancia,
         sol.estado AS estado, sol.dias_solicitados AS dias,
         sol.fecha_inicio AS fecha_inicio
  ORDER BY sol.instance_id, type(r)
  ```

## `GET /api/redis`
Volcado de todas las claves (pestaña Redis).
- ⚡ **Redis**:
  ```
  KEYS instancia:*      KEYS empleado:*
  TYPE <clave>
  HGETALL <clave>       // si es hash
  GET <clave>           // si es string (saldos)
  ```

---

# 3. Tenants y health

## `GET /api/tenants`
Empresas para el selector.
- 🍃 **MongoDB** — `tenants`:
  ```js
  db.tenants.find({}, { _id: 0 }).sort({ tenant_id: 1 })
  // fallback si está vacía:
  db.procesos.distinct("tenant_id");  db.instancias.distinct("tenant_id")
  ```

## `POST /api/tenants`
Crea empresa y le aprovisiona el proceso estándar.
- 🍃 **MongoDB** — `tenants`:
  ```js
  db.tenants.updateOne({ tenant_id },
    { $set: { tenant_id, name, status: "active", plan },
      $setOnInsert: { created_at } }, { upsert: true })
  ```
- 🍃 **MongoDB** — `procesos` (clona la plantilla si no existe):
  ```js
  db.procesos.countDocuments({ tenant_id, proceso_id: "proc_vacaciones_v1" })
  db.procesos.findOne({ proceso_id: "proc_vacaciones_v1" })   // plantilla
  db.procesos.insertOne(<copia con nuevo tenant_id>)
  ```

## `GET /api/status`  ·  evaluación de conectividad (Clase 06/13)
Mide la **latencia** de cada motor con una operación mínima.
- 🍃 **MongoDB Procesos**: `admin.command("ping")` + `db.procesos.countDocuments({})`
- 🍃 **MongoDB Instancias**: `db.instancias.countDocuments({})`
- ⚡ **Redis**: `PING` + `DBSIZE`
- 💎 **Cassandra**: `SELECT COUNT(*) FROM flowops.eventos_instancia`
- 🕸️ **Neo4j**: `MATCH (n) RETURN count(n)` + `MATCH ()-[r]->() RETURN count(r)`

## `GET /`
Sirve `index.html` (frontend). No toca bases.

---

## Resumen: qué motor toca cada endpoint

| Endpoint | 🍃 Mongo | ⚡ Redis | 💎 Cassandra | 🕸️ Neo4j |
|----------|:------:|:------:|:----------:|:------:|
| `POST .../processes` | ✅ | | | |
| `GET .../processes[/{id}]` | ✅ | | | |
| `POST .../instances` · `POST /api/instancias` | ✅ | ✅ | ✅ | ✅ |
| `GET .../instances/{id}` | ✅ | ✅ | | |
| `GET .../events` · `/eventos` | | | ✅ | |
| `GET .../tasks` | ✅ | | | |
| `POST .../tasks/{id}/complete` · `/avanzar` | ✅ | ✅ | ✅ | ✅ |
| `GET /api/proceso` | ✅ | | | |
| `GET /api/instancias` | ✅ | ✅ | | |
| `GET /api/empleados` · `/api/grafo` | | | | ✅ |
| `GET /api/redis` | | ✅ | | |
| `GET /api/tenants` · `POST /api/tenants` | ✅ | | | |
| `GET /api/status` | ✅ | ✅ | ✅ | ✅ |
