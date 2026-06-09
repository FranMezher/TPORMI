# Neo4j Module — FlowOps Solicitud de Vacaciones

Módulo de base de datos de grafos para analizar el flujo de aprobación y la red de empleados en el proceso de Solicitud de Vacaciones de FlowOps.

## Modelo de grafos

### Nodos (3 tipos)

| Label | Descripción | Propiedades clave |
|---|---|---|
| `Empleado` | Persona que solicita o aprueba vacaciones | empleado_id, nombre, departamento, saldo_dias |
| `Solicitud` | Instancia de una solicitud de vacaciones | instance_id, estado, dias_solicitados, fecha_inicio, fecha_fin |
| `NodoProceso` | Paso del flujo BPM (form, task, decision, etc.) | node_id, tipo, nombre |

### Relaciones (5 tipos)

| Relación | Descripción |
|---|---|
| `(Empleado)-[:SOLICITA]->(Solicitud)` | El empleado inicia la solicitud |
| `(Empleado)-[:APRUEBA]->(Solicitud)` | RRHH o Gerencia aprueba |
| `(Empleado)-[:RECHAZA]->(Solicitud)` | RRHH o Gerencia rechaza |
| `(Empleado)-[:REPORTA_A]->(Empleado)` | Jerarquía organizacional |
| `(NodoProceso)-[:SIGUIENTE]->(NodoProceso)` | Transición entre pasos del proceso |

## Levantar Neo4j

```bash
# Desde la raíz del proyecto
docker compose up -d grafo

# Verificar que está corriendo
docker compose ps grafo

# Abrir Neo4j Browser
# http://localhost:7474
# Usuario: neo4j | Contraseña: flowops123
```

## Cargar datos

Desde Neo4j Browser (`http://localhost:7474`) ejecutar en orden:

```
1. queries/create_schema.cypher   — constraints e índices
2. queries/load_data.cypher       — nodos y relaciones
3. queries/advanced_queries.cypher — consultas de análisis
4. queries/graph_algorithms.cypher — PageRank y Shortest Path
```

O desde la terminal:

```bash
docker exec -i flowops-grafo cypher-shell -u neo4j -p flowops123 < queries/create_schema.cypher
docker exec -i flowops-grafo cypher-shell -u neo4j -p flowops123 < queries/load_data.cypher
```

## Consultas destacadas

**Cadena de aprobación de una solicitud:**
```cypher
MATCH (s:Solicitud {instance_id: 'inst_vac_2026_001'})<-[:APRUEBA]-(a:Empleado)
MATCH (a)-[:REPORTA_A]->(sup:Empleado)
RETURN s.instance_id, a.nombre AS aprobador, sup.nombre AS reporta_a;
```

**Caminos posibles del proceso (inicio a fin):**
```cypher
MATCH p = (i:NodoProceso {node_id: 'start'})-[:SIGUIENTE*]->(f:NodoProceso {node_id: 'end'})
RETURN [n IN nodes(p) | n.nombre] AS pasos, length(p) AS saltos
ORDER BY saltos;
```

## Algoritmos aplicados

- **PageRank** — identifica qué empleados son más críticos en la red de aprobaciones
- **Shortest Path (Dijkstra)** — calcula la cadena jerárquica más corta entre un empleado y gerencia

## Justificación del uso de Neo4j

MongoDB almacena los nodos y edges del proceso como documentos, pero no puede ejecutar traversal de grafos eficientemente. Neo4j permite:

- Detectar cuellos de botella en el flujo (qué nodo acumula más instancias detenidas)
- Calcular la cadena de aprobación real para cada empleado según jerarquía
- Detectar conflictos de cobertura (dos empleados del mismo equipo con vacaciones superpuestas)
- Analizar qué aprobadores son críticos usando PageRank
