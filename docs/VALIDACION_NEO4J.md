# Validación de procesos desde Neo4j

FlowOps refleja cada definición de proceso como un grafo `(:Step)-[:NEXT]->(:Step)`
aislado por `tenant_id` + `proceso_id`. Sobre ese grafo se valida que el workflow
sea **correcto** *antes* de que un empleado quede atrapado en un paso sin salida.

- Se sincroniza automáticamente al **arrancar la API** y al **Guardar** un proceso
  desde el editor (`POST /api/{tenant}/processes` → respuesta trae `validacion`).
- El seed `load_all.py` ya crea el grafo del proceso de vacaciones, así que las
  queries de abajo funcionan en el **Neo4j Browser** (http://localhost:7474)
  apenas cargás los datos.

## Modelo

| Elemento | Cómo se representa |
|----------|--------------------|
| Paso del proceso | nodo `:Step {tenant_id, proceso_id, node_id, tipo, nombre}` |
| Transición | relación `-[:NEXT {condicion}]->` |
| Tipos de `tipo` | `start`, `form`, `decision`, `task`, `notification`, `end` |

---

## 1. Ver el grafo del proceso

```cypher
MATCH p = (:Step {proceso_id:'proc_vacaciones_v1'})-[:NEXT*]->(:Step)
RETURN p;
```

## 2. ¿Todos los caminos llegan al fin?  (pasos SIN salida)

Devuelve los pasos que **no tienen ningún camino hacia un nodo `end`**. Si devuelve
filas, hay un error de diseño (un empleado podría quedar atrapado ahí).

```cypher
MATCH (st:Step {tenant_id:'empresa_01', proceso_id:'proc_vacaciones_v1'})
WHERE st.tipo <> 'end'
  AND NOT EXISTS {
    MATCH (st)-[:NEXT*1..]->(e:Step {tenant_id:'empresa_01', proceso_id:'proc_vacaciones_v1'})
    WHERE e.tipo = 'end'
  }
RETURN st.node_id AS paso_sin_salida;
```
> En el proceso de vacaciones **no devuelve nada** → todos los caminos terminan en `end`. ✅

## 3. ¿Hay pasos inalcanzables desde el inicio?

Pasos a los que **nunca se llega** partiendo de `start` (código muerto en el flujo).

```cypher
MATCH (ini:Step {tenant_id:'empresa_01', proceso_id:'proc_vacaciones_v1'})
WHERE ini.tipo = 'start'
MATCH (st:Step {tenant_id:'empresa_01', proceso_id:'proc_vacaciones_v1'})
WHERE st.tipo <> 'start' AND NOT EXISTS { MATCH (ini)-[:NEXT*1..]->(st) }
RETURN st.node_id AS paso_inalcanzable;
```

## 4. ¿Hay loops infinitos?

Pasos que pueden volver a sí mismos siguiendo `NEXT` (ciclo sin fin).

```cypher
MATCH (st:Step {tenant_id:'empresa_01', proceso_id:'proc_vacaciones_v1'})
WHERE EXISTS { MATCH (st)-[:NEXT*1..]->(st) }
RETURN DISTINCT st.node_id AS paso_en_loop;
```

## 5. Listar todos los caminos completos START → END

```cypher
MATCH path = (ini:Step {proceso_id:'proc_vacaciones_v1', tipo:'start'})
             -[:NEXT*]->(fin:Step {proceso_id:'proc_vacaciones_v1', tipo:'end'})
RETURN [n IN nodes(path) | n.node_id] AS camino,
       [r IN relationships(path) | r.condicion] AS condiciones;
```
> Devuelve los 2 caminos del proceso: aprobado (`start→formulario→validacion_saldo→aprobacion_gerencia→notif_aprobacion→end`) y rechazado por saldo (`…→validacion_saldo→notif_rechazo→end`).

---

## Probar que detecta un proceso ROTO

1. En el front: **➕ Nuevo proceso** → borrá la transición que llega a `end` (o
   agregá un nodo `task` suelto sin conectar) → **💾 Guardar**.
2. El toast del front avisa: *"Guardado, pero Neo4j detectó: Pasos sin camino al fin: …"*.
3. En el Browser, la query del punto **2** ahora **sí devuelve** ese nodo.

Equivalente por API:
```bash
curl -X POST http://localhost:8000/api/test_zzz/processes -H "Content-Type: application/json" -d '{
  "proceso_id":"proc_roto","nombre":"Roto",
  "nodos":[{"node_id":"start","tipo":"start"},{"node_id":"tarea","tipo":"task"},
           {"node_id":"huerfano","tipo":"task"},{"node_id":"end","tipo":"end"}],
  "transiciones":[{"desde":"start","hasta":"tarea","condicion":"always"},
                  {"desde":"tarea","hasta":"huerfano","condicion":"always"}]}'
# → "validacion": { "ok": false,
#      "errores": ["Pasos sin camino al fin: start, tarea, huerfano",
#                  "Pasos inalcanzables desde el inicio: end"], ... }
```

---

## Para el oral

> *"El proceso no solo se guarda como documento en Mongo: se refleja como grafo en
> Neo4j y, con una consulta de **reachability** (`NOT EXISTS { (paso)-[:NEXT*]->(:end) }`),
> verificamos que **todo paso lleve a un fin**, que **no haya pasos inalcanzables** y
> que **no haya loops**. Es validación de la lógica de negocio que un modelo
> documental no podría hacer: en el grafo, recorrer caminos es la operación nativa."*
