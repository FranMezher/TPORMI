# 🎬 Storytelling — Defensa del TPO FlowOps

> Narrativa completa para la presentación oral. Está escrita en **primera
> persona** para que la puedas contar como una historia, no como una lista de
> features. Cada bloque indica **[qué mostrar]** en el front y la **idea fuerza**.
> Duración objetivo: 8–10 minutos.

---

## Acto 0 — El gancho (30 seg)

> *"Imaginen una empresa donde pedir vacaciones es un infierno de mails: el
> empleado escribe, RRHH reenvía, el gerente aprueba en otro hilo, y nadie sabe
> en qué estado quedó la solicitud. Nosotros construimos **FlowOps**: una
> plataforma que convierte ese caos en un **proceso visual, ejecutable y
> auditable** — como n8n, pero pensada desde los datos."*

**Idea fuerza:** no vendemos un formulario de vacaciones; vendemos un **motor de
procesos** y, sobre todo, una **arquitectura de datos**.

**[Mostrar]** Pestaña **Workflow**: el canvas con el flujo dibujado.

---

## Acto 1 — El problema real: un proceso no es una tabla (1 min)

> *"Cuando arrancamos, la pregunta no era '¿qué base uso?', sino '¿cuántas formas
> distintas de datos tiene un proceso?'. Y descubrimos que son muchas, y muy
> diferentes entre sí:"*

- La **definición** del proceso es un árbol (nodos y transiciones) → un **documento**.
- El **estado actual** de cada solicitud se consulta todo el tiempo → necesita ser **rapidísimo**.
- La **historia** de lo que pasó no se borra nunca → es un **registro inmutable** que solo crece.
- Las **relaciones** entre empleados, roles y jerarquía → son un **grafo**.

> *"Meter todo esto en una sola base relacional habría sido forzar la realidad.
> Por eso elegimos **persistencia políglota**: una base distinta para cada forma
> de acceder a los datos."*

**Idea fuerza:** la decisión técnica central — *el motor correcto para cada
patrón de acceso* — nace de un problema real, no de querer usar tecnologías de moda.

---

## Acto 2 — La arquitectura (1–2 min)

> *"Así quedó el sistema. Una API en FastAPI es el único punto de entrada —
> nadie toca las bases directamente — y detrás orquesta cinco motores NoSQL."*

**[Mostrar]** Pestaña **Dashboard**: los 5 motores conectados, cada uno con su
**latencia** (el semáforo verde/amarillo/rojo).

| Motor | Por qué está | En una frase |
|-------|--------------|--------------|
| 🍃 **MongoDB** | documento | La definición del proceso y cada instancia son JSON anidados. Es la **fuente de verdad**. |
| ⚡ **Redis** | clave-valor | El estado caliente, leído en milisegundos, con TTL. |
| 💎 **Cassandra** | columnar | El **log de auditoría**: append-only, escala en escritura, particionado por instancia. |
| 🕸️ **Neo4j** | grafo | Empleados, roles y relaciones SOLICITA/APRUEBA: traversal en vez de JOINs. |
| 🔍 **Elasticsearch** | índice | Búsqueda full-text (diseñado; lo dejamos como evolución, somos honestos con el alcance). |

> *"Y algo que el profe nos pidió y nos gustó: el backend no es un script gigante.
> Lo separamos en **capas** — configuración, conexión, acceso a datos (un DAO por
> motor), lógica de negocio y rutas. El router nunca toca la base: llama al
> servicio, el servicio orquesta los repositorios. Cambiar de motor se toca en
> una sola capa."*

**Idea fuerza:** arquitectura políglota **+** código por capas = separación de
responsabilidades de punta a punta.

---

## Acto 3 — La demo: el proceso cobra vida (2–4 min)

> *"Pero esto no es un diagrama. Vamos a ejecutarlo en vivo."*

**[Mostrar]** Canvas → **▶ Ejecutar workflow** → completar el formulario → enviar.

> *"Fíjense que el formulario no está hardcodeado: sale de la **definición del
> proceso**. Si el profe me pide ahora agregar un campo, lo agrego a la
> definición y aparece solo, sin tocar código. Y `días solicitados` es un
> **campo calculado**: lo derivo de las fechas contando días hábiles, no confío
> en lo que mande el cliente."*

> *"Cuando aprieto enviar, en una sola operación escribo en **cuatro motores a la
> vez**: el documento en Mongo, el estado en Redis, los eventos en Cassandra y la
> solicitud en el grafo de Neo4j. Vean el punto animado recorriendo el flujo."*

**Idea fuerza:** *escritura distribuida* + *formulario data-driven* (el proceso
es **dato configurable**, no código).

---

## Acto 4 — La decisión humana (1 min)

> *"La solicitud quedó frenada en `aprobación gerencia`, esperando a una persona.
> Eso es una **tarea humana**: una entidad propia, con su rol asignado y su
> estado."*

