"""
Capa de lógica de negocio.

Orquesta los repositorios para cumplir los casos de uso del workflow. Acá viven
las reglas (cálculo de días hábiles, máquina de estados, idempotencia) y la
*escritura distribuida* a los cuatro motores con degradación best-effort: si un
motor secundario falla, se acumula un warning pero la operación principal sigue.
"""
import json
from datetime import datetime, date, timedelta
from typing import Any, Dict, List

from fastapi import HTTPException

from . import config, repositories as repo

# ─── Reglas del dominio ──────────────────────────────────────
def dias_habiles(fi, ff):
    """Días hábiles (lun–vie) entre dos fechas ISO, inclusive. None si inválidas."""
    try:
        d0 = date.fromisoformat(str(fi)[:10])
        d1 = date.fromisoformat(str(ff)[:10])
    except Exception:
        return None
    if d1 < d0:
        return 0
    n, cur = 0, d0
    while cur <= d1:
        if cur.weekday() < 5:   # 0=lun … 4=vie
            n += 1
        cur += timedelta(days=1)
    return n


def extract_solicitud(body: Dict[str, Any]):
    """Acepta {empleado_id, datos:{...}} o un objeto plano; devuelve (empleado_id, datos)."""
    if not isinstance(body, dict):
        raise HTTPException(400, "Cuerpo inválido")
    if isinstance(body.get("datos"), dict):
        datos = dict(body["datos"])
        empleado_id = body.get("empleado_id") or datos.get("empleado_id")
    else:
        empleado_id = body.get("empleado_id")
        datos = {k: v for k, v in body.items() if k != "empleado_id"}
    datos.pop("empleado_id", None)
    if not empleado_id:
        raise HTTPException(400, "Falta 'empleado_id'")
    # dias_solicitados es CALCULADO: se deriva de las fechas, no se confía en el cliente
    if datos.get("fecha_inicio") and datos.get("fecha_fin"):
        d = dias_habiles(datos["fecha_inicio"], datos["fecha_fin"])
        if d is not None:
            datos["dias_solicitados"] = d
    return empleado_id, datos


def sig_nodo(nodo: str, accion: str) -> tuple:
    """Retorna (nodo_siguiente, nuevo_estado). El avance manual ocurre en aprobacion_gerencia."""
    if nodo == "aprobacion_gerencia":
        if accion == "approved":
            return ("notif_aprobacion", "aprobada")
        return ("notif_rechazo", "rechazada")
    if nodo in ("notif_aprobacion", "notif_rechazo"):
        return ("end", "finalizada")
    return ("end", "finalizada")


# ═══════════════════════════════════════════════════════════════
#  Casos de uso (tenant-aware) — reutilizados por ambas familias de rutas
# ═══════════════════════════════════════════════════════════════
def core_crear_instancia(tenant_id: str, empleado_id: str, datos: Dict[str, Any],
                         process_id: str = "proc_vacaciones_v1") -> dict:
    datos = dict(datos or {})
    now   = datetime.utcnow()
    iid   = "inst_vac_" + now.strftime("%Y%m%d_%H%M%S")
    warns = []

    # 1. MongoDB ─────────────────────────────────────────────
    try:
        repo.insert_instancia({
            "tenant_id":      tenant_id,
            "instance_id":    iid,
            "proceso_id":     process_id,
            "solicitante_id": empleado_id,
            "estado":         "pendiente",
            "nodo_actual":    "aprobacion_gerencia",  # tras validacion_saldo automática
            "datos":          datos,                  # flexible: lo que defina el formulario
            "created_at": now, "updated_at": now
        })
    except Exception as e:
        raise HTTPException(500, f"MongoDB: {e}")

    # 1b. Tarea humana pendiente (entidad Task)
    task_id = None
    try:
        task_id = repo.crear_task(tenant_id, iid, "aprobacion_gerencia", role="gerencia")
    except Exception as e:
        warns.append(f"Task: {e}")

    # 2. Redis ────────────────────────────────────────────────
    try:
        repo.cache_set_estado(iid, "pendiente", "aprobacion_gerencia", now.isoformat(), ttl=86400)
    except Exception as e:
        warns.append(f"Redis: {e}")

    # 3. Cassandra ────────────────────────────────────────────
    try:
        repo.cass_event(tenant_id, iid, now,                        "start",            None,        "inicio_proceso",     None)
        repo.cass_event(tenant_id, iid, now + timedelta(seconds=1), "formulario",       empleado_id, "formulario_enviado",
                        json.dumps(datos))
        repo.cass_event(tenant_id, iid, now + timedelta(seconds=2), "validacion_saldo", "sistema",   "saldo_suficiente",
                        json.dumps({"dias_solicitados": datos.get("dias_solicitados")}))
        repo.cass_event(tenant_id, iid, now + timedelta(seconds=3), "aprobacion_gerencia", "sistema", "tarea_asignada",
                        json.dumps({"asignado_a_rol": "gerencia", "task_id": task_id}))
    except Exception as e:
        warns.append(f"Cassandra: {e}")

    # 4. Neo4j ────────────────────────────────────────────────
    try:
        repo.graph_crear_solicitud(iid, datos, now.isoformat(), empleado_id, tenant_id)
    except Exception as e:
        warns.append(f"Neo4j: {e}")

    return {"ok": True, "instance_id": iid, "task_id": task_id, "warnings": warns}


