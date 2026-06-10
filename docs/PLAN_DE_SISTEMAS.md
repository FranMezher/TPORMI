# Plan de Sistemas — FlowOps

**TPO Ingeniería de Datos II · Grupo 7** — Rodriguez · Mezher · Romero Gomez · Guglielmone
Plataforma BPM NoSQL para procesos operativos configurables.

> Este documento consolida el **diseño conceptual** desarrollado en las Actividades 1–8 (análisis de datos, CAP, MongoDB, Cassandra, Neo4j, Redis) y lo conecta con el **prototipo implementado**. Donde el prototipo implementa un subconjunto del diseño, se indica explícitamente con la marca **[Prototipo]**.

---

## 1. Dominio del problema

FlowOps es una plataforma **SaaS multi-tenant** que permite a empresas definir **procesos operativos** como datos (no como código) y ejecutarlos. El caso modelado es **Solicitud de Vacaciones**.

### 1.1 Datos del dominio (Actividad 1)

| Dato | Estructura | ¿Cambia por tenant? | ¿Crece? | Motor destino |
|------|-----------|:---:|:---:|---------------|
| **Tenant** | Estructurado | Sí | Bajo | MongoDB |
| **ProcessDefinition** (proceso) | Semi-estructurado | Sí | Medio | MongoDB |
| **ProcessInstance** (instancia) | Semi-estructurado | Sí | Alto | MongoDB (+ Redis caché) |
| **Task** (tarea humana) | Estructurado/semi | Sí | Medio | MongoDB (+ Redis cola) |
| **Event** (evento/auditoría) | Semi-estructurado | Sí | **Muy alto** | Cassandra |
| **Form** (formulario) | Semi-estructurado | Sí | Medio | MongoDB |
| **Métricas** | No estructurado | No | Muy alto | Redis / series temporales |
| **Usuarios y Roles** | Estructurado | Sí | Bajo | MongoDB / Neo4j |

Diferenciación BPM clave (criterio de evaluación): **definición** (plantilla inmutable y versionada) vs **instancia** (ejecución mutable) vs **tarea** (acción humana pendiente) vs **evento** (hecho histórico inmutable).

### 1.2 El proceso (Actividad 7 / TPO Parte 2)

```
start → formulario → validacion_saldo (¿días ≤ saldo?) ─┬─ ok  → aprobacion (líder) ─┬─ aprobado  → notif_aprobacion (solicitante + RRHH) → end
                                                        │                            └─ rechazado → notif_rechazo (solicitante)        → end
                                                        └─ insuficiente ─────────────── notif_rechazo / corrección de fechas
```

Roles: **solicitante**, **aprobador** (líder/gerencia), **rrhh**. Dos decisiones: **automática** (control de saldo de días) y **humana** (aprobación del líder).

> **[Prototipo]** Implementa este flujo con 7 nodos (`start, formulario, validacion_saldo, aprobacion_gerencia, notif_aprobacion, notif_rechazo, end`). El rol aprobador se materializa como `gerencia`. La validación de saldo está modelada (la instancia pasa por el nodo) y el avance lo hace el actor con rol gerencia.

---

## 2. Arquitectura políglota (Actividades 5–8)

API monolítica modular en **FastAPI** que orquesta **5 motores NoSQL**, uno por cada forma de acceso a los datos (**persistencia políglota**). El detalle de componentes y flujos está en [ARQUITECTURA.md](ARQUITECTURA.md); los esquemas en [MODELO_DE_DATOS.md](MODELO_DE_DATOS.md).

