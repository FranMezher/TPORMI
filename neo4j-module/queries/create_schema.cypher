// ============================================================
// FlowOps - Solicitud de Vacaciones
// create_schema.cypher — Constraints e índices
// ============================================================

// Constraints de unicidad
CREATE CONSTRAINT empleado_id_unique IF NOT EXISTS
FOR (e:Empleado) REQUIRE e.empleado_id IS UNIQUE;

CREATE CONSTRAINT solicitud_id_unique IF NOT EXISTS
FOR (s:Solicitud) REQUIRE s.instance_id IS UNIQUE;

CREATE CONSTRAINT nodo_id_unique IF NOT EXISTS
FOR (n:NodoProceso) REQUIRE n.node_id IS UNIQUE;

CREATE CONSTRAINT rol_nombre_unique IF NOT EXISTS
FOR (r:Rol) REQUIRE r.nombre IS UNIQUE;

// Índices para búsquedas frecuentes
CREATE INDEX empleado_nombre IF NOT EXISTS FOR (e:Empleado) ON (e.nombre);
CREATE INDEX solicitud_estado IF NOT EXISTS FOR (s:Solicitud) ON (s.estado);
CREATE INDEX solicitud_fecha IF NOT EXISTS FOR (s:Solicitud) ON (s.fecha_inicio);
