# FlowOps TPO

## Integrantes
- RODRIGUEZ BELEN MERCEDES
- MEZHER FRANCO ADRIAN
- ROMERO GOMEZ MARIA SOL
- GUGLIELMONE LUCAS

---

## Proceso elegido

**Solicitud de Vacaciones**

---

## Descripción del problema

Estandarizar y automatizar el pedido de días libres de los empleados, asegurando que se validen los días disponibles, se obtenga la autorización del líder directo y se notifique a Recursos Humanos de forma ordenada.

El proceso resuelve los siguientes problemas concretos:
- Falta de control sobre el saldo de días disponibles al momento de la solicitud
- Ausencia de un canal formal y trazable para la aprobación del líder directo
- Notificaciones inconsistentes o manuales hacia Recursos Humanos
- Sin registro de auditoría sobre quién aprobó, cuándo y con qué justificación

---

## Primer flujo BPM

```
[Empleado] → Carga fechas (formulario)
                  ↓
         ¿Tiene días disponibles?
           /              \
          No              Sí
          ↓               ↓
   Notificación     [Líder] Revisión manual
   rechazo →            /         \
   Fin           Aprueba         Rechaza
                    ↓               ↓
           Notificación       Notificación
           RRHH + Empleado    solo Empleado
                    ↓               ↓
                   Fin             Fin
```

**Roles participantes:** Solicitante, Aprobador (líder directo), Recursos Humanos

**Datos capturados:** ID del empleado, fecha inicio, fecha fin, cantidad de días solicitados, comentarios opcionales

**Registro de auditoría:** fecha/hora exacta de la solicitud, quién aprobó o rechazó, comentarios del líder, fechas solicitadas

---

## Modelos NoSQL candidatos

### Documental
Utilizado para almacenar las definiciones de procesos: nodos, roles, transiciones y versiones del flujo. El modelo JSON flexible permite evolucionar el esquema del proceso sin migraciones.

### Columnar/Tabular 
Utilizado para almacenar el historial de eventos y auditoría. 

### Relacional 
Considerado para el estado de instancias por su garantía ACID.

---

## Arquitectura conceptual inicial

```
Frontend / Cliente de prueba
          |
          v
    API de FlowOps
          |
    +-----+------+----------+
    |            |          |
    v            v          v
 MongoDB     PostgreSQL  Cassandra
(definiciones) (instancias) (eventos/auditoría)
```

Esta arquitectura aplica el patrón **Polyglot Persistence**: cada motor resuelve el patrón de acceso específico de su capa, en lugar de forzar una única tecnología para los tres casos de uso.

---

## Decisiones pendientes

| Decisión pendiente |
| Confirmar MongoDB para base documental o si hay una opcion mejor para este tipo de informacion a almacenar. 
| Confirmar Cassandra para eventos | Todavía no se estudió Cassandra en profundidad en la cursada |
| Evaluar si el modelo relacional planteado puede reemplazarse por una NoSQL para instancias | No se vio consistencia eventual ni transacciones en NoSQL |
| Definir cómo identificar y estructurar los eventos de auditoría | Depende del modelo final de Cassandra y de lo que se vea este tipo de datos |
| Definir consistencia y particionamiento para la auditoria | Se profundizará en sistemas distribuidos |
| Implementar conexión desde la API a cada base | 
| Definir estrategia de multi-tenant (separación por tenant_id) 
| Definir métricas o benchmarking entre motores | Se verá al final de la cursada |

---

## Instrucciones iniciales de ejecución

### Requisitos previos
- Docker Desktop instalado (https://www.docker.com/products/docker-desktop)
- Docker Compose (incluido en Docker Desktop)

### Levantar el ambiente
```bash
# Clonar o descomprimir el proyecto
cd flowops-tpo

# Levantar todos los servicios
docker-compose up -d

# Verificar que los contenedores están corriendo
docker-compose ps
```

### Verificar conexiones

// aun no se eligieron las tecnologias a utilizar 

### Detener el ambiente
```bash
docker-compose down
```