| Subsistema | Motor | Modelo | Rol | Implementado |
|-----------|-------|--------|-----|:---:|
| Definiciones de proceso | MongoDB | Documental | Plantillas JSON (nodos + transiciones), versionadas | ✅ |
| Instancias / Tareas | MongoDB | Documental | Estado de ejecución + tareas humanas | ✅ |
| Estado rápido / saldos | Redis | Clave-valor | Caché de estado actual y saldo (con TTL) | ✅ |
| Eventos / auditoría | Cassandra | Columnar | Event log append-only, write-heavy | ✅ |
| Grafo organizacional y de flujo | Neo4j | Grafo | Empleados, roles, jerarquía, relaciones de solicitud | ✅ |
| Sesiones, colas, rate-limit, métricas | Redis | Clave-valor / List / Sorted Set | Patrones operativos (Act 8) | 🔶 diseñado, no en el prototipo |
| Búsqueda full-text | Elasticsearch | Índice invertido | Observabilidad y búsqueda (Act 7-H) | 🔶 contenedor levantado, no usado por la API |

> Para aprobar alcanza con ≥2 modelos NoSQL: el prototipo implementa **4 modelos distintos (5 instancias)**.

---

## 3. Multi-tenancy

- Todo dato principal lleva `tenant_id`.
- En **Cassandra** es parte de la **partition key** → aislamiento físico por empresa (Act 6).
- En **MongoDB** las consultas filtran por `tenant_id`; los documentos lo incluyen.
- La API expone rutas multi-tenant `/api/{tenant_id}/...` (ver §5).

> **[Prototipo]** Tenant por defecto cargado: `empresa_01` (en las actividades figura como `tenant_grupo7`; es el mismo concepto de tenant raíz).

---

## 4. Decisiones de persistencia (justificación — Act 5–8)

| Decisión | Por qué |
|----------|---------|
| Definición e instancias en **MongoDB** | Documento JSON anidado (nodos/transiciones, `data` variable por proceso); **esquema flexible** y versionado, sin JOINs (Act 5). |
| Auditoría en **Cassandra** | Patrón **append-only / write-heavy**, time-series por instancia. PK `(tenant_id, instance_id)` → historial sin `ALLOW FILTERING`; escala horizontal (Act 6). |
| Estado en **Redis** | Lectura de baja latencia del estado caliente y del saldo; **caché**, no fuente de verdad; **TTL** (Act 8). |
| Relaciones en **Neo4j** | Jerarquía (`REPORTA_A`), roles y relaciones `SOLICITA/APRUEBA/NOTIFICADO`; traversal de caminos del flujo imposible eficientemente en SQL/JSON (Act 7). |
| Métricas en **Redis/series temporales** | Contadores `INCR` y dashboards en tiempo real, reconstruibles desde Cassandra (Act 8). |
| Separar definición vs instancia | Versionar procesos sin afectar instancias en curso (Act 5-D). |

---

## 5. API mínima

**Rutas del spec (multi-tenant):**

| Método | Endpoint | Función |
|--------|----------|---------|
| POST | `/api/{tenant_id}/processes` | Crear definición de proceso |
| GET | `/api/{tenant_id}/processes` | Listar definiciones |
| GET | `/api/{tenant_id}/processes/{process_id}` | Consultar definición |
| POST | `/api/{tenant_id}/processes/{process_id}/instances` | Iniciar instancia |
| GET | `/api/{tenant_id}/instances/{instance_id}` | Estado de instancia |
| GET | `/api/{tenant_id}/tasks?status=pending` | Tareas humanas |
| POST | `/api/{tenant_id}/tasks/{task_id}/complete` | Completar tarea y avanzar |
| GET | `/api/{tenant_id}/instances/{instance_id}/events` | Auditoría |

Documentación interactiva (Swagger) autogenerada en **`/docs`**. Frontend tipo n8n en `/`.

---

## 6. Análisis CAP y consistencia (Actividad 3)

FlowOps es una **composición de motores**, cada uno con su posicionamiento CAP. El análisis es por componente.

| Componente | Criticidad | CAP | Modelo de consistencia | Motor |
|-----------|-----------|-----|------------------------|-------|
| Configuración del tenant | Baja | Balance | Causal | MongoDB |
| Definición publicada de proceso | Alta | **CP** | Strong | MongoDB |
| Estado actual de instancia | Muy alta | **CP** | Strong | MongoDB |
| Tareas humanas | Muy alta | **CP** | Strong / Session | MongoDB |
| Eventos de auditoría | Alta | **AP** | Eventual (append-only) | Cassandra |
| Métricas operativas | Baja | **AP** | Eventual | Redis |

