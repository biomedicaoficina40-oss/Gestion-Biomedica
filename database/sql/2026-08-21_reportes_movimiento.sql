/* ============================================================================
   Fase 2.3 — Entrada y salida de equipo: soporte para varios equipos por reporte
   ----------------------------------------------------------------------------
   Fecha:   2026-08-21
   Aplicar: después de 2026-08-19_reportes_nucleo.sql y ..._detalle_tipos.sql
   Motor:   SQL Server 2022

   Qué hace
     1. Crea dbo.ReporteEquipos: un movimiento (entrada o salida) casi siempre
        es de un solo equipo, pero a veces es en masa — un lote completo que
        sale a mantenimiento externo, por ejemplo. Reportes.equipo_id sigue
        apuntando al PRIMERO de la lista (compatibilidad con todo el código
        que ya asume un equipo por reporte: listado, ficha, dashboard); esta
        tabla es la lista completa.
     2. Amplía el CHECK de ReporteAdjuntos.clase con 'foto_estado': la foto
        única de entrada/salida (documenta cómo entra o cómo sale el equipo),
        distinta de las tres etapas del mantenimiento.

   Por qué NO es una columna de más en Reportes
     Una columna "equipo_id_2, equipo_id_3..." no escala y un CSV en un
     VARCHAR no se puede indexar ni unir. Una tabla aparte permite además
     saber cuántos hay (`COUNT(*)`) sin tocar el resto del sistema.

   Es idempotente: se puede volver a correr sin romper nada.
   ============================================================================ */

USE HospitalGalenia;
GO

/* ----------------------------------------------------------------------------
   1. dbo.ReporteEquipos
   ---------------------------------------------------------------------------- */
IF OBJECT_ID('dbo.ReporteEquipos', 'U') IS NOT NULL
    PRINT 'La tabla dbo.ReporteEquipos ya existe. No se hace nada.';
ELSE
BEGIN
    CREATE TABLE dbo.ReporteEquipos (
        id          INT IDENTITY(1,1) NOT NULL,
        reporte_id  INT               NOT NULL,
        equipo_id   INT               NOT NULL,
        orden       INT               NOT NULL
            CONSTRAINT DF_ReporteEquipos_orden DEFAULT (0),

        CONSTRAINT PK_ReporteEquipos PRIMARY KEY CLUSTERED (id),
        CONSTRAINT UQ_ReporteEquipos_reporte_equipo UNIQUE (reporte_id, equipo_id),
        CONSTRAINT FK_ReporteEquipos_Rep FOREIGN KEY (reporte_id)
            REFERENCES dbo.Reportes (id),
        CONSTRAINT FK_ReporteEquipos_Eq FOREIGN KEY (equipo_id)
            REFERENCES dbo.InventarioEquipos (id)
    );

    CREATE NONCLUSTERED INDEX IX_ReporteEquipos_reporte
        ON dbo.ReporteEquipos (reporte_id, orden);

    -- Para "en qué movimientos aparece este equipo" (útil para el enganche
    -- futuro con BLE: si un equipo está en una salida sin retorno, no está
    -- "perdido", está documentado).
    CREATE NONCLUSTERED INDEX IX_ReporteEquipos_equipo
        ON dbo.ReporteEquipos (equipo_id);

    PRINT 'Tabla dbo.ReporteEquipos creada.';
END
GO

/* ----------------------------------------------------------------------------
   2. ReporteAdjuntos.clase admite 'foto_estado'
   ---------------------------------------------------------------------------- */
IF EXISTS (SELECT 1 FROM sys.check_constraints cc
           JOIN sys.columns col ON col.object_id = cc.parent_object_id
           WHERE cc.name = 'CK_ReporteAdjuntos_clase'
             AND cc.definition NOT LIKE '%foto_estado%')
BEGIN
    ALTER TABLE dbo.ReporteAdjuntos DROP CONSTRAINT CK_ReporteAdjuntos_clase;
    PRINT 'CK_ReporteAdjuntos_clase (viejo) eliminado.';
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_ReporteAdjuntos_clase')
BEGIN
    ALTER TABLE dbo.ReporteAdjuntos WITH CHECK ADD CONSTRAINT CK_ReporteAdjuntos_clase
        CHECK (clase IN ('foto_antes', 'foto_durante', 'foto_despues', 'foto_estado',
                         'documento', 'requisicion'));
    PRINT 'CK_ReporteAdjuntos_clase ampliado con foto_estado.';
END
GO

/* ----------------------------------------------------------------------------
   Verificación
   ---------------------------------------------------------------------------- */
SELECT 'ReporteEquipos' AS tabla, COUNT(*) AS filas FROM dbo.ReporteEquipos;
SELECT cc.name, cc.definition
  FROM sys.check_constraints cc
 WHERE cc.name = 'CK_ReporteAdjuntos_clase';
GO
