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

## Endpoints disponibles

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