def core_avanzar(tenant_id: str, iid: str, actor_id: str, accion: str, comentario: str = "") -> dict:
    # Buscar la instancia (preferente por tenant, con fallback)
    doc = repo.find_instancia(tenant_id, iid)
    if not doc:
        raise HTTPException(404, "Instancia no encontrada")

    estado_actual = doc.get("estado")
    nodo_actual   = doc.get("nodo_actual", "aprobacion_gerencia")

    # Idempotencia / estado inválido (CAP: evita doble avance / doble completar tarea)
    if nodo_actual == "end" or estado_actual not in ("pendiente", "pendiente_gerencia"):
        raise HTTPException(409,
            f"La instancia ya fue avanzada (estado={estado_actual}, nodo={nodo_actual})")

    nodo_sig, nuevo_estado = sig_nodo(nodo_actual, accion)
    now   = datetime.utcnow()
    warns = []

    # El nodo de notificación es AUTOMÁTICO → la instancia encadena hasta 'end'
    notif_node = nodo_sig if nodo_sig in ("notif_aprobacion", "notif_rechazo") else None
    final_nodo = "end" if notif_node else nodo_sig

    # 1. MongoDB
    try:
        repo.update_instancia(iid, {"estado": nuevo_estado, "nodo_actual": final_nodo, "updated_at": now})
    except Exception as e:
        raise HTTPException(500, f"MongoDB: {e}")

    # 1b. Completar tarea humana si el nodo de origen era una tarea
    try:
        if nodo_actual in repo.task_nodes(tenant_id):
            repo.completar_task_doc(tenant_id, iid, nodo_actual, actor_id, accion)
    except Exception as e:
        warns.append(f"Task: {e}")

    # 2. Redis
    try:
        repo.cache_set_estado(iid, nuevo_estado, final_nodo, now.isoformat())
    except Exception as e:
        warns.append(f"Redis: {e}")

    # 3. Cassandra: decisión → notificación (automática) → fin
    try:
        repo.cass_event(tenant_id, iid, now, nodo_actual, actor_id, accion, comentario or "")
        if notif_node:
            dest = [doc.get("solicitante_id", "")]
            if notif_node == "notif_aprobacion":
                dest.append("emp_002")  # RRHH también recibe aprobación
            repo.cass_event(tenant_id, iid, now + timedelta(seconds=1), notif_node, "sistema",
                            "notificacion_enviada", json.dumps({"destinatarios": dest}))
            repo.cass_event(tenant_id, iid, now + timedelta(seconds=2), "end", None,
                            "proceso_finalizado", None)
    except Exception as e:
        warns.append(f"Cassandra: {e}")

    # 4. Neo4j
    try:
        repo.graph_decision(iid, actor_id, accion, now.isoformat(), comentario or "", nuevo_estado)
    except Exception as e:
        warns.append(f"Neo4j: {e}")

    return {"ok": True, "nodo_anterior": nodo_actual, "nodo_actual": final_nodo,
            "notif_node": notif_node, "estado": nuevo_estado, "warnings": warns}


def core_completar_tarea(tenant_id: str, task_id: str, actor_id: str, accion: str, comentario: str = "") -> dict:
    t = repo.find_task(tenant_id, task_id)
    if not t:
        raise HTTPException(404, "Tarea no encontrada")
    if t.get("status") == "completed":
        raise HTTPException(409, "La tarea ya fue completada")
    res = core_avanzar(tenant_id, t["instance_id"], actor_id, accion, comentario)
    res["task_id"] = task_id
    return res


def core_eventos(tenant_id: str, iid: str) -> list:
    return repo.cass_eventos(tenant_id, iid)


# ─── Publicación + validación de proceso (Neo4j) ─────────────
def _norm_nodos(nodos):
    out = []
    for n in nodos or []:
        nid = n.get("node_id") or n.get("id")
        if nid:
            out.append({"node_id": nid, "tipo": n.get("tipo", ""), "nombre": n.get("nombre", nid)})
    return out


def _norm_trans(trans):
    out = []
    for t in trans or []:
        d = t.get("desde") or t.get("from")
        h = t.get("hasta") or t.get("to")
        if d and h:
            out.append({"desde": d, "hasta": h, "condicion": t.get("condicion", "")})
    return out


