// ============================================================
// FlowOps - Solicitud de Vacaciones
// load_data.cypher — Carga inicial de nodos y relaciones
// ============================================================

// --- Roles ---
MERGE (:Rol {nombre: 'empleado'});
MERGE (:Rol {nombre: 'rrhh'});
MERGE (:Rol {nombre: 'gerencia'});

// --- Empleados ---
MERGE (e1:Empleado {empleado_id: 'emp_001'})
SET e1.nombre = 'Juan Pérez', e1.departamento = 'Tecnología', e1.saldo_dias = 15;

MERGE (e2:Empleado {empleado_id: 'emp_002'})
SET e2.nombre = 'María González', e2.departamento = 'Recursos Humanos', e2.saldo_dias = 20;

MERGE (e3:Empleado {empleado_id: 'emp_003'})
SET e3.nombre = 'Carlos López', e3.departamento = 'Dirección', e3.saldo_dias = 25;

MERGE (e4:Empleado {empleado_id: 'emp_004'})
SET e4.nombre = 'Ana Martínez', e4.departamento = 'Tecnología', e4.saldo_dias = 10;

MERGE (e5:Empleado {empleado_id: 'emp_005'})
SET e5.nombre = 'Luis Rodríguez', e5.departamento = 'Marketing', e5.saldo_dias = 18;

// --- Asignar roles ---
MATCH (e:Empleado {empleado_id: 'emp_001'}), (r:Rol {nombre: 'empleado'})
MERGE (e)-[:TIENE_ROL]->(r);

MATCH (e:Empleado {empleado_id: 'emp_002'}), (r:Rol {nombre: 'rrhh'})
MERGE (e)-[:TIENE_ROL]->(r);

MATCH (e:Empleado {empleado_id: 'emp_003'}), (r:Rol {nombre: 'gerencia'})
MERGE (e)-[:TIENE_ROL]->(r);

MATCH (e:Empleado {empleado_id: 'emp_004'}), (r:Rol {nombre: 'empleado'})
MERGE (e)-[:TIENE_ROL]->(r);

MATCH (e:Empleado {empleado_id: 'emp_005'}), (r:Rol {nombre: 'empleado'})
MERGE (e)-[:TIENE_ROL]->(r);

// --- Jerarquía de reporte ---
MATCH (e1:Empleado {empleado_id: 'emp_001'}), (e2:Empleado {empleado_id: 'emp_002'})
MERGE (e1)-[:REPORTA_A {desde: '2024-01-01'}]->(e2);

MATCH (e4:Empleado {empleado_id: 'emp_004'}), (e2:Empleado {empleado_id: 'emp_002'})
MERGE (e4)-[:REPORTA_A {desde: '2024-01-01'}]->(e2);

MATCH (e2:Empleado {empleado_id: 'emp_002'}), (e3:Empleado {empleado_id: 'emp_003'})
MERGE (e2)-[:REPORTA_A {desde: '2023-06-01'}]->(e3);

// --- Nodos del proceso ---
MERGE (:NodoProceso {node_id: 'start',               tipo: 'start',    nombre: 'Inicio'});
MERGE (:NodoProceso {node_id: 'formulario_solicitud', tipo: 'form',     nombre: 'Formulario de Solicitud'});
MERGE (:NodoProceso {node_id: 'revision_rrhh',        tipo: 'task',     nombre: 'Revisión RRHH'});
MERGE (:NodoProceso {node_id: 'decision_dias',        tipo: 'decision', nombre: '¿Más de 10 días?'});
MERGE (:NodoProceso {node_id: 'aprobacion_gerencia',  tipo: 'task',     nombre: 'Aprobación Gerencia'});
MERGE (:NodoProceso {node_id: 'notif_aprobacion',     tipo: 'notification', nombre: 'Notificación Aprobación'});
MERGE (:NodoProceso {node_id: 'notif_rechazo',        tipo: 'notification', nombre: 'Notificación Rechazo'});
MERGE (:NodoProceso {node_id: 'end',                  tipo: 'end',      nombre: 'Fin'});

// --- Transiciones entre nodos ---
MATCH (a:NodoProceso {node_id: 'start'}), (b:NodoProceso {node_id: 'formulario_solicitud'})
MERGE (a)-[:SIGUIENTE {condicion: 'always'}]->(b);

MATCH (a:NodoProceso {node_id: 'formulario_solicitud'}), (b:NodoProceso {node_id: 'revision_rrhh'})
MERGE (a)-[:SIGUIENTE {condicion: 'always'}]->(b);

