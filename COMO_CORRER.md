# FlowOps API — Cómo correr el prototipo

## Requisitos previos
- Docker con los contenedores del TPO corriendo (`bash load_all.sh`)
- Python 3.10+

## 1. Instalar dependencias

```bash
cd flowops-api
pip install -r requirements.txt
```

## 2. Levantar la API

```bash
uvicorn main:app --reload --port 8000
```

## 3. Abrir el frontend

Ir a **http://localhost:8000** en el navegador.

---

## API multi-tenant (rutas del spec del TPO)

Documentación interactiva (Swagger) autogenerada en **http://localhost:8000/docs**.

| Método | URL | Descripción |
|--------|-----|-------------|
| POST | `/api/{tenant_id}/processes` | Crear definición de proceso |
| GET | `/api/{tenant_id}/processes` | Listar definiciones |
| GET | `/api/{tenant_id}/processes/{process_id}` | Consultar definición |
| POST | `/api/{tenant_id}/processes/{process_id}/instances` | Iniciar instancia |
| GET | `/api/{tenant_id}/instances/{instance_id}` | Estado de una instancia |
| GET | `/api/{tenant_id}/tasks?status=pending` | Tareas humanas |
| POST | `/api/{tenant_id}/tasks/{task_id}/complete` | Completar tarea y avanzar |
| GET | `/api/{tenant_id}/instances/{instance_id}/events` | Auditoría (Cassandra) |

> `tenant_id` por defecto: `empresa_01`. Completar una tarea ya completada devuelve **HTTP 409** (idempotencia).

## Endpoints clásicos (usados por el frontend)

| Método | URL | Descripción |
|--------|-----|-------------|
| GET | `/api/status` | Estado de los 4 motores |
| GET | `/api/proceso` | Definición del proceso (MongoDB) |
| GET | `/api/instancias` | Todas las instancias (MongoDB + Redis) |
| GET | `/api/instancias/{id}` | Una instancia |
| GET | `/api/instancias/{id}/eventos` | Log de auditoría (Cassandra) |
| POST | `/api/instancias` | Crear nueva solicitud (escribe en los 4 DBs) |
| POST | `/api/instancias/{id}/avanzar` | Aprobar/rechazar (actualiza los 4 DBs) |
| GET | `/api/empleados` | Empleados desde Neo4j |
| GET | `/api/grafo` | Relaciones (Empleado)-[r]->(Solicitud) en Neo4j |
| GET | `/api/redis` | Todas las claves Redis |

## Reset de datos / demo limpia

`load_all.py` es **idempotente**: borra antes de cargar en cada motor y ahora
también limpia las colecciones `instancias` y `tareas` de Mongo (las "cosas
raras" acumuladas). Dos modos:

```powershell
# A) Cargar con datos demo (3 instancias ya iniciadas/terminadas)
$env:PYTHONUTF8=1; python load_all.py
python -m uvicorn main:app --port 8000 --reload

# B) Demo LIMPIA: solo estructura (definición + empleados + saldos), sin instancias
$env:PYTHONUTF8=1; python load_all.py --limpio
$env:FLOWOPS_SEED_DEMO=0; python -m uvicorn main:app --port 8000 --reload
```

- **`--limpio`** omite las solicitudes demo de Neo4j, los eventos de Cassandra y
  los hashes de instancia de Redis; deja el saldo de `emp_001` en 15 para poder
  solicitar desde cero.
- **`FLOWOPS_SEED_DEMO=0`** evita que el arranque de la API resiembre las 3
  instancias demo. Así la base queda vacía de ejecuciones y podés correr todo el
  proceso en vivo.

Para un reset **total** (borra volúmenes Docker): `docker compose down -v` →
`docker compose up -d` → esperar ~30 s → `python load_all.py [--limpio]`.

> **Nuevo proceso desde el front:** el botón ➕ *Nuevo proceso* ya crea un
> esqueleto completo (start → formulario con campos → aprobación → notificación →
> end), así el formulario no queda vacío. Editás, conectás y guardás con 💾.

## Flujo del proceso

```
start → formulario → validacion_saldo
            saldo ok       → aprobacion_gerencia
                                 ↓ approved → notif_aprobacion → end (estado: aprobada)
                                 ↓ rejected → notif_rechazo    → end (estado: rechazada)
            saldo insuf.   → notif_rechazo → end (estado: rechazada)
```

## Datos de prueba cargados por load_all.sh

| instance_id | Solicitante | Días | Estado |
|-------------|-------------|------|--------|
| inst_vac_2026_001 | emp_001 (Juan) | 15 | aprobada |
| inst_vac_2026_002 | emp_004 (Ana) | 12 | rechazada |
| inst_vac_2026_003 | emp_005 (Luis) | 5 | pendiente |

Para probar el flujo: la instancia `inst_vac_2026_003` está pendiente en `aprobacion_gerencia`.
En el panel, ir a **Instancias** → botón **▶ Avanzar** → Actor: `emp_003` → Aprobar/Rechazar.
