/* ============================================================================
   Fase 2 — Columnas de InventarioEquipos que hacen falta para los KPI
   ----------------------------------------------------------------------------
   Fecha:   2026-08-19
   Aplicar: después de 2026-08-19_reportes_nucleo.sql
   Motor:   SQL Server 2022

   Qué hace
     Agrega columnas a dbo.InventarioEquipos. TODAS son NULLABLE y ninguna
     tiene default con valor de negocio: el inventario existente (531 filas)
     no se toca y sigue funcionando igual.

   Por qué
     valor_adquisicion es la que bloquea el análisis de costo. Sin ella no se
     puede calcular el ratio costo-acumulado-de-reparación contra valor del
     equipo, que es el criterio estándar para dictaminar una baja. Hoy ni
     siquiera existe la columna, y fecha_adquisicion está en NULL en 530 de
     531 registros.

     Los KPI que dependen de ella se degradan con elegancia: muestran "sin
     dato" en vez de romperse, y se van poblando conforme se capture.

   registro_sanitario lo pide NOM-240-SSA1-2012 para notificar un incidente
   adverso a COFEPRIS. Sin él, el reporte de tecnovigilancia queda incompleto
   justo en el campo que la autoridad revisa.

   Es idempotente: se puede volver a correr sin romper nada.
   ============================================================================ */

USE HospitalGalenia;
GO

SET NOCOUNT ON;
GO

/* ── Costo ──────────────────────────────────────────────────────────────── */

IF COL_LENGTH('dbo.InventarioEquipos', 'valor_adquisicion') IS NULL
BEGIN
    ALTER TABLE dbo.InventarioEquipos ADD valor_adquisicion DECIMAL(14,2) NULL;
    PRINT 'InventarioEquipos.valor_adquisicion agregada.';
END
ELSE PRINT 'InventarioEquipos.valor_adquisicion ya existe.';
GO

IF COL_LENGTH('dbo.InventarioEquipos', 'moneda') IS NULL
BEGIN
    ALTER TABLE dbo.InventarioEquipos ADD moneda CHAR(3) NULL
        CONSTRAINT DF_InventarioEquipos_moneda DEFAULT ('MXN');
    PRINT 'InventarioEquipos.moneda agregada.';
END
ELSE PRINT 'InventarioEquipos.moneda ya existe.';
GO


/* ── Clasificación ──────────────────────────────────────────────────────────
   criticidad es lo que permite priorizar: un programa de mantenimiento que
   trata igual a un ventilador y a una báscula no es un programa, es una lista.
   ---------------------------------------------------------------------------- */

IF COL_LENGTH('dbo.InventarioEquipos', 'criticidad') IS NULL
BEGIN
    ALTER TABLE dbo.InventarioEquipos ADD criticidad VARCHAR(10) NULL;
    PRINT 'InventarioEquipos.criticidad agregada.';
END
ELSE PRINT 'InventarioEquipos.criticidad ya existe.';
GO

/* El CHECK va en su propio lote a propósito. SQL Server compila el lote
   completo antes de ejecutarlo, y la expresión de un CHECK se compila: si
   estuviera junto al ADD COLUMN de arriba, fallaría con "Invalid column name
   'criticidad'" porque al compilar la columna todavía no existe.
   Las FOREIGN KEY de más abajo no tienen ese problema: referencian la columna
   por metadatos, sin expresión que compilar. */
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints
               WHERE name = 'CK_InventarioEquipos_criticidad')
BEGIN
    ALTER TABLE dbo.InventarioEquipos WITH CHECK
        ADD CONSTRAINT CK_InventarioEquipos_criticidad
        CHECK (criticidad IS NULL OR criticidad IN ('alta', 'media', 'baja'));
    PRINT 'CK_InventarioEquipos_criticidad creado.';
END
ELSE PRINT 'CK_InventarioEquipos_criticidad ya existe.';
GO

IF COL_LENGTH('dbo.InventarioEquipos', 'registro_sanitario') IS NULL
BEGIN
    ALTER TABLE dbo.InventarioEquipos ADD registro_sanitario VARCHAR(50) NULL;
    PRINT 'InventarioEquipos.registro_sanitario agregada.';
