"""
Paquete FlowOps — arquitectura por capas (Clase 12: Acceso a BD desde aplicaciones).

    config        → Capa de configuración (parámetros de conexión y constantes)
    database      → Capa de conexión        (factories lazy a los 5 motores NoSQL)
    repositories  → Capa de acceso a datos   (DAO: una sección por motor)
    schemas       → Modelos de datos         (Pydantic / contratos de la API)
    services      → Capa de lógica de negocio (orquesta los motores: core_*)
    routers/      → Capa de presentación      (endpoints HTTP/JSON de FastAPI)

main.py ensambla la app, incluye los routers y corre el seed de arranque.
"""