**[Mostrar]** Clic en el nodo `aprobacion_gerencia` → **Aprobar** como `emp_003`.

> *"Aprueba el gerente y la instancia avanza sola hasta el final, notificando al
> empleado y a RRHH."*

**[Mostrar, remate de idempotencia]** Volvé a apretar **Aprobar** sobre la misma
instancia.

> *"Y si intento aprobar dos veces, el sistema responde **HTTP 409**: una tarea se
> completa una sola vez. Esto es nuestra respuesta al teorema **CAP** —
> priorizamos consistencia en la operación crítica."*

**Idea fuerza:** máquina de estados + **idempotencia** como decisión de diseño.

---

## Acto 5 — La prueba de que todo pasó (1–2 min)

> *"¿Cómo sé que todo esto realmente ocurrió? Acá entra cada motor a mostrar lo suyo."*

**[Mostrar]** Pestaña **Ejecuciones** → *"el estado actual lo leo de **Redis**, la caché."*

**[Mostrar]** Pestaña **Auditoría** → elegir la instancia → *"este es el **event
log de Cassandra**: quién, qué y cuándo, evento por evento, inmutable. Esto es
**event sourcing**."*

**[Mostrar]** Pestaña **Grafo Neo4j** (modal) → *"y acá las **relaciones**:
el empleado que solicita, el gerente que aprueba. Preguntas que en SQL serían
JOINs carísimos, acá son un traversal."*

**Idea fuerza:** cada tecnología **justifica su existencia** con una evidencia
visible en pantalla.

---

## Acto 6 — Honestidad técnica: límites y fallas (1 min)

> *"No todo es perfecto, y eso también lo pensamos:"*

- *"La consistencia entre motores es **eventual**: Redis puede quedar un instante atrás de Mongo. Lo asumimos: Redis es caché, no la verdad."*
- *"Si un motor secundario falla al escribir, la operación **no se cae**: sigue y devuelve **warnings** (best-effort). La mejora natural sería un patrón **outbox/saga**."*
- *"Si falla algo crítico — el proceso no existe, el tenant es inválido — respondemos con códigos claros: 404, 409."*
- *"Y medimos la **conectividad**: la latencia de cada motor está en el Dashboard. Es la evaluación de conectividad que vimos en clase."*

**Idea fuerza:** conocemos los **límites** de nuestra solución → madurez técnica.

---

## Acto 7 — El cierre (30 seg)

> *"FlowOps demuestra una idea: **no hay una base para todo, hay una base para
> cada cosa**. Modelamos un proceso real con la herramienta correcta en cada
> punto — documento, caché, log, grafo — detrás de una API por capas, multi-empresa
> y auditable. Si tuviéramos que resumirlo en una prueba: **completar una tarea
> toca Mongo y Cassandra, deja evidencia en la auditoría y se protege con
> idempotencia.** Eso es la arquitectura políglota funcionando."*

**[Mostrar]** Volver al **Dashboard** con los 5 motores en verde.

---

## 🎯 Tu kit anti-pánico (preguntas difíciles)

| Si te preguntan… | Respondé con… |
|------------------|---------------|
| *"¿Por qué no una sola base?"* | Persistencia políglota: cada motor por su patrón de acceso; escalan por separado. |
| *"¿Qué pasa si falla un motor al escribir?"* | Best-effort + warnings; Mongo es la verdad; mejora = outbox/saga. |
| *"¿Consistencia?"* | Eventual entre motores; Redis es caché, puede quedar atrás. |
| *"¿Por qué Cassandra y no Mongo para auditoría?"* | Write-heavy, append-only, particionado por `(tenant_id, instance_id)`, escala horizontal. |
| *"¿Cómo evitás `ALLOW FILTERING`?"* | Diseñé la PK por `(tenant_id, instance_id)` y siempre consulto por esa clave. |
| *"¿Multi-tenancy?"* | `tenant_id` en todos los motores + entidad Tenant; en Cassandra es parte de la partition key. |
| *"¿Por qué FastAPI por capas?"* | El router no toca la base; servicio orquesta repositorios; un DAO por motor. Cambiar de motor = una sola capa. |

---

## ⏱ Mapa de tiempos (referencia rápida)

```
0:00  Gancho + canvas
0:30  El problema: un proceso tiene muchas formas de datos
1:30  Arquitectura: Dashboard, 5 motores, capas
3:00  Demo: ▶ Ejecutar (escritura en 4 motores) + form data-driven
5:00  Tarea humana: aprobar + idempotencia (409)
6:00  Evidencia: Redis + Auditoría (Cassandra) + Grafo (Neo4j)
8:00  Límites: consistencia eventual, best-effort, latencia
9:00  Cierre: "una base para cada cosa"
```
