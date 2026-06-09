// ============================================================
// FlowOps - Solicitud de Vacaciones
// graph_algorithms.cypher — Algoritmos de grafos con GDS
// ============================================================

// PREREQUISITO: cargar el grafo en memoria antes de ejecutar algoritmos
// ============================================================

// --- Paso 1: Proyectar el grafo de empleados en memoria ---
CALL gds.graph.project(
  'flowops-empleados',
  ['Empleado'],
  {
    REPORTA_A: { orientation: 'UNDIRECTED' },
    APRUEBA:   { orientation: 'UNDIRECTED' },
    RECHAZA:   { orientation: 'UNDIRECTED' }
  }
);

// --- Paso 2: Proyectar el grafo de proceso en memoria ---
CALL gds.graph.project(
  'flowops-proceso',
  ['NodoProceso'],
  {
    SIGUIENTE: {
      orientation: 'NATURAL',
      properties: []
    }
  }
);

// ============================================================
// ALGORITMO 1 — PageRank sobre empleados
// Identifica qué empleados son más críticos en la red de aprobaciones
// ============================================================
CALL gds.pageRank.stream('flowops-empleados')
YIELD nodeId, score
RETURN gds.util.asNode(nodeId).nombre AS empleado,
       gds.util.asNode(nodeId).departamento AS departamento,
       round(score * 100) / 100 AS influencia
ORDER BY influencia DESC;

// Interpretación:
// Un score alto indica que el empleado participa en muchas aprobaciones
// o que empleados influyentes dependen de él. Útil para detectar
// quién es el cuello de botella real en la cadena de aprobación.

// ============================================================
// ALGORITMO 2 — Shortest Path (camino más corto de aprobación)
// Encuentra la ruta más corta desde un empleado hasta gerencia
// ============================================================
MATCH (inicio:Empleado {empleado_id: 'emp_001'}),
      (fin:Empleado {empleado_id: 'emp_003'})
CALL gds.shortestPath.dijkstra.stream('flowops-empleados', {
  sourceNode: id(inicio),
  targetNode: id(fin)
})
YIELD index, sourceNode, targetNode, totalCost, nodeIds, path
RETURN gds.util.asNode(sourceNode).nombre AS origen,
       gds.util.asNode(targetNode).nombre AS destino,
       totalCost AS distancia,
       [nodeId IN nodeIds | gds.util.asNode(nodeId).nombre] AS ruta;

// Interpretación:
// Muestra cuántos saltos jerárquicos necesita una solicitud para
// llegar a aprobación final. Una distancia de 2 significa:
// empleado → rrhh → gerencia (flujo normal del proceso).

// ============================================================
// LIMPIEZA — Eliminar grafos de memoria al terminar
// ============================================================
// CALL gds.graph.drop('flowops-empleados');
// CALL gds.graph.drop('flowops-proceso');