END
ELSE PRINT 'InventarioEquipos.registro_sanitario ya existe.';
GO

IF COL_LENGTH('dbo.InventarioEquipos', 'vida_util_anios') IS NULL
BEGIN
    ALTER TABLE dbo.InventarioEquipos ADD vida_util_anios INT NULL;
    PRINT 'InventarioEquipos.vida_util_anios agregada.';
END
ELSE PRINT 'InventarioEquipos.vida_util_anios ya existe.';
GO


/* ── Área normalizada ───────────────────────────────────────────────────────
   Convive con la columna `area` de texto, que NO se toca: todo el sistema
   actual (filtros del inventario, panel NFC, dashboard de mantenimientos) la
   lee, y romperla para ganar una FK no vale la pena.

   area_id se llena desde el texto y se usa para agrupar en las estadísticas.
   La columna de texto sigue siendo la que se edita; esta se sincroniza.
   ---------------------------------------------------------------------------- */

IF COL_LENGTH('dbo.InventarioEquipos', 'area_id') IS NULL
BEGIN
    ALTER TABLE dbo.InventarioEquipos ADD area_id INT NULL;
    ALTER TABLE dbo.InventarioEquipos WITH CHECK
        ADD CONSTRAINT FK_InventarioEquipos_Area
        FOREIGN KEY (area_id) REFERENCES dbo.Cat_Areas (id);
    PRINT 'InventarioEquipos.area_id agregada.';
END
ELSE PRINT 'InventarioEquipos.area_id ya existe.';
GO

/* Sincroniza contra el catálogo sembrado por el script del núcleo. */
UPDATE e
   SET e.area_id = c.id
  FROM dbo.InventarioEquipos e
  JOIN dbo.Cat_Areas c ON c.nombre = LTRIM(RTRIM(e.area))
 WHERE e.area_id IS NULL;
PRINT CONCAT('Equipos vinculados a Cat_Areas: ', @@ROWCOUNT);
GO


/* ── Baja ───────────────────────────────────────────────────────────────────
   Un equipo dado de baja no se borra: se marca. Borrarlo dejaría huérfano
   todo su historial de mantenimientos, que es justo lo que justifica la baja.
   ---------------------------------------------------------------------------- */

IF COL_LENGTH('dbo.InventarioEquipos', 'fecha_baja') IS NULL
BEGIN
    ALTER TABLE dbo.InventarioEquipos ADD fecha_baja DATE NULL;
    PRINT 'InventarioEquipos.fecha_baja agregada.';
END
ELSE PRINT 'InventarioEquipos.fecha_baja ya existe.';
GO

IF COL_LENGTH('dbo.InventarioEquipos', 'reporte_baja_id') IS NULL
BEGIN
    ALTER TABLE dbo.InventarioEquipos ADD reporte_baja_id INT NULL;
    ALTER TABLE dbo.InventarioEquipos WITH CHECK
        ADD CONSTRAINT FK_InventarioEquipos_RepBaja
        FOREIGN KEY (reporte_baja_id) REFERENCES dbo.Reportes (id);
    PRINT 'InventarioEquipos.reporte_baja_id agregada.';
END
ELSE PRINT 'InventarioEquipos.reporte_baja_id ya existe.';
GO


/* ============================================================================
   Comprobación tras aplicar
   ============================================================================ */

PRINT '';
PRINT '--- Columnas nuevas ---';
SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH,
       NUMERIC_PRECISION, NUMERIC_SCALE, IS_NULLABLE
  FROM INFORMATION_SCHEMA.COLUMNS
 WHERE TABLE_NAME = 'InventarioEquipos'
   AND COLUMN_NAME IN ('valor_adquisicion', 'moneda', 'criticidad',
                       'registro_sanitario', 'vida_util_anios', 'area_id',
                       'fecha_baja', 'reporte_baja_id')
 ORDER BY COLUMN_NAME;

PRINT '--- Cobertura del vinculo con Cat_Areas ---';
SELECT COUNT(*) AS total,
       SUM(CASE WHEN area_id IS NOT NULL THEN 1 ELSE 0 END) AS con_area_id,
       SUM(CASE WHEN area_id IS NULL     THEN 1 ELSE 0 END) AS sin_area_id
  FROM dbo.InventarioEquipos;
GO