def publicar_proceso(tenant_id: str, proceso_id: str, nodos, transiciones) -> dict:
    """Sincroniza la topología del proceso a Neo4j y valida los caminos.
    Devuelve {ok, errores[], sin_camino_a_fin[], inalcanzables[], loops[]}. Best-effort."""
    nn, tt = _norm_nodos(nodos), _norm_trans(transiciones)
    errores = []
    tipos = {n["tipo"] for n in nn}
    if "start" not in tipos:
        errores.append("Falta un nodo de tipo 'start'.")
    if "end" not in tipos:
        errores.append("Falta un nodo de tipo 'end'.")
    val = {"sin_camino_a_fin": [], "inalcanzables": [], "loops": []}
    try:
        repo.graph_sync_proceso(tenant_id, proceso_id, nn, tt)
        val = repo.graph_validar_proceso(tenant_id, proceso_id)
    except Exception as e:
        return {"ok": None, "errores": [f"Neo4j no disponible: {e}"], **val}
    if val["sin_camino_a_fin"]:
        errores.append("Pasos sin camino al fin: " + ", ".join(val["sin_camino_a_fin"]))
    if val["inalcanzables"]:
        errores.append("Pasos inalcanzables desde el inicio: " + ", ".join(val["inalcanzables"]))
    if val["loops"]:
        errores.append("Pasos en un ciclo infinito: " + ", ".join(val["loops"]))
    return {"ok": not errores, "errores": errores, **val}


# ═══════════════════════════════════════════════════════════════
#  Arranque — seed + migración tenant_id + tareas pendientes
# ═══════════════════════════════════════════════════════════════
def seed_and_migrate():
    try:
        if config.SEED_DEMO_INSTANCES and repo.count_instancias() == 0:
            base = {"proceso_id": "proc_vacaciones_v1", "tenant_id": config.DEFAULT_TENANT}
            repo.seed_instancias([
                {**base, "instance_id": "inst_vac_2026_001", "solicitante_id": "emp_001",
                 "estado": "aprobada", "nodo_actual": "end",
                 "datos": {"fecha_inicio": "2026-07-01", "fecha_fin": "2026-07-18",
                           "dias_solicitados": 15, "motivo": "Vacaciones anuales"},
                 "created_at": datetime(2026, 6, 10, 9, 0), "updated_at": datetime(2026, 6, 10, 11, 1)},
                {**base, "instance_id": "inst_vac_2026_002", "solicitante_id": "emp_004",
                 "estado": "rechazada", "nodo_actual": "end",
                 "datos": {"fecha_inicio": "2026-07-15", "fecha_fin": "2026-07-29",
                           "dias_solicitados": 12, "motivo": "Vacaciones"},
                 "created_at": datetime(2026, 6, 11, 10, 0), "updated_at": datetime(2026, 6, 11, 10, 3)},
                {**base, "instance_id": "inst_vac_2026_003", "solicitante_id": "emp_005",
                 "estado": "pendiente", "nodo_actual": "aprobacion_gerencia",
                 "datos": {"fecha_inicio": "2026-08-01", "fecha_fin": "2026-08-07",
                           "dias_solicitados": 5, "motivo": "Vacaciones de invierno"},
                 "created_at": datetime(2026, 6, 12, 8, 0), "updated_at": datetime(2026, 6, 12, 8, 3)},
            ])
        # Migración: backfill tenant_id en datos preexistentes
        repo.backfill_tenant_instancias()
        repo.backfill_tenant_procesos()
        # Entidad Tenant: seed de empresas demo si la colección está vacía
        if repo.count_tenants() == 0:
            repo.seed_tenants([
                {"tenant_id": "empresa_01", "name": "Grupo 7 S.A.",   "status": "active", "plan": "demo", "created_at": datetime.utcnow()},
                {"tenant_id": "empresa_02", "name": "Acme Logística",  "status": "active", "plan": "demo", "created_at": datetime.utcnow()},
                {"tenant_id": "empresa_03", "name": "Delta Salud",     "status": "active", "plan": "demo", "created_at": datetime.utcnow()},
            ])
        # Cada empresa tiene aprovisionado el proceso estándar "Solicitud de Vacaciones"
        for t in repo.distinct_tenants():
            repo.provision_process(t)
        # Form data-driven: asegurar campos tipados en el nodo formulario de cada proceso
        repo.ensure_form_fields()
        # Reflejar la topología de cada proceso como grafo en Neo4j (para validación)
        for p in repo.all_procesos():
            try:
                publicar_proceso(p.get("tenant_id", config.DEFAULT_TENANT),
                                 p.get("proceso_id"), p.get("nodos"), p.get("transiciones"))
            except Exception:
                pass
        # Crear tareas pendientes para instancias detenidas en un nodo task
        tnodes = repo.task_nodes(config.DEFAULT_TENANT)
        for d in repo.instancias_pendientes():
            if d.get("nodo_actual") in tnodes:
                repo.crear_task(d.get("tenant_id", config.DEFAULT_TENANT), d["instance_id"], d["nodo_actual"])
    except Exception:
        pass  # Si no conecta al inicio, no hay problema
