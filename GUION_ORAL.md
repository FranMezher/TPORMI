# 🎤 Guion oral — FlowOps (TPO Ingeniería de Datos II)

> Palabras clave en **negrita**. La idea es que con ver el keyword puedas desarrollar la idea vos.

---

## 1. Pitch de apertura (30 seg)
- **FlowOps** = motor de **workflows** (procesos BPM) tipo **n8n**.
- Caso modelado: **Solicitud de Vacaciones**.
- Lo interesante NO es el caso, es la **arquitectura de datos**: **persistencia políglota** → 5 motores NoSQL, cada uno por su fortaleza.
- Stack: **FastAPI** (Python) + **Docker Compose** (un contenedor por motor).

---

## 2. El workflow (mostrar el canvas)
- 7 **nodos**: `start → formulario → validacion_saldo → aprobacion_gerencia → notif_aprobacion / notif_rechazo → end`.
- Tipos de nodo: **trigger**, **form**, **decision** (automático), **task** (humano), **notification**, **end**.
- **validacion_saldo** = decisión **automática**: `días_solicitados ≤ saldo_dias`.
- **aprobacion_gerencia** = **tarea humana** (rol **gerencia**, **SLA** 48h).
- **Bifurcaciones**: saldo insuficiente → rechazo automático; gerencia aprueba/rechaza.
- Keyword fuerte: **máquina de estados** / **transiciones condicionadas**.

---

## 3. Por qué cada motor (EL núcleo del TPO)
| Motor | Keyword | Justificación en una frase |
|-------|---------|----------------------------|
| 🍃 **MongoDB — procesos** | **documento / esquema flexible** | La definición del workflow es un JSON anidado (nodos + transiciones); encaja natural en un documento. |
| 🍃 **MongoDB — instancias** | **estado por ejecución** | Cada solicitud es un documento con su estado y datos. |
| ⚡ **Redis** | **clave-valor / baja latencia / caché** | Estado actual y **saldo de días** para lectura inmediata; usa **TTL** (expire). |
| 💎 **Cassandra** | **columnar / write-heavy / inmutable** | **Log de auditoría** (event sourcing). **Partition key** = `(tenant_id, instance_id)`, **clustering** por timestamp → consultas por instancia sin `ALLOW FILTERING`. |
| 🕸️ **Neo4j** | **grafo / relaciones** | Empleados, **jerarquía** (REPORTA_A), **roles**, y relaciones SOLICITA/APRUEBA/NOTIFICADO. Consultas de relación que en SQL serían **JOINs** caros. |

- Frase de cierre: **"el motor correcto para cada forma de acceso a los datos"**.

---

## 4. Multi-tenancy
- **tenant_id** (`empresa_01`) → el sistema es **multi-empresa**.
- En Cassandra el tenant es parte de la **partition key** → aislamiento físico de datos.

---

## 5. Demo en vivo (orden sugerido)
1. **Canvas Workflow** → señalar nodo iluminado con badge → **"hay una instancia esperando aprobación"**.
2. Botón **▶ Ejecutar workflow** → crear solicitud → se ve el **punto animado recorriendo el flujo** → **"esto escribió en los 4 motores a la vez"** (keyword: **escritura transaccional distribuida** / **dual write**).
3. La instancia queda en **aprobacion_gerencia** → **clic en el nodo** → Aprobar (actor `emp_003`) → se anima hasta **end**.
4. **Auditoría** → pegar el `instance_id` → **timeline de Cassandra** (quién, qué, cuándo).
5. **Grafo Neo4j** → relaciones empleado→solicitud.
6. **Dashboard** → 5 motores **conectados** (health check `/api/status`).

---

## 6. Posibles preguntas del profe (y keyword para responder)
- *"¿Por qué no todo en una sola base?"* → **persistencia políglota**, **acoplamiento**, **escalabilidad independiente**.
- *"¿Qué pasa si falla un motor al escribir?"* → la API devuelve **warnings** (escritura **best-effort**); mencionar que lo ideal sería un **outbox pattern** / **saga** para **consistencia eventual**.
- *"¿Consistencia?"* → **consistencia eventual** entre motores; Redis es **caché** (puede quedar atrás de Mongo).
- *"¿Por qué Cassandra y no Mongo para auditoría?"* → **write-heavy**, **append-only**, **escala horizontal**, modelo **time-series** por partición.
- *"¿Cómo evitás `ALLOW FILTERING`?"* → diseñé la **PK por (tenant_id, instance_id)** y consulto siempre por esa clave.
- *"¿Escalabilidad?"* → cada motor escala **horizontalmente** por separado; el estado caliente está en **Redis**.

