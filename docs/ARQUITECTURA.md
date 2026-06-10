# Arquitectura — FlowOps

Consolida la **arquitectura políglota** definida progresivamente en las Actividades 5–8.

## Diagrama de componentes y flujo de datos

```
                          ┌─────────────────────────────┐
                          │   Frontend (index.html)     │
                          │  Canvas tipo n8n + Swagger  │
                          └──────────────┬──────────────┘
                                         │ HTTP/JSON
                                         ▼
                          ┌─────────────────────────────┐
                          │     API FlowOps (FastAPI)    │  ← único punto de entrada
                          │  rutas /api/{tenant_id}/...  │    (no se accede a las BD directo)
                          ├─────────────────────────────┤
                          │  core_crear_instancia()      │
                          │  core_avanzar()              │
                          │  core_completar_tarea()      │
                          │  core_eventos()              │
                          └──┬─────┬───────┬───────┬─────┘
            ┌────────────────┘     │       │       └────────────────┐
            ▼                      ▼       ▼                        ▼
   ┌─────────────────┐   ┌─────────────────┐   ┌──────────────┐   ┌──────────────┐
   │ MongoDB :27017  │   │ MongoDB :27018  │   │  Redis :6379 │   │ Cassandra    │
   │ flowops_procesos│   │flowops_instancias│  │  caché +     │   │ :9042        │
   │  · procesos     │   │  · instancias   │   │  saldos      │   │ auditoría    │
   │ (definiciones)  │   │  · tareas       │   │ (TTL)        │   │ (append-only)│
   └─────────────────┘   └─────────────────┘   └──────────────┘   └──────────────┘
        ~5ms                   ~5ms               <1ms                ~10ms
                                         │
                                         ▼
                                ┌──────────────────┐     ┌──────────────────┐
                                │   Neo4j :7687    │     │ Elasticsearch    │
                                │  empleados, roles│     │ :9200            │
                                │  jerarquía, flujo│     │ (búsqueda/obsv.) │
                                └──────────────────┘     └──────────────────┘
                                     ~5ms                  🔶 no usado por la API
```

Todos los contenedores corren con **Docker Compose** en la red `flowops-net`.

## Matriz de responsabilidades (Act 5-I / 7-H / 8-H)

| Subsistema | Base principal | Redis interviene | Rol |
|-----------|----------------|:---:|-----|
| Definiciones de proceso | MongoDB | caché (cache-aside, TTL 15 min) | JSON completo + topología en Neo4j |
| Estado de instancia | MongoDB | sí (Hash, TTL 24 h) | fuente de verdad documental, caché rápida |
| Tareas humanas | MongoDB | sí (Sorted Set por rol) | bandeja por rol; Mongo = verdad |
| Eventos de auditoría | Cassandra | no | append-only, alto volumen |
| Flujo / caminos | Neo4j | no | traversal, detección de anomalías |
| Sesiones | Redis | **es la base** | efímero, TTL 8 h |
| Métricas / contadores | Redis | sí (`INCR`) | dashboards en tiempo real |
| Búsqueda full-text | Elasticsearch | no | observabilidad (diseño) |

## Flujo de una escritura (crear instancia)

`POST /api/{tenant}/processes/{pid}/instances` →

1. **MongoDB instancias** → inserta el documento (`estado=pendiente`, `nodo_actual=aprobacion_gerencia`).
2. **MongoDB tareas** → crea la `Task` humana pendiente (rol aprobador/gerencia).
3. **Redis** → cachea el estado actual (`instancia:{id}`) con TTL 24 h.
4. **Cassandra** → registra eventos `start`, `formulario`, `validacion_saldo`, `aprobacion_gerencia`.
5. **Neo4j** → crea `Solicitud` y la relación `(:Empleado)-[:SOLICITA]->(:Solicitud)`.

Si un motor **secundario** (Redis/Cassandra/Neo4j) falla, la operación continúa y devuelve `warnings`; solo MongoDB (fuente de verdad) aborta con HTTP 500.

## Flujo de avance (completar tarea) — con idempotencia

`POST /api/{tenant}/tasks/{task_id}/complete` → valida tarea `pending` → `core_avanzar`:

1. **Guarda de idempotencia (CAP Act 3):** si la instancia no está `pendiente` → **HTTP 409**.
2. MongoDB instancias → actualiza `estado` y `nodo_actual`.
3. MongoDB tareas → marca la tarea `completed`.
4. Redis → actualiza el estado cacheado.
5. Cassandra → evento de decisión + notificación.
6. Neo4j → relación `(:Empleado)-[:APRUEBA|RECHAZA]->(:Solicitud)`.

## Tecnologías

| Capa | Tecnología |
|------|-----------|
| API | FastAPI 0.110 + Uvicorn |
| Drivers | pymongo, redis-py, cassandra-driver, neo4j |
| Frontend | HTML/CSS/JS vanilla (canvas SVG, sin frameworks) |
| Orquestación | Docker Compose (servicios: 2× MongoDB, Redis, Cassandra, Neo4j, Elasticsearch) |
| Lenguaje | Python 3.10+ |