**Preguntas del spec respondidas (Act 3 + implementación):**

- **Datos que toleran consistencia eventual:** métricas, caché de estado (Redis) y visualización de auditoría (Cassandra). La verdad del estado vive en MongoDB.
- **Si se duplica un evento:** Cassandra usa `event_id` (UUID) en la clustering key → cada evento es único; al ser append-only, los duplicados se distinguen y no corrompen el estado (que no se deriva sumando eventos).
- **Si una tarea se completa dos veces:** **operación idempotente** — `core_avanzar` rechaza con **HTTP 409** si la instancia no está `pendiente` o ya está en `end`; `core_completar_tarea` rechaza si la tarea ya está `completed`. En auditoría queda: primer intento OK, segundo rechazado, actor, timestamp y motivo. *(Responde directamente al Escenario 1 de Act 3.)* **[Implementado]**
- **Cómo se evitan estados inválidos:** el siguiente nodo se calcula con la función de transición `sig_nodo(nodo, accion)`; no se aceptan saltos arbitrarios; el estado solo avanza desde `pendiente`.
- **Partición de red (Act 3 Escenario 3):** los eventos (AP) se siguen aceptando; el avance de instancia (CP) se bloquea si no puede confirmarse el estado. Reconciliar luego: eventos pendientes, estado e tareas.
- **Configuración modificada en ejecución (Escenario 4):** instancias viejas conservan su versión; nuevas usan la publicada → **versionado de procesos**.
- **Consultas que optimiza cada modelo:** Mongo: documento por id. Cassandra: historial ordenado por tiempo de una instancia. Redis: estado/saldo O(1). Neo4j: traversal de relaciones y caminos.

---

## 7. Diseño conceptual vs Prototipo (alcance honesto)

| Subsistema | Diseñado en clase | Implementado en el prototipo |
|-----------|-------------------|------------------------------|
| MongoDB | 6 colecciones (tenants, process_definitions, process_instances, tasks, forms, notification_templates) con embedding/referencing e índices (Act 5) | `tenants`, `procesos`, `instancias`, `tareas` con `tenant_id`; alta de empresa aprovisiona el proceso |
| Cassandra | 3 tablas orientadas a consulta (events_by_instance, events_by_tenant_date, events_by_actor) + niveles ONE/QUORUM (Act 6) | 1 tabla `eventos_instancia` con PK `(tenant_id, instance_id)` |
| Neo4j | 8 tipos de nodo + 11 relaciones (Act 7) | Empleado, Rol, Solicitud, NodoProceso + relaciones SOLICITA/APRUEBA/NOTIFICADO/REPORTA_A/SIGUIENTE |
| Redis | 6 patrones: caché, sesiones, colas, sorted sets, rate-limit, contadores (Act 8) | Caché de estado (Hash) + saldo de días |
| Elasticsearch | Búsqueda full-text / observabilidad (Act 7-H) | Contenedor disponible, no integrado a la API |

El prototipo implementa el **núcleo BPM end-to-end** (definir proceso → iniciar instancia → completar tarea → auditar) sobre 4 motores; el resto del diseño queda documentado como evolución.

---

## 8. Limitaciones y mejoras futuras

- Escritura en los 4 motores es **best-effort** (dual write): si un motor secundario falla, la API devuelve `warnings` sin rollback. Mejora: **patrón Outbox / Saga** para consistencia eventual garantizada.
- Validación de saldo simplificada (la instancia pasa a aprobación). Mejora: leer `saldo_dias` de Neo4j/Redis y bifurcar a rechazo automático cuando `dias > saldo`.
- Sin autenticación (el spec no la exige). Mejora: API Key / sesiones en Redis (Act 8).
- Tablas de Cassandra y patrones de Redis adicionales quedan como diseño (Act 6/8) no implementado.
