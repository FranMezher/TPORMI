# Práctica 12 / Clase 06 — Conectividad y plan de demostración

**TPO FlowOps — Ingeniería de Datos II — Grupo 7**

Plan de conectividad y demostración de la arquitectura políglota de FlowOps
(proceso *Solicitud de Vacaciones*). Los valores de latencia son **medidos** por
el endpoint `GET /api/status` (evaluación de conectividad por motor).

---

## Parte A — Matriz de conectividad

| Motor / Tecnología | Uso en FlowOps | Operación mínima de prueba | Evidencia esperada | Riesgo |
|--------------------|----------------|----------------------------|--------------------|--------|
| **MongoDB** :27018 | Definiciones de proceso, instancias y tareas (fuente de verdad documental) | `GET /api/empresa_01/processes/proc_vacaciones_v1` (leer definición publicada) | JSON con `nodos`+`transiciones`; Dashboard → "MongoDB: ok, N docs" | Mongo nativo de Windows en 27017 choca con Docker → mitigado usando 27018 |
| **Cassandra** :9042 | Event log de auditoría, append-only (event sourcing) | Insertar evento al avanzar y consultarlo: `GET /api/empresa_01/instances/{id}/events` | Timeline de 6 eventos en pestaña **Auditoría** | Arranque lento del contenedor; mayor latencia de primera conexión |
| **Neo4j** :7687 | Empleados, roles, jerarquía y relaciones SOLICITA/APRUEBA | `GET /api/grafo` (caminos empleado→solicitud) | **Modal de grafo** dibujado; Dashboard → nodos/relaciones | Driver Bolt no conecta; grafo desincronizado |
| **Redis** :6379 | Caché del estado actual de instancia y saldo (TTL) | `GET /api/redis` (leer estado cacheado `instancia:*`) | Pestaña **Redis** con hash de estado | Caché atrasada respecto de Mongo (consistencia eventual) |
| **Elasticsearch** :9200 | Búsqueda full-text (diseñado, contenedor disponible) | — | Contenedor levantado | No consumido por la API (alcance) |
| **IRIS** | No se incorpora | — | — | No aplica |

Operaciones mínimas por motor (resumen): **Mongo** = leer definición publicada ·
**Cassandra** = insertar `TASK_COMPLETED` y consultar por `instance_id` · **Neo4j**
= caminos START→END · **Redis** = leer estado cacheado de una instancia.

---

## Parte B — Métricas mínimas

Medidas reales del laboratorio (warm) vía `GET /api/status`.

| Métrica | Cómo se mide en el TPO | Valor esperado razonable | Qué indicaría un problema |
|---------|------------------------|--------------------------|---------------------------|
| Latencia de lectura de estado | `/api/status` → Redis `ping`+`dbsize` | ~3 ms | >50 ms o `ok=false` → Redis caído |
| Latencia de escritura de evento | `/api/status` → Cassandra `COUNT` (proxy) | ~15 ms | >100 ms → cluster degradado |
| Tiempo de inicio de instancia | Duración de `POST .../instances` (escribe 4 motores) | <150 ms | >1 s → un motor lento bloquea |
| Error rate de endpoints | Proporción de respuestas HTTP 5xx | ~0 % | >0 % sostenido → falla sistémica |
| Cantidad de eventos por instancia | Largo del timeline en **Auditoría** | 6 (alta) → 8 (con aprobación) | 0 → no se auditó (Cassandra caída) |
| Cache hit / miss | `redis_estado` presente en `GET /api/instancias` | Hit en instancias activas | Miss siempre → TTL vencido / Redis caído |
| Tiempo de consulta de grafo | `/api/status` → Neo4j `count(n)`/`count(r)` | ~16 ms | >100 ms → grafo grande sin índice |

**Preguntas guía:** (1) usuario final → *latencia de lectura de estado*; (2)
auditoría → *cantidad de eventos por instancia* + *latencia de escritura*; (3)
justifica Redis → *cache hit / latencia de lectura*; (4) justifica Cassandra →
*escritura append de eventos / cantidad por instancia*; (5) justifica Neo4j →
*tiempo de consulta de grafo*.

---

## Parte C — Escenarios de prueba

| N.º | Escenario | Pasos | Resultado esperado | Bases involucradas |
|-----|-----------|-------|--------------------|--------------------|
| 1 | Iniciar instancia | Canvas → **▶ Ejecutar** → completar form → enviar | Instancia `pendiente` en `aprobacion_gerencia`; tarea creada | Mongo + Redis + Cassandra + Neo4j |
| 2 | Completar tarea humana | Clic en nodo `aprobacion_gerencia` → **Aprobar** (`emp_003`) | Tarea `completed` una sola vez; instancia avanza a `end` | Mongo + Redis + Cassandra + Neo4j |
| 3 | Consultar estado actual | Pestaña **Ejecuciones** (lee Redis con fallback a Mongo) | Estado/nodo cacheado al instante | Redis (+ Mongo) |
| 4 | Consultar auditoría | Pestaña **Auditoría** → elegir instancia | Timeline de eventos (quién/qué/cuándo) | Cassandra |
| 5 | Validar flujo / camino | Canvas (definición) + **Grafo Neo4j** | Camino START→END coherente con la definición | Mongo (def) + Neo4j |
| 6 | Simular error / caso inválido | Aprobar una instancia ya finalizada | **HTTP 409** (idempotencia), sin doble avance | Mongo |

---

## Parte D — Fallas posibles y respuesta del sistema