MATCH (a:NodoProceso {node_id: 'revision_rrhh'}), (b:NodoProceso {node_id: 'decision_dias'})
MERGE (a)-[:SIGUIENTE {condicion: 'approved'}]->(b);

MATCH (a:NodoProceso {node_id: 'revision_rrhh'}), (b:NodoProceso {node_id: 'notif_rechazo'})
MERGE (a)-[:SIGUIENTE {condicion: 'rejected'}]->(b);

MATCH (a:NodoProceso {node_id: 'decision_dias'}), (b:NodoProceso {node_id: 'aprobacion_gerencia'})
MERGE (a)-[:SIGUIENTE {condicion: 'dias > 10'}]->(b);

MATCH (a:NodoProceso {node_id: 'decision_dias'}), (b:NodoProceso {node_id: 'notif_aprobacion'})
MERGE (a)-[:SIGUIENTE {condicion: 'dias <= 10'}]->(b);

MATCH (a:NodoProceso {node_id: 'aprobacion_gerencia'}), (b:NodoProceso {node_id: 'notif_aprobacion'})
MERGE (a)-[:SIGUIENTE {condicion: 'approved'}]->(b);

MATCH (a:NodoProceso {node_id: 'aprobacion_gerencia'}), (b:NodoProceso {node_id: 'notif_rechazo'})
MERGE (a)-[:SIGUIENTE {condicion: 'rejected'}]->(b);

MATCH (a:NodoProceso {node_id: 'notif_aprobacion'}), (b:NodoProceso {node_id: 'end'})
MERGE (a)-[:SIGUIENTE {condicion: 'always'}]->(b);

MATCH (a:NodoProceso {node_id: 'notif_rechazo'}), (b:NodoProceso {node_id: 'end'})
MERGE (a)-[:SIGUIENTE {condicion: 'always'}]->(b);

// --- Solicitudes de ejemplo ---
MERGE (s1:Solicitud {instance_id: 'inst_vac_2026_001'})
SET s1.estado = 'aprobada', s1.dias_solicitados = 15,
    s1.fecha_inicio = '2026-07-01', s1.fecha_fin = '2026-07-18',
    s1.motivo = 'Vacaciones de verano', s1.created_at = '2026-06-10T09:00:00Z';

MERGE (s2:Solicitud {instance_id: 'inst_vac_2026_002'})
SET s2.estado = 'rechazada', s2.dias_solicitados = 8,
    s2.fecha_inicio = '2026-07-15', s2.fecha_fin = '2026-07-24',
    s2.motivo = 'Descanso', s2.created_at = '2026-06-11T10:00:00Z';

MERGE (s3:Solicitud {instance_id: 'inst_vac_2026_003'})
SET s3.estado = 'pendiente', s3.dias_solicitados = 5,
    s3.fecha_inicio = '2026-08-01', s3.fecha_fin = '2026-08-07',
    s3.motivo = 'Viaje familiar', s3.created_at = '2026-06-12T08:00:00Z';

// --- Relaciones de solicitudes ---
MATCH (e:Empleado {empleado_id: 'emp_001'}), (s:Solicitud {instance_id: 'inst_vac_2026_001'})
MERGE (e)-[:SOLICITA {timestamp: '2026-06-10T09:00:00Z'}]->(s);

MATCH (e:Empleado {empleado_id: 'emp_002'}), (s:Solicitud {instance_id: 'inst_vac_2026_001'})
MERGE (e)-[:APRUEBA {timestamp: '2026-06-10T10:30:00Z', comentario: 'Documentación validada'}]->(s);

MATCH (e:Empleado {empleado_id: 'emp_003'}), (s:Solicitud {instance_id: 'inst_vac_2026_001'})
MERGE (e)-[:APRUEBA {timestamp: '2026-06-10T11:00:00Z', comentario: 'Aprobado por gerencia'}]->(s);

MATCH (e:Empleado {empleado_id: 'emp_004'}), (s:Solicitud {instance_id: 'inst_vac_2026_002'})
MERGE (e)-[:SOLICITA {timestamp: '2026-06-11T10:00:00Z'}]->(s);

MATCH (e:Empleado {empleado_id: 'emp_002'}), (s:Solicitud {instance_id: 'inst_vac_2026_002'})
MERGE (e)-[:RECHAZA {timestamp: '2026-06-11T14:00:00Z', comentario: 'Saldo insuficiente'}]->(s);

MATCH (e:Empleado {empleado_id: 'emp_005'}), (s:Solicitud {instance_id: 'inst_vac_2026_003'})
MERGE (e)-[:SOLICITA {timestamp: '2026-06-12T08:00:00Z'}]->(s);
