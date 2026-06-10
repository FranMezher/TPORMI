# FlowOps — Plataforma BPM NoSQL

**TPO Ingeniería de Datos II**

Plataforma SaaS multi-tenant para definir y ejecutar **procesos operativos configurables** (BPM), inspirada en n8n. Caso modelado: **Solicitud de Vacaciones**. La gracia del trabajo es la **persistencia políglota**: 5 motores NoSQL, cada uno elegido por su patrón de acceso.

## Integrantes
- RODRIGUEZ BELEN MERCEDES
- MEZHER FRANCO ADRIAN
- ROMERO GOMEZ MARIA SOL
- GUGLIELMONE LUCAS

---

## Proceso: Solicitud de Vacaciones

```
start → formulario → validacion_saldo (¿días ≤ saldo?) ─┬─ ok  → aprobacion_gerencia ─┬─ aprobado  → notif_aprobacion (empleado + RRHH) → end
                                                        │                            └─ rechazado → notif_rechazo (empleado)          → end
                                                        └─ insuficiente ─────────────── notif_rechazo → end
```

- **Roles:** solicitante, aprobador (gerencia), RRHH.
- **Decisiones:** automática (validación de días hábiles vs saldo) y humana (aprobación de gerencia).
- **Auditoría:** cada evento (quién, qué, cuándo) queda registrado de forma inmutable.

---

## Arquitectura — Persistencia políglota

```
                Frontend (canvas tipo n8n)  +  Swagger /docs
                              │ HTTP/JSON
                              ▼
                     API FlowOps (FastAPI)
        ┌──────────────┬──────────┬───────────┬──────────────┐
        ▼              ▼          ▼           ▼              ▼
   MongoDB :27018   Redis     Cassandra    Neo4j      Elasticsearch
  (2 bases lógicas) :6379     :9042        :7687      :9200
   procesos/tenants  caché    auditoría    grafo      (búsqueda,
   instancias/tareas estado   event log    relaciones  diseño)
```

| Motor | Modelo NoSQL | Rol en FlowOps |
|-------|--------------|----------------|
| **MongoDB** (1 instancia, 27018) | Documental | Definiciones de proceso + `tenants` (base `flowops_procesos`); instancias + tareas (base `flowops_instancias`) |
| **Redis** | Clave-valor | Caché del estado actual y saldo de días (TTL) |
| **Cassandra** | Columnar | Event log de auditoría, append-only. PK `(tenant_id, instance_id)` |
| **Neo4j** | Grafo | Empleados, roles, jerarquía y relaciones de solicitud/aprobación |
| **Elasticsearch** | Índice invertido | Búsqueda full-text (diseñado, contenedor disponible) |

> No se usa ningún motor relacional: el estado de instancias vive en MongoDB (documental). El detalle del diseño está en [docs/](docs/) (Plan de Sistemas, Modelo de Datos, Arquitectura).

---

## Características

- **Canvas de workflow tipo n8n**: nodos, transiciones, pan/zoom, ejecución animada y avance desde el propio nodo.
- **Multi-tenant**: entidad `Tenant` + `tenant_id` en todos los motores; alta de empresa aprovisiona su proceso.
- **Formulario data-driven**: los campos salen de la definición del proceso; agregar un campo no requiere tocar código. `dias_solicitados` es **calculado** (días hábiles).
- **Idempotencia**: completar una tarea dos veces devuelve HTTP 409 (análisis CAP aplicado).
- **Visualización de bases**: mongo-express, Neo4j Browser y un grafo dibujado en la app.

---

## Cómo ejecutar

### Requisitos
- Docker Desktop
- Python 3.10+ (`pip install -r requirements.txt`)

### 1. Levantar los motores
```bash
docker compose up -d
```

### 2. Cargar datos iniciales
```bash
# Linux/Mac
bash load_all.sh
# Windows (PowerShell)
$env:PYTHONUTF8=1; python load_all.py
```

### 3. Levantar la API
```bash
python -m uvicorn main:app --port 8000 --reload
```

### 4. Abrir
- **App**: http://localhost:8000
- **Swagger (API)**: http://localhost:8000/docs
- **mongo-express**: http://localhost:8081
- **Neo4j Browser**: http://localhost:7474 (`neo4j` / `flowops123`)

---

## API (resumen)

Rutas multi-tenant según el spec (ver todas en `/docs`):

| Método | Endpoint |
|--------|----------|
| POST | `/api/{tenant_id}/processes` |
| GET | `/api/{tenant_id}/processes/{process_id}` |
| POST | `/api/{tenant_id}/processes/{process_id}/instances` |
| GET | `/api/{tenant_id}/instances/{instance_id}` |
| POST | `/api/{tenant_id}/tasks/{task_id}/complete` |
| GET | `/api/{tenant_id}/instances/{instance_id}/events` |

---

## Documentación

- [docs/PLAN_DE_SISTEMAS.md](docs/PLAN_DE_SISTEMAS.md) — dominio, persistencia, CAP, decisiones
- [docs/MODELO_DE_DATOS.md](docs/MODELO_DE_DATOS.md) — esquemas, claves e índices por motor
- [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md) — componentes y flujos de datos
- [COMO_CORRER.md](COMO_CORRER.md) — endpoints y puesta en marcha
- [GUION_ORAL.md](GUION_ORAL.md) — guía para la defensa oral

### Detener el ambiente
```bash
docker compose down
```