| Falla | Impacto | ¿Continúa? | Respuesta del sistema | Evidencia |
|-------|---------|------------|-----------------------|-----------|
| Redis no disponible | Bajo (solo caché) | **Sí** | Escritura best-effort: agrega `warning`, Mongo sigue siendo verdad | `warnings` en la respuesta + Dashboard Redis en rojo |
| Event log (Cassandra) no disponible | Medio (sin auditoría) | **Parcial** | `warning`; la operación de negocio igual avanza | `warnings` + Auditoría vacía + Dashboard Cassandra rojo |
| Definición de proceso no encontrada | Alto | **No** | **HTTP 404**, bloquea esa operación | Código 404 en `/processes/{id}` |
| Tarea ya completada | Bajo | **No** (correcto) | **HTTP 409** idempotencia | Código 409 al recompletar |
| Tenant inválido | Bajo | **Parcial** | Devuelve vacío (`{}` / `[]`), no rompe | 200 con cuerpo vacío |
| Grafo inconsistente | Bajo | **Sí** | `warning` Neo4j; no bloquea el flujo | Dashboard Neo4j + `warnings` |
| Timeout de base de datos | Medio | **Parcial** | `serverSelectionTimeoutMS=3000` → error controlado, no cuelga | Excepción capturada → 500/`warning` |

**Preguntas guía:** crítica = *definición de proceso no encontrada*; con fallback
= *Redis no disponible*; requiere reintento = *timeout de DB*; debe quedar
auditada = *tarea completada* (queda en Cassandra); debe bloquear = *tarea ya
completada* y *tenant/instancia inválida*.

---

## Parte E — Checklist de demostración

| Ítem | Estado | Observación |
|------|--------|-------------|
| El repositorio está actualizado | **OK** | Rama `fran` pusheada |
| Docker Compose levanta los servicios | **OK** | `docker compose up -d` (Mongo, Redis, Cassandra, Neo4j, ES, mongo-express) |
| Las bases tienen datos de prueba | **OK** | `seed_and_migrate` + `load_all.py` |
| La API responde en los endpoints principales | **OK** | `GET /api/status` mide los 5 motores |
| Se puede iniciar una instancia | **OK** | Canvas → ▶ Ejecutar |
| Se puede completar una tarea | **OK** | Clic en nodo → Aprobar/Rechazar |
| Se puede consultar auditoría | **OK** | Pestaña Auditoría (Cassandra) |
| Se puede mostrar al menos una consulta por motor | **OK** | Dashboard + Redis + Auditoría + Grafo + canvas |
| Hay capturas o video de respaldo | **Pendiente** | Grabar la corrida como plan B |
| El README explica cómo ejecutar | **OK** | `README.md` (sección "Cómo ejecutar") |

---

## Parte F — Plan de demostración (8–10 min)

| Minuto | Qué se muestra (en el front) | Objetivo |
|--------|------------------------------|----------|
| 0–1 | Pestaña **Workflow**: el canvas del proceso de vacaciones | Contextualizar el dominio |
| 1–2 | Pestaña **Dashboard**: 5 motores conectados + latencia (semáforo) | Justificar tecnologías + conectividad |
| 2–4 | **▶ Ejecutar workflow** → formulario → enviar; punto animado | Flujo principal (escribe en 4 motores) |
| 4–5 | Clic en nodo `aprobacion_gerencia` → **Aprobar** | Cambio de estado / tarea humana |
| 5–6 | Pestaña **Auditoría**: timeline de la instancia | Justificar el event log (Cassandra) |
| 6–7 | **Grafo Neo4j** (modal) + pestaña **Redis** | Segunda y tercera tecnología |
| 7–8 | **Dashboard** / `/api/status`: latencia por motor | Validación técnica (Clase 06) |
| 8–10 | Decisiones y límites (ES no consumido, consistencia eventual) | Defender el alcance |

**Respuestas:** (1) lo que no puede fallar = *iniciar instancia* (es el flujo
central); (2) si una herramienta local falla = mostrar `/api/status` y `/docs` +
captura de respaldo; (3) evidencia alternativa = video/capturas de la corrida;
(4) pregunta difícil esperada = *"¿qué pasa si falla un motor en mitad de la
escritura?"* → best-effort + warnings + outbox como mejora; (5) decisión que
defendemos con énfasis = **persistencia políglota** (un motor por patrón de acceso).

---

## Parte G — Matriz de riesgos técnicos

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|------------|
| No levanta un contenedor | Media | Alto | `docker compose up -d` con anticipación; healthcheck `/api/status` antes de exponer |
| Falta un dato de prueba | Baja | Medio | `seed_and_migrate` en el arranque + `load_all.py` |
| Endpoint no responde | Baja | Alto | Conexiones lazy + timeout 3 s; probar `/api/status` antes |
| Consulta tarda demasiado | Media | Medio | Cassandra/Neo4j calientan en la 1ª llamada; "precalentar" con un `/api/status` previo |
| El grupo no puede explicar una tecnología | Baja | Alto | Guion oral con keyword por motor (`GUION_ORAL.md`) |
| Decisión NoSQL no está justificada | Baja | Alto | Matriz Parte A + `docs/MODELO_DE_DATOS.md` (un motor por patrón) |

---

## Puesta en común — prueba mínima que demuestra que la arquitectura funciona

> **Completar una tarea humana** (`POST /api/{tenant}/tasks/{id}/complete`):
> involucra **MongoDB** (actualiza la instancia y marca la tarea) y **Cassandra**
> (registra el evento `aprobacion`+`notificacion`+`end`); la **evidencia** es el
> timeline de auditoría y la latencia medida en `/api/status`; el **riesgo
> técnico** es el doble avance, mitigado con la guarda de idempotencia (**HTTP 409**).