---

## 6.bis Features que cierran el spec (mencionalas si preguntan por la API)
- **Multi-tenant real**: `tenant_id` en todos los documentos + rutas `/api/{tenant_id}/...`.
- **Crear proceso por API**: `POST /api/{tenant}/processes` (no solo por script) → mostralo en **Swagger `/docs`**.
- **Entidad Task explícita**: cada tarea humana es un documento (`task_id`, `assigned_role`, `status`) → `POST /api/{tenant}/tasks/{id}/complete`.
- **Idempotencia / estado inválido**: completar una tarea dos veces o avanzar una instancia finalizada → **HTTP 409**. (Responde la pregunta CAP de "completar tarea dos veces".)
- **Compatibilidad**: las rutas viejas siguen funcionando para el frontend (delegan en la misma lógica core).
- Documentos del entregable en **`docs/`**: Plan de Sistemas, Modelo de Datos, Arquitectura.
- **Formulario data-driven (¡demo fuerte!)**: los campos del form salen de la definición del proceso (`nodos[formulario].campos`) y la instancia guarda `datos` flexible. Si el profe pide **agregar un campo en vivo**, lo agregás a la definición y aparece en el formulario **sin tocar código** ni migrar. Es la prueba directa de "procesos configurables como datos" (spec) y del esquema flexible NoSQL (Act 1-B).
  - Comando para agregar el campo en vivo (Mongo):
    ```
    db.procesos.updateOne(
      { tenant_id:"empresa_01", proceso_id:"proc_vacaciones_v1" },
      { $push: { "nodos.$[n].campos": { name:"destino", label:"Destino", type:"text", required:false } } },
      { arrayFilters: [ { "n.node_id":"formulario" } ] })
    ```
    Luego **refrescás** la página → el campo aparece en "Nueva Solicitud" y en "▶ Ejecutar". Al crear la instancia, el valor queda en `instancias.datos` y en la auditoría de Cassandra.

## 6.ter Editor de workflow (demo n8n completa)
- El canvas tiene **modo edición** (botón ✏️ Editar): arrastrás nodos, **agregás** nodos desde la paleta, **conectás** arrastrando desde el punto morado derecho, editás nombre/tipo/condición en el inspector, **borrás** nodos/transiciones, y **💾 Guardás** → `POST /api/{tenant}/processes`.
- Las **posiciones** se guardan en la definición (cada nodo tiene `x,y`), así que el layout que armás queda persistido en MongoDB.
- Mensaje para el oral: *"el proceso es dato; lo construyo visualmente y lo guardo sin tocar código — igual que n8n"*. Responde la sugerencia del profe de hacer el workflow editable.

## 6.qua Alineación con las clases 12 y 13
- **Clase 12 (Acceso a BD desde apps)**: API unificada (FastAPI = gateway que orquesta los 5 motores), drivers oficiales, cache-aside (Redis), event log (Cassandra), escritura best-effort con degradación. El editor de procesos + selector + "Nuevo proceso" demuestran "procesos como datos configurables".
  - **Arquitectura por capas** (lo que pidió el profe): el backend está separado en `flowops/` → `config` (parámetros) → `database` (conexiones lazy) → `repositories` (DAO, uno por motor) → `services` (lógica `core_*`) → `routers` (endpoints). `main.py` solo ensambla. Frase: *"el router no toca la base: llama al servicio, el servicio orquesta repositorios, y cada DAO habla con un solo motor — dependencia en una sola dirección"*. Mostrar el árbol de `flowops/` y `docs/ARQUITECTURA.md` (sección "Arquitectura por capas").
- **Clase 13 (Evaluación de la conectividad a los distintos productos)**: el **Dashboard mide la latencia (ms) de cada motor** en `/api/status` (verde <15ms, amarillo <60ms, rojo). Es literalmente la evaluación de conectividad de la clase. Frase: *"acá ves la latencia de conexión a cada producto, que es la métrica central de la clase de evaluación de conectividad"*.

## 7. Glosario express (por si te traban)
- **BPM** = Business Process Management.
- **Event sourcing** = guardar cada evento, no solo el estado final.
- **Partition key / clustering key** = cómo Cassandra distribuye y ordena.
- **Dual write** = escribir el mismo hecho en varias bases.
- **Consistencia eventual** = todas las réplicas convergen, pero no al instante.
- **TTL** = time-to-live, expiración automática (Redis).
- **Health check** = endpoint que verifica que cada servicio responde.
