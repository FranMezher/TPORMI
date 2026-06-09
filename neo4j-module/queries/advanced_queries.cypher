// ============================================================
// FlowOps - Solicitud de Vacaciones
// advanced_queries.cypher — Consultas de 2+ saltos
// ============================================================

// --- Q1: Ver todas las solicitudes de un empleado con quién las aprobó/rechazó ---
// 2 saltos: Empleado → Solicitud → (Aprobador)
MATCH (e:Empleado {empleado_id: 'emp_001'})-[:SOLICITA]->(s:Solicitud)
OPTIONAL MATCH (aprobador:Empleado)-[:APRUEBA]->(s)
OPTIONAL MATCH (rechazador:Empleado)-[:RECHAZA]->(s)
RETURN e.nombre AS solicitante,
       s.instance_id AS solicitud,
       s.estado AS estado,
       s.dias_solicitados AS dias,
       aprobador.nombre AS aprobado_por,
       rechazador.nombre AS rechazado_por;

// --- Q2: Cadena de aprobación de una solicitud (quién aprobó y a quién reporta) ---
// 3 saltos: Solicitud ← Aprobador → REPORTA_A → Superior
MATCH (s:Solicitud {instance_id: 'inst_vac_2026_001'})<-[:APRUEBA]-(aprobador:Empleado)
MATCH (aprobador)-[:REPORTA_A]->(superior:Empleado)
RETURN s.instance_id AS solicitud,
       aprobador.nombre AS aprobador,
       aprobador.departamento AS dept_aprobador,
       superior.nombre AS reporta_a;

// --- Q3: Camino completo de una solicitud a través del proceso ---
// Traversal de la cadena de nodos del proceso
MATCH camino = (inicio:NodoProceso {node_id: 'start'})-[:SIGUIENTE*]->(fin:NodoProceso {node_id: 'end'})
RETURN [n IN nodes(camino) | n.nombre] AS pasos,
       length(camino) AS cantidad_pasos
ORDER BY cantidad_pasos;

// --- Q4: Empleados que solicitaron vacaciones en fechas superpuestas ---
// Detectar conflictos de cobertura en el mismo período
MATCH (e1:Empleado)-[:SOLICITA]->(s1:Solicitud),
      (e2:Empleado)-[:SOLICITA]->(s2:Solicitud)
WHERE e1.empleado_id <> e2.empleado_id
  AND s1.fecha_inicio <= s2.fecha_fin
  AND s1.fecha_fin >= s2.fecha_inicio
  AND s1.estado IN ['pendiente', 'aprobada']
  AND s2.estado IN ['pendiente', 'aprobada']
RETURN e1.nombre AS empleado1,
       s1.fecha_inicio + ' - ' + s1.fecha_fin AS periodo1,
       e2.nombre AS empleado2,
       s2.fecha_inicio + ' - ' + s2.fecha_fin AS periodo2;

// --- Q5: Empleados que nunca tuvieron una solicitud aprobada ---
MATCH (e:Empleado)-[:TIENE_ROL]->(:Rol {nombre: 'empleado'})
WHERE NOT (e)-[:SOLICITA]->(:Solicitud {estado: 'aprobada'})
RETURN e.nombre AS empleado, e.departamento;

// --- Q6: Árbol jerárquico completo de aprobación (quién puede aprobar a quién) ---
// 2+ saltos: Empleado → REPORTA_A* → Gerencia
MATCH cadena = (e:Empleado)-[:REPORTA_A*1..3]->(jefe:Empleado)
WHERE NOT (jefe)-[:REPORTA_A]->()
RETURN e.nombre AS empleado,
       [n IN nodes(cadena) | n.nombre] AS cadena_aprobacion;

// --- Q7: Cuello de botella — nodo donde más solicitudes quedan detenidas ---
MATCH (s:Solicitud {estado: 'pendiente'})
MATCH (s)<-[:SOLICITA]-(:Empleado)
// Simulación: el nodo activo sería el de revision_rrhh para solicitudes pendientes
MATCH (n:NodoProceso {node_id: 'revision_rrhh'})
RETURN n.nombre AS nodo_cuello_botella,
       count(s) AS solicitudes_detenidas;
