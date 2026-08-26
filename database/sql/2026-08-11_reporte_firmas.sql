/* ============================================================================
   ReporteFirmas — firmas de los reportes (alta, y los que vengan después)
   ----------------------------------------------------------------------------
   Fecha:   2026-08-11
   Aplicar: una sola vez por base de datos (pruebas y producción por separado).
   Motor:   SQL Server

   Por qué tabla y no dentro de Reportes.datos_json:
     - datos_json es el snapshot inmutable del equipo el día del alta. La firma
       se agrega DESPUÉS, así que guardarla ahí obligaría a reescribir el
       snapshot, que es justo lo que se quiso evitar.
     - Son hasta dos filas por reporte, con ciclo de vida propio.
     - UQ_ReporteFirmas_rol vuelve "una vez firmado ya no se cambia" una
       garantía del motor, no un if de la aplicación.

   El estado pendiente/firmado NO se guarda: se deriva de qué filas existen,
   para no tener dos fuentes de verdad que se puedan desincronizar.
   ============================================================================ */

USE HospitalGalenia;
GO

IF OBJECT_ID('dbo.ReporteFirmas', 'U') IS NOT NULL
BEGIN
    PRINT 'La tabla dbo.ReporteFirmas ya existe. No se hace nada.';
END
ELSE
BEGIN
    CREATE TABLE dbo.ReporteFirmas (
        id         INT IDENTITY(1,1) NOT NULL,
        reporte_id INT               NOT NULL,
        rol        VARCHAR(10)       NOT NULL,   -- 'entrega' | 'recibe'
        nombre     VARCHAR(150)      NOT NULL,
        cargo      VARCHAR(150)      NULL,
        imagen     VARCHAR(255)      NOT NULL,   -- firmas/xxxxx.png (bajo static/uploads)
        usuario_id INT               NULL,       -- usuario del sistema que capturó la firma
        fecha      DATETIME          NOT NULL
            CONSTRAINT DF_ReporteFirmas_fecha DEFAULT (GETDATE()),

        CONSTRAINT PK_ReporteFirmas     PRIMARY KEY CLUSTERED (id),
        CONSTRAINT UQ_ReporteFirmas_rol UNIQUE (reporte_id, rol),
        CONSTRAINT CK_ReporteFirmas_rol CHECK (rol IN ('entrega', 'recibe')),
        CONSTRAINT FK_ReporteFirmas_Rep FOREIGN KEY (reporte_id)
            REFERENCES dbo.Reportes (id)
    );

    /* Se consulta siempre por reporte para saber qué falta firmar. */
    CREATE NONCLUSTERED INDEX IX_ReporteFirmas_reporte
        ON dbo.ReporteFirmas (reporte_id);

    PRINT 'Tabla dbo.ReporteFirmas creada.';
END
GO

/* Comprobación rápida tras aplicar */
SELECT
    c.COLUMN_NAME, c.DATA_TYPE, c.CHARACTER_MAXIMUM_LENGTH, c.IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS c
WHERE c.TABLE_NAME = 'ReporteFirmas'
ORDER BY c.ORDINAL_POSITION;
GO
