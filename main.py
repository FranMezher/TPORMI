"""
FlowOps API — TPO Ingeniería de Datos II
Punto de ensamblado de la aplicación (arquitectura por capas, Clase 12).

main.py ya NO contiene lógica: solo crea la app, monta los routers y dispara el
seed de arranque. La implementación vive en el paquete `flowops/`:

    flowops/config.py        → parámetros de conexión y constantes
    flowops/database.py      → conexiones lazy a los 5 motores + colecciones
    flowops/repositories.py  → acceso a datos (DAO, una sección por motor)
    flowops/schemas.py       → modelos Pydantic (contratos de la API)
    flowops/services.py      → lógica de negocio (core_* + escritura distribuida)
    flowops/routers/spec.py     → rutas multi-tenant del spec
    flowops/routers/classic.py  → rutas clásicas + status + tenants

Flujo del proceso:
  start → formulario → validacion_saldo
      saldo_ok     → aprobacion_gerencia → notif_aprobacion → end
      saldo_insuf. →                       notif_rechazo    → end

Contenedores Docker:
  flowops-instancias → MongoDB    → localhost:27018  (flowops_procesos + flowops_instancias)
  flowops-cache      → Redis      → localhost:6379
  flowops-auditoria  → Cassandra  → localhost:9042   keyspace: flowops
  flowops-grafo      → Neo4j      → bolt://localhost:7687
"""
import os

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from flowops import services
from flowops.routers import spec, classic

# ─── App ─────────────────────────────────────────────────────
app = FastAPI(title="FlowOps API", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

# ─── Routers (capa de presentación) ──────────────────────────
app.include_router(spec.router)
app.include_router(classic.router)


# ─── Arranque: seed + migración ──────────────────────────────
@app.on_event("startup")
def _startup():
    services.seed_and_migrate()


# ─── Frontend (single-page) ──────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def frontend():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    with open(path, encoding="utf-8") as f:
        return f.read()
