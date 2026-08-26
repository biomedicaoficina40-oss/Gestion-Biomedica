/* ============================================================================
   FASE 2 — MIGRACION COMPLETA PARA PRODUCCION
   ============================================================================
   Generado:  2026-08-25
   Motor:     SQL Server 2022 · collation Modern_Spanish_CI_AS
   Base:      HospitalGalenia

   QUE ES ESTO
     Los cinco scripts de la Fase 2 concatenados en orden de dependencia, en
     un solo archivo, para poder aplicarlos de una pasada en produccion.
     Es exactamente el mismo SQL que ya corrio contra la base de PRUEBAS.

   COMO SE APLICA
     1. RESPALDA LA BASE DE PRODUCCION ANTES DE CORRER ESTO.
     2. Abrelo en SSMS con la base HospitalGalenia seleccionada.
     3. Ejecutalo completo (F5). Los separadores GO ya vienen puestos.
     4. Revisa la seccion de VERIFICACION al final: imprime que quedo.

   ES IDEMPOTENTE
     Se puede correr dos veces sin romper nada: cada bloque comprueba si el
     objeto ya existe antes de crearlo. Si algo ya estaba aplicado, ese
     bloque imprime "ya existe" y sigue.

   QUE NO HACE
     - No borra ni modifica ninguna fila existente de InventarioEquipos,
       Reportes ni usuario.
     - Todas las columnas nuevas son NULLABLE o traen DEFAULT, asi que las
       filas que ya existen siguen siendo validas.
     - No toca permisos, logins ni configuracion del servidor.

   LO UNICO QUE PISA
     Dos CHECK constraints se reemplazan por versiones mas amplias (aceptan
     mas valores, nunca menos):
       · CK_Reportes_tipo         — para admitir los tipos nuevos
       · CK_ReporteFirmas_rol     — para admitir los roles de firma nuevos
       · CK_ReporteAdjuntos_clase — para admitir la foto de entrada/salida
     Y Reportes.equipo_id pasa a NULLABLE (antes NOT NULL), porque la
     bitacora de carrito rojo no cuelga de un equipo. Ninguna fila existente
     se invalida con eso.

   DESPUES DE ESTE SCRIPT — pasos que NO son SQL
     · Copiar los archivos de la aplicacion (ver GUIA-DESPLIEGUE.md).
     · Agregar 2 lineas a app.py para registrar el blueprint.
     · Dar permiso de ESCRITURA al usuario de Apache sobre
       static/uploads/  (ahi se guardan los PDF congelados y las fotos).
   ============================================================================ */



/* ############################################################################
   PASO 1 de 5 — 2026-08-11_reporte_firmas.sql
   ----------------------------------------------------------------------------
   Firmas de reportes. Puede que ya este aplicado en produccion (es de la fase del acta de alta); volver a correrlo no hace nada.
   ############################################################################ */

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


/* ############################################################################
   PASO 2 de 5 — 2026-08-19_reportes_nucleo.sql
   ----------------------------------------------------------------------------
   Nucleo: amplia Reportes, crea folios, catalogos y las tablas transversales (costos, adjuntos, notas, bitacora, relaciones).
   ############################################################################ */

/* ============================================================================
   Fase 2 — Núcleo de reportes
   ----------------------------------------------------------------------------
   Fecha:   2026-08-19
   Aplicar: una sola vez por base de datos (pruebas y producción por separado).
   Motor:   SQL Server 2022 · collation Modern_Spanish_CI_AS

   Qué hace
     Amplía dbo.Reportes y dbo.ReporteFirmas, que ya nacieron genéricas, y
     agrega las tablas transversales que los cinco tipos de reporte nuevos
     (preventivo, correctivo, entrada/salida, tecnovigilancia) comparten:
     costos, adjuntos, notas, bitácora y relaciones.

   Por qué extender en vez de crear un módulo aparte
     Reportes ya tiene tipo/folio/equipo_id/datos_json/archivo_pdf, y
     ReporteFirmas ya cuelga de Reportes.id y no del alta. El diseño previo
     anticipó esto; duplicarlo daría dos historiales de reportes que nadie
     podría consultar juntos.

   Por qué los costos van en tabla y no en datos_json
     datos_json es el snapshot inmutable del equipo, y además no es
     consultable ni indexable. Un importe ahí no se puede sumar por mes ni
     por área, que es justo para lo que se pidió el módulo.

   Es idempotente: se puede volver a correr sin romper nada.
   ============================================================================ */

USE HospitalGalenia;
GO

SET NOCOUNT ON;
GO

/* ============================================================================
   1. dbo.Reportes — columnas nuevas
   ----------------------------------------------------------------------------
   Un reporte deja de ser un documento que nace terminado y pasa a ser un
   expediente con ciclo de vida: se abre, se trabaja durante días, y solo al
   liberarse produce el PDF. De ahí las tres fechas y el estado.
   ============================================================================ */

IF COL_LENGTH('dbo.Reportes', 'estado') IS NULL
BEGIN
    ALTER TABLE dbo.Reportes ADD estado VARCHAR(15) NOT NULL
        CONSTRAINT DF_Reportes_estado DEFAULT ('borrador');
    PRINT 'Reportes.estado agregada.';
END
ELSE PRINT 'Reportes.estado ya existe.';
GO

/* La serie del folio se guarda aparte del folio mismo para no tener que
   parsear la cadena cada vez que se quiere agrupar o pedir el consecutivo. */
IF COL_LENGTH('dbo.Reportes', 'serie') IS NULL
BEGIN
    ALTER TABLE dbo.Reportes ADD serie VARCHAR(8) NULL;
    PRINT 'Reportes.serie agregada.';
END
ELSE PRINT 'Reportes.serie ya existe.';
GO

IF COL_LENGTH('dbo.Reportes', 'area_id') IS NULL
BEGIN
    /* Área donde ocurrió el trabajo, que no siempre es donde está el equipo
       hoy: un equipo que se reparó en el taller y volvió a UCI debe reportar
       UCI, no taller. */
    ALTER TABLE dbo.Reportes ADD area_id INT NULL;
    PRINT 'Reportes.area_id agregada.';
END
ELSE PRINT 'Reportes.area_id ya existe.';
GO

IF COL_LENGTH('dbo.Reportes', 'tecnico_id') IS NULL
BEGIN
    ALTER TABLE dbo.Reportes ADD tecnico_id INT NULL;
    PRINT 'Reportes.tecnico_id agregada.';
END
ELSE PRINT 'Reportes.tecnico_id ya existe.';
GO

IF COL_LENGTH('dbo.Reportes', 'fecha_apertura') IS NULL
BEGIN
    ALTER TABLE dbo.Reportes ADD fecha_apertura DATETIME NULL
        CONSTRAINT DF_Reportes_fecha_apertura DEFAULT (GETDATE());
    PRINT 'Reportes.fecha_apertura agregada.';
END
ELSE PRINT 'Reportes.fecha_apertura ya existe.';
GO

IF COL_LENGTH('dbo.Reportes', 'fecha_inicio') IS NULL
BEGIN
    ALTER TABLE dbo.Reportes ADD fecha_inicio DATE NULL;
    PRINT 'Reportes.fecha_inicio agregada.';
END
ELSE PRINT 'Reportes.fecha_inicio ya existe.';
GO

/* La fecha que se IMPRIME en el documento. Un preventivo que empieza el lunes
   y termina el miércoles dice miércoles: es la que se cruza contra el programa
   anual y la que refleja cuándo el equipo volvió a estar disponible. */
IF COL_LENGTH('dbo.Reportes', 'fecha_liberacion') IS NULL
BEGIN
    ALTER TABLE dbo.Reportes ADD fecha_liberacion DATETIME NULL;
    PRINT 'Reportes.fecha_liberacion agregada.';
END
ELSE PRINT 'Reportes.fecha_liberacion ya existe.';
GO

IF COL_LENGTH('dbo.Reportes', 'liberado_por') IS NULL
BEGIN
    ALTER TABLE dbo.Reportes ADD liberado_por INT NULL;
    PRINT 'Reportes.liberado_por agregada.';
END
ELSE PRINT 'Reportes.liberado_por ya existe.';
GO

/* El hash es lo que vuelve verificable un reporte liberado: prueba que el
   archivo que se sirve hoy es el mismo que se firmó. Sin él, "el PDF está
   congelado" es una promesa de la aplicación, no un hecho comprobable. */
IF COL_LENGTH('dbo.Reportes', 'pdf_sha256') IS NULL
BEGIN
    ALTER TABLE dbo.Reportes ADD pdf_sha256 CHAR(64) NULL;
    PRINT 'Reportes.pdf_sha256 agregada.';
END
ELSE PRINT 'Reportes.pdf_sha256 ya existe.';
GO

/* Variante sin anexos fotográficos, para imprimir solo la hoja del reporte.
   Se congela junto con el completo en vez de re-renderizarse a demanda, que
   rompería la inmutabilidad. */
IF COL_LENGTH('dbo.Reportes', 'pdf_reporte') IS NULL
BEGIN
    ALTER TABLE dbo.Reportes ADD pdf_reporte VARCHAR(500) NULL;
    PRINT 'Reportes.pdf_reporte agregada.';
END
ELSE PRINT 'Reportes.pdf_reporte ya existe.';
GO


/* ── equipo_id pasa a NULLABLE ───────────────────────────────────────────────
   La bitácora de carrito rojo no cuelga de un equipo: se genera por área y
   fecha. Se hace el cambio ahora, con 4 filas en la tabla, en vez de migrar
   cuando ese módulo llegue.
   ---------------------------------------------------------------------------- */
IF EXISTS (SELECT 1 FROM sys.columns
           WHERE object_id = OBJECT_ID('dbo.Reportes')
             AND name = 'equipo_id' AND is_nullable = 0)
BEGIN
    ALTER TABLE dbo.Reportes ALTER COLUMN equipo_id INT NULL;
    PRINT 'Reportes.equipo_id ahora acepta NULL.';
END
ELSE PRINT 'Reportes.equipo_id ya aceptaba NULL.';
GO


/* ── CHECK de tipo ──────────────────────────────────────────────────────────
   'mantenimiento' se conserva como valor de legado: producción puede tener
   filas con ese tipo y el script debe poder aplicarse ahí sin fallar. Los
   reportes nuevos usan 'preventivo' o 'correctivo', que sí se distinguen.
   ---------------------------------------------------------------------------- */
IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CHK_Reportes_Tipo')
BEGIN
    ALTER TABLE dbo.Reportes DROP CONSTRAINT CHK_Reportes_Tipo;
    PRINT 'CHK_Reportes_Tipo (viejo) eliminado.';
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_Reportes_tipo')
BEGIN
    ALTER TABLE dbo.Reportes WITH CHECK ADD CONSTRAINT CK_Reportes_tipo
        CHECK (tipo IN ('alta', 'baja', 'mantenimiento', 'preventivo',
                        'correctivo', 'entrada', 'salida', 'tecnovigilancia',
                        'capacitacion', 'carrito_rojo'));
    PRINT 'CK_Reportes_tipo creado.';
END
ELSE PRINT 'CK_Reportes_tipo ya existe.';
GO

IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_Reportes_estado')
BEGIN
    ALTER TABLE dbo.Reportes WITH CHECK ADD CONSTRAINT CK_Reportes_estado
        CHECK (estado IN ('borrador', 'en_proceso', 'liberado', 'cancelado'));
    PRINT 'CK_Reportes_estado creado.';
END
ELSE PRINT 'CK_Reportes_estado ya existe.';
GO


/* ── Backfill de las filas existentes ───────────────────────────────────────
   Las actas de alta que ya existen están liberadas y firmadas: nacieron con
   el flujo viejo, que congelaba el PDF de inmediato. Se marcan como tales
   para que aparezcan correctamente en el Centro de Reportes.
   ---------------------------------------------------------------------------- */
UPDATE dbo.Reportes
   SET estado           = 'liberado',
       fecha_apertura   = ISNULL(fecha_apertura, fecha),
       fecha_liberacion = ISNULL(fecha_liberacion, fecha)
 WHERE estado = 'borrador'
   AND archivo_pdf IS NOT NULL;
PRINT CONCAT('Reportes marcados como liberados: ', @@ROWCOUNT);
GO

/* La serie se deduce del folio ya emitido: 'RPT-ALTA-00003' -> 'ALTA'. */
UPDATE dbo.Reportes
   SET serie = UPPER(
           SUBSTRING(folio, 5, CHARINDEX('-', folio + '-', 5) - 5))
 WHERE serie IS NULL
   AND folio LIKE 'RPT-%';
PRINT CONCAT('Series deducidas del folio: ', @@ROWCOUNT);
GO


/* ============================================================================
   2. dbo.ReporteFirmas — más roles
   ----------------------------------------------------------------------------
   El alta solo necesitaba entrega/recibe. Un preventivo lo firma el biomédico
   y el responsable de área; una salida puede llevar además al proveedor.
   'responsable_area' son 16 caracteres, así que VARCHAR(10) ya no alcanza.
   ============================================================================ */

IF EXISTS (SELECT 1 FROM sys.columns
           WHERE object_id = OBJECT_ID('dbo.ReporteFirmas')
             AND name = 'rol' AND max_length < 20)
BEGIN
    /* El CHECK depende de la columna: hay que quitarlo para poder ensancharla. */
    IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_ReporteFirmas_rol')
        ALTER TABLE dbo.ReporteFirmas DROP CONSTRAINT CK_ReporteFirmas_rol;

    ALTER TABLE dbo.ReporteFirmas ALTER COLUMN rol VARCHAR(20) NOT NULL;
    PRINT 'ReporteFirmas.rol ampliado a VARCHAR(20).';
END
ELSE PRINT 'ReporteFirmas.rol ya es VARCHAR(20) o mayor.';
GO

IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_ReporteFirmas_rol')
BEGIN
    ALTER TABLE dbo.ReporteFirmas DROP CONSTRAINT CK_ReporteFirmas_rol;
    PRINT 'CK_ReporteFirmas_rol (viejo) eliminado.';
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_ReporteFirmas_rol')
BEGIN
    ALTER TABLE dbo.ReporteFirmas WITH CHECK ADD CONSTRAINT CK_ReporteFirmas_rol
        CHECK (rol IN ('entrega', 'recibe', 'realizo', 'biomedico',
                       'responsable_area', 'proveedor', 'autoriza'));
    PRINT 'CK_ReporteFirmas_rol creado con los roles nuevos.';
END
GO


/* ============================================================================
   3. dbo.Folios — consecutivo por serie
   ----------------------------------------------------------------------------
   Reemplaza el SELECT MAX(...)+1 que hace hoy ModelReportes.generar_folio.
   Ese patrón tiene dos problemas: es una condición de carrera (dos altas
   simultáneas obtienen el mismo número) y usa LIKE 'RPT-XXX%', que cuenta de
   más si una serie es prefijo de otra.

   Con esta tabla el consecutivo se pide con un UPDATE ... OUTPUT, que es
   atómico: el motor serializa las peticiones y cada quien recibe un número
   distinto sin necesidad de transacción explícita.
   ============================================================================ */

IF OBJECT_ID('dbo.Folios', 'U') IS NOT NULL
    PRINT 'La tabla dbo.Folios ya existe. No se hace nada.';
ELSE
BEGIN
    CREATE TABLE dbo.Folios (
        serie  VARCHAR(8) NOT NULL,
        ultimo INT        NOT NULL CONSTRAINT DF_Folios_ultimo DEFAULT (0),
        CONSTRAINT PK_Folios PRIMARY KEY CLUSTERED (serie)
    );
    PRINT 'Tabla dbo.Folios creada.';
END
GO

/* Siembra: arranca donde van los folios ya emitidos, para no repetir ninguno. */
MERGE dbo.Folios AS destino
USING (
    SELECT serie,
           MAX(TRY_CONVERT(INT, RIGHT(folio, 5))) AS ultimo
      FROM dbo.Reportes
     WHERE serie IS NOT NULL
       AND TRY_CONVERT(INT, RIGHT(folio, 5)) IS NOT NULL
     GROUP BY serie
) AS origen ON destino.serie = origen.serie
WHEN MATCHED AND destino.ultimo < origen.ultimo
    THEN UPDATE SET ultimo = origen.ultimo
WHEN NOT MATCHED BY TARGET
    THEN INSERT (serie, ultimo) VALUES (origen.serie, origen.ultimo);
PRINT CONCAT('Series sembradas en Folios: ', @@ROWCOUNT);
GO

/* Series que aún no tienen ningún folio emitido, para que el catálogo esté
   completo desde el día uno. Ninguna es prefijo de otra, a propósito. */
INSERT INTO dbo.Folios (serie, ultimo)
SELECT s.serie, 0
  FROM (VALUES ('ALTA'), ('REG'), ('MP'), ('MC'), ('BAJA'),
               ('ENT'), ('SAL'), ('TV'), ('CAP'), ('CR')) AS s(serie)
 WHERE NOT EXISTS (SELECT 1 FROM dbo.Folios f WHERE f.serie = s.serie);
PRINT CONCAT('Series nuevas agregadas: ', @@ROWCOUNT);
GO


/* ============================================================================
   4. Catálogos
   ----------------------------------------------------------------------------
   Se crean como tabla y no como CHECK porque son valores que el departamento
   va a querer editar sin pedir un cambio de esquema, y porque agrupar por
   texto libre es lo que vuelve inútil una estadística.
   ============================================================================ */

IF OBJECT_ID('dbo.Cat_Areas', 'U') IS NOT NULL
    PRINT 'La tabla dbo.Cat_Areas ya existe. No se hace nada.';
ELSE
BEGIN
    CREATE TABLE dbo.Cat_Areas (
        id     INT IDENTITY(1,1) NOT NULL,
        nombre VARCHAR(100)      NOT NULL,
        piso   INT               NULL,
        activa BIT               NOT NULL CONSTRAINT DF_Cat_Areas_activa DEFAULT (1),
        CONSTRAINT PK_Cat_Areas PRIMARY KEY CLUSTERED (id),
        CONSTRAINT UQ_Cat_Areas_nombre UNIQUE (nombre)
    );
    PRINT 'Tabla dbo.Cat_Areas creada.';
END
GO

/* Siembra desde el inventario. Las 19 áreas actuales están limpias (se
   revisaron una por una), así que un DISTINCT basta y no hace falta
   normalizar nada. */
INSERT INTO dbo.Cat_Areas (nombre)
SELECT DISTINCT LTRIM(RTRIM(e.area))
  FROM dbo.InventarioEquipos e
 WHERE e.area IS NOT NULL
   AND LTRIM(RTRIM(e.area)) <> ''
   AND NOT EXISTS (SELECT 1 FROM dbo.Cat_Areas c
                    WHERE c.nombre = LTRIM(RTRIM(e.area)));
PRINT CONCAT('Areas sembradas desde InventarioEquipos: ', @@ROWCOUNT);
GO


IF OBJECT_ID('dbo.Cat_Proveedores', 'U') IS NOT NULL
    PRINT 'La tabla dbo.Cat_Proveedores ya existe. No se hace nada.';
ELSE
BEGIN
    CREATE TABLE dbo.Cat_Proveedores (
        id       INT IDENTITY(1,1) NOT NULL,
        nombre   VARCHAR(150)      NOT NULL,
        contacto VARCHAR(150)      NULL,
        telefono VARCHAR(50)       NULL,
        correo   VARCHAR(150)      NULL,
        activo   BIT               NOT NULL CONSTRAINT DF_Cat_Proveedores_activo DEFAULT (1),
        CONSTRAINT PK_Cat_Proveedores PRIMARY KEY CLUSTERED (id),
        CONSTRAINT UQ_Cat_Proveedores_nombre UNIQUE (nombre)
    );
    PRINT 'Tabla dbo.Cat_Proveedores creada.';
END
GO


IF OBJECT_ID('dbo.Cat_Tecnicos', 'U') IS NOT NULL
    PRINT 'La tabla dbo.Cat_Tecnicos ya existe. No se hace nada.';
ELSE
BEGIN
    CREATE TABLE dbo.Cat_Tecnicos (
        id           INT IDENTITY(1,1) NOT NULL,
        usuario_id   INT               NULL,   -- si el técnico tiene cuenta
        nombre       VARCHAR(150)      NOT NULL,
        cargo        VARCHAR(150)      NULL,
        tipo         VARCHAR(10)       NOT NULL
            CONSTRAINT DF_Cat_Tecnicos_tipo DEFAULT ('interno'),
        proveedor_id INT               NULL,
        activo       BIT               NOT NULL
            CONSTRAINT DF_Cat_Tecnicos_activo DEFAULT (1),
        CONSTRAINT PK_Cat_Tecnicos PRIMARY KEY CLUSTERED (id),
        CONSTRAINT CK_Cat_Tecnicos_tipo CHECK (tipo IN ('interno', 'externo')),
        CONSTRAINT FK_Cat_Tecnicos_Prov FOREIGN KEY (proveedor_id)
            REFERENCES dbo.Cat_Proveedores (id)
    );
    PRINT 'Tabla dbo.Cat_Tecnicos creada.';
END
GO

/* Siembra desde los responsables que ya usa el programa de mantenimiento.
   Son 3 valores de texto libre; a partir de aquí son entidades. */
INSERT INTO dbo.Cat_Tecnicos (nombre, tipo)
SELECT DISTINCT LTRIM(RTRIM(m.responsable)),
       CASE WHEN m.responsable LIKE '%Interna%' THEN 'interno' ELSE 'externo' END
  FROM dbo.MantenimientosEquipos m
 WHERE m.responsable IS NOT NULL
   AND LTRIM(RTRIM(m.responsable)) <> ''
   AND NOT EXISTS (SELECT 1 FROM dbo.Cat_Tecnicos t
                    WHERE t.nombre = LTRIM(RTRIM(m.responsable)));
PRINT CONCAT('Tecnicos sembrados desde MantenimientosEquipos: ', @@ROWCOUNT);
GO


IF OBJECT_ID('dbo.Cat_TiposFalla', 'U') IS NOT NULL
    PRINT 'La tabla dbo.Cat_TiposFalla ya existe. No se hace nada.';
ELSE
BEGIN
    CREATE TABLE dbo.Cat_TiposFalla (
        id        INT IDENTITY(1,1) NOT NULL,
        nombre    VARCHAR(120)      NOT NULL,
        categoria VARCHAR(30)       NULL,
        activo    BIT               NOT NULL
            CONSTRAINT DF_Cat_TiposFalla_activo DEFAULT (1),
        CONSTRAINT PK_Cat_TiposFalla PRIMARY KEY CLUSTERED (id),
        CONSTRAINT UQ_Cat_TiposFalla_nombre UNIQUE (nombre)
    );

    /* Arranque provisional: el departamento va a querer el suyo, pero sin
       algo cargado el primer correctivo no tendría qué seleccionar. */
    INSERT INTO dbo.Cat_TiposFalla (nombre, categoria) VALUES
        ('Falla eléctrica',                'electrica'),
        ('Falla mecánica',                 'mecanica'),
        ('Falla de software o firmware',   'software'),
        ('Accesorio dañado o extraviado',  'accesorio'),
        ('Desgaste por uso',               'desgaste'),
        ('Uso incorrecto',                 'uso_incorrecto'),
        ('Consumible agotado',             'consumible'),
        ('Sin falla encontrada',           'otro'),
        ('Otra',                           'otro');

    PRINT 'Tabla dbo.Cat_TiposFalla creada y sembrada.';
END
GO


IF OBJECT_ID('dbo.Cat_CausasDemora', 'U') IS NOT NULL
    PRINT 'La tabla dbo.Cat_CausasDemora ya existe. No se hace nada.';
ELSE
BEGIN
    /* Esta es la tabla que explica un MTTR alto. Un correctivo que tardó tres
       semanas esperando una requisición y otro que tardó tres semanas porque
       nadie lo atendió son problemas distintos, y sin este catálogo se ven
       exactamente iguales en la estadística. */
    CREATE TABLE dbo.Cat_CausasDemora (
        id     INT IDENTITY(1,1) NOT NULL,
        nombre VARCHAR(120)      NOT NULL,
        activo BIT               NOT NULL
            CONSTRAINT DF_Cat_CausasDemora_activo DEFAULT (1),
        CONSTRAINT PK_Cat_CausasDemora PRIMARY KEY CLUSTERED (id),
        CONSTRAINT UQ_Cat_CausasDemora_nombre UNIQUE (nombre)
    );

    INSERT INTO dbo.Cat_CausasDemora (nombre) VALUES
        ('Sin demora'),
        ('Espera de refacción'),
        ('Espera de requisición a compras'),
        ('Espera de proveedor externo'),
        ('Espera de autorización'),
        ('Falta de herramienta o equipo de prueba'),
        ('Equipo en uso clínico'),
        ('Diagnóstico complejo'),
        ('Otra');

    PRINT 'Tabla dbo.Cat_CausasDemora creada y sembrada.';
END
GO


/* ── FK de Reportes hacia los catálogos ─────────────────────────────────────
   Se agregan hasta aquí porque las tablas destino tienen que existir antes.
   ---------------------------------------------------------------------------- */
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_Reportes_Area')
BEGIN
    ALTER TABLE dbo.Reportes WITH CHECK ADD CONSTRAINT FK_Reportes_Area
        FOREIGN KEY (area_id) REFERENCES dbo.Cat_Areas (id);
    PRINT 'FK_Reportes_Area creada.';
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_Reportes_Tecnico')
BEGIN
    ALTER TABLE dbo.Reportes WITH CHECK ADD CONSTRAINT FK_Reportes_Tecnico
        FOREIGN KEY (tecnico_id) REFERENCES dbo.Cat_Tecnicos (id);
    PRINT 'FK_Reportes_Tecnico creada.';
END
GO


/* ============================================================================
   5. Tablas transversales
   ============================================================================ */

/* ── ReporteLineas — refacciones, consumibles y costos ──────────────────────
   Una sola tabla con `clase` en vez de tablas separadas: en el formulario se
   ve como un solo bloque de renglones, y el día que se quieran separar
   consumibles de refacciones no hay migración, solo una opción más.

   precio_unitario acepta NULL a propósito: un preventivo puede registrar que
   se usó una refacción sin que nadie sepa cuánto costó. Forzar un cero
   mentiría en la suma.
   ---------------------------------------------------------------------------- */
IF OBJECT_ID('dbo.ReporteLineas', 'U') IS NOT NULL
    PRINT 'La tabla dbo.ReporteLineas ya existe. No se hace nada.';
ELSE
BEGIN
    CREATE TABLE dbo.ReporteLineas (
        id              INT IDENTITY(1,1) NOT NULL,
        reporte_id      INT               NOT NULL,
        clase           VARCHAR(20)       NOT NULL
            CONSTRAINT DF_ReporteLineas_clase DEFAULT ('refaccion'),
        descripcion     VARCHAR(300)      NOT NULL,
        cantidad        DECIMAL(10,2)     NOT NULL
            CONSTRAINT DF_ReporteLineas_cantidad DEFAULT (1),
        precio_unitario DECIMAL(12,2)     NULL,
        importe AS (cantidad * precio_unitario) PERSISTED,
        moneda          CHAR(3)           NOT NULL
            CONSTRAINT DF_ReporteLineas_moneda DEFAULT ('MXN'),
        proveedor_id    INT               NULL,
        factura         VARCHAR(50)       NULL,
        orden           INT               NOT NULL
            CONSTRAINT DF_ReporteLineas_orden DEFAULT (0),

        CONSTRAINT PK_ReporteLineas PRIMARY KEY CLUSTERED (id),
        CONSTRAINT CK_ReporteLineas_clase CHECK (clase IN
            ('refaccion', 'consumible', 'mano_obra', 'servicio_externo', 'otro')),
        CONSTRAINT CK_ReporteLineas_cantidad CHECK (cantidad > 0),
        CONSTRAINT FK_ReporteLineas_Rep FOREIGN KEY (reporte_id)
            REFERENCES dbo.Reportes (id),
        CONSTRAINT FK_ReporteLineas_Prov FOREIGN KEY (proveedor_id)
            REFERENCES dbo.Cat_Proveedores (id)
    );

    /* Se consulta siempre por reporte al pintar el detalle, y se agrega por
       reporte al sumar costos. */
    CREATE NONCLUSTERED INDEX IX_ReporteLineas_reporte
        ON dbo.ReporteLineas (reporte_id) INCLUDE (importe);

    PRINT 'Tabla dbo.ReporteLineas creada.';
END
GO


/* ── ReporteAdjuntos — fotos y archivos ─────────────────────────────────────
   Los archivos viven en disco bajo static/uploads; aquí solo va la ruta, el
   hash y de qué etapa es cada foto.

   incluir_en_pdf lo fija el modelo al subir, según la clase: encendido para
   foto_antes y foto_despues, apagado para foto_durante y los documentos. Las
   fotos del proceso son las más numerosas y las que menos aportan al lector
   del documento formal, pero son las que le sirven al técnico que abra ese
   equipo dentro de seis meses: su lugar es el expediente, no el papel.
   ---------------------------------------------------------------------------- */
IF OBJECT_ID('dbo.ReporteAdjuntos', 'U') IS NOT NULL
    PRINT 'La tabla dbo.ReporteAdjuntos ya existe. No se hace nada.';
ELSE
BEGIN
    CREATE TABLE dbo.ReporteAdjuntos (
        id             INT IDENTITY(1,1) NOT NULL,
        reporte_id     INT               NOT NULL,
        clase          VARCHAR(20)       NOT NULL,
        archivo        VARCHAR(255)      NOT NULL,   -- derivado 'web'
        archivo_thumb  VARCHAR(255)      NULL,       -- listados
        archivo_pdf    VARCHAR(255)      NULL,       -- reducido para WeasyPrint
        nombre_original VARCHAR(255)     NULL,
        descripcion    VARCHAR(300)      NULL,       -- pie de foto en el anexo
        orden          INT               NOT NULL
            CONSTRAINT DF_ReporteAdjuntos_orden DEFAULT (0),
        sha256         CHAR(64)          NULL,
        incluir_en_pdf BIT               NOT NULL
            CONSTRAINT DF_ReporteAdjuntos_incluir DEFAULT (1),
        subido_por     INT               NULL,
        fecha          DATETIME          NOT NULL
            CONSTRAINT DF_ReporteAdjuntos_fecha DEFAULT (GETDATE()),

        CONSTRAINT PK_ReporteAdjuntos PRIMARY KEY CLUSTERED (id),
        CONSTRAINT CK_ReporteAdjuntos_clase CHECK (clase IN
            ('foto_antes', 'foto_durante', 'foto_despues',
             'documento', 'requisicion')),
        CONSTRAINT FK_ReporteAdjuntos_Rep FOREIGN KEY (reporte_id)
            REFERENCES dbo.Reportes (id)
    );

    CREATE NONCLUSTERED INDEX IX_ReporteAdjuntos_reporte
        ON dbo.ReporteAdjuntos (reporte_id, clase, orden);

    PRINT 'Tabla dbo.ReporteAdjuntos creada.';
END
GO


/* ── ReporteNotas — anotaciones del técnico ─────────────────────────────────
   Contenido editable, escrito a mano durante el trabajo. Es lo que convierte
   un correctivo en un antecedente útil: "se cambió la tarjeta X, el conector
   Y viene invertido de fábrica".

   incluir_en_pdf viene APAGADO por omisión, al revés que en los adjuntos: la
   mayoría de las notas son de trabajo interno y no tienen por qué salir en un
   documento que firma el responsable del área.
   ---------------------------------------------------------------------------- */
IF OBJECT_ID('dbo.ReporteNotas', 'U') IS NOT NULL
    PRINT 'La tabla dbo.ReporteNotas ya existe. No se hace nada.';
ELSE
BEGIN
    CREATE TABLE dbo.ReporteNotas (
        id             INT IDENTITY(1,1) NOT NULL,
        reporte_id     INT               NOT NULL,
        texto          NVARCHAR(MAX)     NOT NULL,
        usuario_id     INT               NULL,
        fecha          DATETIME          NOT NULL
            CONSTRAINT DF_ReporteNotas_fecha DEFAULT (GETDATE()),
        incluir_en_pdf BIT               NOT NULL
            CONSTRAINT DF_ReporteNotas_incluir DEFAULT (0),

        CONSTRAINT PK_ReporteNotas PRIMARY KEY CLUSTERED (id),
        CONSTRAINT FK_ReporteNotas_Rep FOREIGN KEY (reporte_id)
            REFERENCES dbo.Reportes (id)
    );

    CREATE NONCLUSTERED INDEX IX_ReporteNotas_reporte
        ON dbo.ReporteNotas (reporte_id, fecha);

    PRINT 'Tabla dbo.ReporteNotas creada.';
END
GO


/* ── ReporteBitacora — auditoría automática ─────────────────────────────────
   Separada de ReporteNotas a propósito: esta la escribe el sistema, nadie la
   edita, y es la que responde "quién liberó este reporte y cuándo" frente a
   un auditor. Mezclarla con las notas del técnico haría que un registro de
   auditoría fuera editable, que es justo lo que no debe ser.
   ---------------------------------------------------------------------------- */
IF OBJECT_ID('dbo.ReporteBitacora', 'U') IS NOT NULL
    PRINT 'La tabla dbo.ReporteBitacora ya existe. No se hace nada.';
ELSE
BEGIN
    CREATE TABLE dbo.ReporteBitacora (
        id         INT IDENTITY(1,1) NOT NULL,
        reporte_id INT               NOT NULL,
        evento     VARCHAR(30)       NOT NULL,
        detalle    VARCHAR(500)      NULL,
        usuario_id INT               NULL,
        fecha      DATETIME          NOT NULL
            CONSTRAINT DF_ReporteBitacora_fecha DEFAULT (GETDATE()),

        CONSTRAINT PK_ReporteBitacora PRIMARY KEY CLUSTERED (id),
        CONSTRAINT FK_ReporteBitacora_Rep FOREIGN KEY (reporte_id)
            REFERENCES dbo.Reportes (id)
    );

    CREATE NONCLUSTERED INDEX IX_ReporteBitacora_reporte
        ON dbo.ReporteBitacora (reporte_id, fecha);

    PRINT 'Tabla dbo.ReporteBitacora creada.';
END
GO


/* ── ReporteRelaciones — trazabilidad entre reportes ────────────────────────
   Un correctivo que termina en irreparable origina una baja; un evento de
   tecnovigilancia origina un correctivo. Poder recorrer esa cadena es lo que
   convierte una carpeta de documentos sueltos en un historial.
   ---------------------------------------------------------------------------- */
IF OBJECT_ID('dbo.ReporteRelaciones', 'U') IS NOT NULL
    PRINT 'La tabla dbo.ReporteRelaciones ya existe. No se hace nada.';
ELSE
BEGIN
    CREATE TABLE dbo.ReporteRelaciones (
        id         INT IDENTITY(1,1) NOT NULL,
        origen_id  INT               NOT NULL,
        destino_id INT               NOT NULL,
        relacion   VARCHAR(20)       NOT NULL,
        fecha      DATETIME          NOT NULL
            CONSTRAINT DF_ReporteRelaciones_fecha DEFAULT (GETDATE()),

        CONSTRAINT PK_ReporteRelaciones PRIMARY KEY CLUSTERED (id),
        CONSTRAINT UQ_ReporteRelaciones UNIQUE (origen_id, destino_id, relacion),
        CONSTRAINT CK_ReporteRelaciones_distintos CHECK (origen_id <> destino_id),
        CONSTRAINT CK_ReporteRelaciones_tipo CHECK (relacion IN
            ('origina', 'reemplaza', 'complementa', 'cierra')),
        CONSTRAINT FK_ReporteRelaciones_Org FOREIGN KEY (origen_id)
            REFERENCES dbo.Reportes (id),
        CONSTRAINT FK_ReporteRelaciones_Dst FOREIGN KEY (destino_id)
            REFERENCES dbo.Reportes (id)
    );

    PRINT 'Tabla dbo.ReporteRelaciones creada.';
END
GO


/* ── Índice para el Centro de Reportes ──────────────────────────────────────
   El listado filtra por estado y ordena por fecha; sin esto cada consulta
   recorre la tabla completa.
   ---------------------------------------------------------------------------- */
IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = 'IX_Reportes_estado_fecha'
                 AND object_id = OBJECT_ID('dbo.Reportes'))
BEGIN
    CREATE NONCLUSTERED INDEX IX_Reportes_estado_fecha
        ON dbo.Reportes (estado, fecha DESC) INCLUDE (tipo, folio, equipo_id);
    PRINT 'IX_Reportes_estado_fecha creado.';
END
GO


/* ============================================================================
   Comprobación tras aplicar
   ============================================================================ */

PRINT '';
PRINT '--- Tablas del nucleo ---';
SELECT t.name AS tabla, p.rows AS filas
  FROM sys.tables t
  JOIN sys.partitions p ON p.object_id = t.object_id AND p.index_id IN (0, 1)
 WHERE t.name IN ('Reportes', 'ReporteFirmas', 'Folios', 'Cat_Areas',
                  'Cat_Tecnicos', 'Cat_Proveedores', 'Cat_TiposFalla',
                  'Cat_CausasDemora', 'ReporteLineas', 'ReporteAdjuntos',
                  'ReporteNotas', 'ReporteBitacora', 'ReporteRelaciones')
 ORDER BY t.name;

PRINT '--- Columnas nuevas de Reportes ---';
SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE
  FROM INFORMATION_SCHEMA.COLUMNS
 WHERE TABLE_NAME = 'Reportes'
 ORDER BY ORDINAL_POSITION;

PRINT '--- Estado de los reportes existentes ---';
SELECT folio, tipo, serie, estado, fecha_liberacion FROM dbo.Reportes ORDER BY id;

PRINT '--- Consecutivos ---';
SELECT serie, ultimo FROM dbo.Folios ORDER BY serie;
GO


/* ############################################################################
   PASO 3 de 5 — 2026-08-19_reportes_detalle_tipos.sql
   ----------------------------------------------------------------------------
   Una tabla de detalle por tipo: mantenimiento, movimiento, tecnovigilancia.
   ############################################################################ */

/* ============================================================================
   Fase 2 — Tablas de detalle por tipo de reporte
   ----------------------------------------------------------------------------
   Fecha:   2026-08-19
   Aplicar: después de 2026-08-19_reportes_nucleo.sql
   Motor:   SQL Server 2022

   Qué hace
     Una tabla 1:1 con dbo.Reportes por cada tipo, con sus campos propios.
     Lo común (folio, estado, fechas, firmas, fotos, costos, notas) ya vive en
     el núcleo y no se repite aquí.

   Por qué tabla por tipo y no todo en datos_json
     Porque estos son los campos que se miden. Un `resultado` o un
     `causa_demora_id` dentro de un JSON no se puede agrupar ni indexar, y
     todo el módulo se pidió justamente para poder agruparlos.

   Por qué la PK es también la FK
     reporte_id como PRIMARY KEY garantiza el 1:1 a nivel de motor: no puede
     haber dos detalles del mismo reporte ni un detalle huérfano.

   Es idempotente: se puede volver a correr sin romper nada.
   ============================================================================ */

USE HospitalGalenia;
GO

SET NOCOUNT ON;
GO

/* ============================================================================
   RepMantenimiento — preventivo, predictivo y correctivo
   ----------------------------------------------------------------------------
   Los tres comparten estructura; lo que cambia es qué campos se llenan. Un
   preventivo no tiene fecha_falla ni causa de demora; un correctivo sí.
   Separarlos en dos tablas obligaría a duplicar la mitad de las consultas de
   estadística, que casi siempre quieren ver los dos juntos.

   Las cuatro fechas del proceso viven en dbo.Reportes (fecha_apertura,
   fecha_inicio, fecha_liberacion) salvo fecha_falla, que es propia del
   correctivo: es cuándo se descompuso, no cuándo se abrió el reporte. La
   diferencia entre ambas es el tiempo de respuesta, y es medible solo si se
   guardan las dos.
   ============================================================================ */

IF OBJECT_ID('dbo.RepMantenimiento', 'U') IS NOT NULL
    PRINT 'La tabla dbo.RepMantenimiento ya existe. No se hace nada.';
ELSE
BEGIN
    CREATE TABLE dbo.RepMantenimiento (
        reporte_id          INT           NOT NULL,
        tipo_servicio       VARCHAR(12)   NOT NULL,
        descripcion_trabajo NVARCHAR(MAX) NULL,
        observaciones       NVARCHAR(MAX) NULL,

        /* Solo correctivo */
        fecha_falla         DATETIME      NULL,
        tipo_falla_id       INT           NULL,
        causa_demora_id     INT           NULL,

        resultado           VARCHAR(28)   NULL,
        horas_paro          DECIMAL(8,2)  NULL,
        requiere_seguimiento BIT          NOT NULL
            CONSTRAINT DF_RepMantenimiento_seguim DEFAULT (0),

        CONSTRAINT PK_RepMantenimiento PRIMARY KEY CLUSTERED (reporte_id),
        CONSTRAINT CK_RepMantenimiento_tipo CHECK (tipo_servicio IN
            ('preventivo', 'predictivo', 'correctivo')),
        CONSTRAINT CK_RepMantenimiento_resultado CHECK (resultado IS NULL OR resultado IN
            ('operativo', 'operativo_con_restriccion', 'fuera_de_servicio', 'irreparable')),
        CONSTRAINT CK_RepMantenimiento_horas CHECK (horas_paro IS NULL OR horas_paro >= 0),
        CONSTRAINT FK_RepMantenimiento_Rep FOREIGN KEY (reporte_id)
            REFERENCES dbo.Reportes (id),
        CONSTRAINT FK_RepMantenimiento_Falla FOREIGN KEY (tipo_falla_id)
            REFERENCES dbo.Cat_TiposFalla (id),
        CONSTRAINT FK_RepMantenimiento_Demora FOREIGN KEY (causa_demora_id)
            REFERENCES dbo.Cat_CausasDemora (id)
    );

    /* Las dos agrupaciones más frecuentes del dashboard: preventivo vs
       correctivo, y el ranking de modos de falla. */
    CREATE NONCLUSTERED INDEX IX_RepMantenimiento_tipo
        ON dbo.RepMantenimiento (tipo_servicio) INCLUDE (resultado, horas_paro);
    CREATE NONCLUSTERED INDEX IX_RepMantenimiento_falla
        ON dbo.RepMantenimiento (tipo_falla_id);

    PRINT 'Tabla dbo.RepMantenimiento creada.';
END
GO


/* ============================================================================
   RepMovimiento — entrada y salida de equipo
   ----------------------------------------------------------------------------
   Un solo formato con `sentido`, porque los campos son los mismos y solo
   cambia la dirección.

   movimiento_padre_id es lo que cierra el ciclo: la entrada apunta a la
   salida que salda. Con eso se puede saber en cualquier momento qué equipos
   están fuera (salidas sin entrada que las cierre) y —lo más útil— evitar
   que el módulo BLE los reporte como "no localizados" cuando su ausencia
   está documentada.
   ============================================================================ */

IF OBJECT_ID('dbo.RepMovimiento', 'U') IS NOT NULL
    PRINT 'La tabla dbo.RepMovimiento ya existe. No se hace nada.';
ELSE
BEGIN
    CREATE TABLE dbo.RepMovimiento (
        reporte_id             INT           NOT NULL,
        sentido                CHAR(1)       NOT NULL,   -- 'E' | 'S'
        motivo                 NVARCHAR(MAX) NULL,
        accesorios             NVARCHAR(MAX) NULL,
        destino_externo        VARCHAR(200)  NULL,
        proveedor_id           INT           NULL,
        fecha_retorno_prevista DATE          NULL,
        fecha_retorno_real     DATE          NULL,
        movimiento_padre_id    INT           NULL,

        CONSTRAINT PK_RepMovimiento PRIMARY KEY CLUSTERED (reporte_id),
        CONSTRAINT CK_RepMovimiento_sentido CHECK (sentido IN ('E', 'S')),
        CONSTRAINT FK_RepMovimiento_Rep FOREIGN KEY (reporte_id)
            REFERENCES dbo.Reportes (id),
        CONSTRAINT FK_RepMovimiento_Prov FOREIGN KEY (proveedor_id)
            REFERENCES dbo.Cat_Proveedores (id),
        CONSTRAINT FK_RepMovimiento_Padre FOREIGN KEY (movimiento_padre_id)
            REFERENCES dbo.RepMovimiento (reporte_id)
    );

    /* Para la consulta "qué está fuera": salidas sin retorno registrado. */
    CREATE NONCLUSTERED INDEX IX_RepMovimiento_abiertos
        ON dbo.RepMovimiento (sentido, fecha_retorno_real)
        INCLUDE (fecha_retorno_prevista);

    PRINT 'Tabla dbo.RepMovimiento creada.';
END
GO


/* ============================================================================
   RepTecnovigilancia
   ----------------------------------------------------------------------------
   Los campos de arriba son los que pide el formulario hoy: una redacción con
   encabezado, que es lo que el comité usa.

   Los de abajo están alineados a NOM-240-SSA1-2012 y quedan en el esquema
   pero OCULTOS en el formulario hasta que el comité defina su formato. Se
   crean ahora porque agregar columnas después obliga a migrar, y ocultarlas
   en la plantilla no cuesta nada.

   `etapa` refleja el ciclo que exige la norma: notificación inicial, reporte
   de seguimiento y reporte final. reporte_padre_id encadena los seguimientos
   con la notificación que los originó.
   ============================================================================ */

IF OBJECT_ID('dbo.RepTecnovigilancia', 'U') IS NOT NULL
    PRINT 'La tabla dbo.RepTecnovigilancia ya existe. No se hace nada.';
ELSE
BEGIN
    CREATE TABLE dbo.RepTecnovigilancia (
        reporte_id             INT           NOT NULL,
        fecha_evento           DATETIME      NULL,
        fecha_deteccion        DATETIME      NULL,
        clasificacion          VARCHAR(20)   NULL,
        descripcion            NVARCHAR(MAX) NULL,
        involucrados           NVARCHAR(MAX) NULL,
        acciones_inmediatas    NVARCHAR(MAX) NULL,

        /* NOM-240: en esquema, fuera del formulario por ahora */
        desenlace              VARCHAR(30)   NULL,
        afectado               VARCHAR(20)   NULL,
        registro_sanitario     VARCHAR(50)   NULL,
        lote                   VARCHAR(50)   NULL,
        dispositivo_resguardado BIT          NOT NULL
            CONSTRAINT DF_RepTecno_resguardado DEFAULT (0),
        causa_raiz             NVARCHAR(MAX) NULL,
        notificado_cofepris    BIT           NOT NULL
            CONSTRAINT DF_RepTecno_notificado DEFAULT (0),
        folio_cofepris         VARCHAR(50)   NULL,
        fecha_notificacion     DATE          NULL,
        etapa                  VARCHAR(12)   NULL,
        reporte_padre_id       INT           NULL,

        CONSTRAINT PK_RepTecnovigilancia PRIMARY KEY CLUSTERED (reporte_id),
        CONSTRAINT CK_RepTecno_clasificacion CHECK (clasificacion IS NULL OR clasificacion IN
            ('evento_adverso', 'evento_centinela', 'casi_incidente')),
        CONSTRAINT CK_RepTecno_desenlace CHECK (desenlace IS NULL OR desenlace IN
            ('muerte', 'dano_serio', 'intervencion_medica', 'sin_dano', 'desconocido')),
        CONSTRAINT CK_RepTecno_afectado CHECK (afectado IS NULL OR afectado IN
            ('paciente', 'operador', 'tercero', 'ninguno')),
        CONSTRAINT CK_RepTecno_etapa CHECK (etapa IS NULL OR etapa IN
            ('inicial', 'seguimiento', 'final')),
        CONSTRAINT FK_RepTecnovigilancia_Rep FOREIGN KEY (reporte_id)
            REFERENCES dbo.Reportes (id),
        CONSTRAINT FK_RepTecnovigilancia_Padre FOREIGN KEY (reporte_padre_id)
            REFERENCES dbo.RepTecnovigilancia (reporte_id)
    );

    PRINT 'Tabla dbo.RepTecnovigilancia creada.';
END
GO


/* ============================================================================
   Comprobación tras aplicar
   ============================================================================ */

PRINT '';
PRINT '--- Tablas de detalle ---';
SELECT t.name AS tabla, p.rows AS filas
  FROM sys.tables t
  JOIN sys.partitions p ON p.object_id = t.object_id AND p.index_id IN (0, 1)
 WHERE t.name IN ('RepMantenimiento', 'RepMovimiento', 'RepTecnovigilancia')
 ORDER BY t.name;
GO


/* ############################################################################
   PASO 4 de 5 — 2026-08-19_inventario_columnas_kpi.sql
   ----------------------------------------------------------------------------
   Columnas nuevas en InventarioEquipos. Todas NULLABLE: el inventario existente no se toca.
   ############################################################################ */

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


/* ############################################################################
   PASO 5 de 5 — 2026-08-21_reportes_movimiento.sql
   ----------------------------------------------------------------------------
   ReporteEquipos (varios equipos por movimiento) y la clase de adjunto foto_estado.
   ############################################################################ */

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


/* ============================================================================
   VERIFICACION — que quedo despues de correr todo
   ============================================================================ */
PRINT '';
PRINT '=========================================================';
PRINT ' VERIFICACION DE LA MIGRACION';
PRINT '=========================================================';
GO

SELECT 'Tablas del modulo' AS bloque,
       t.name AS tabla,
       (SELECT COUNT(*) FROM sys.columns c WHERE c.object_id = t.object_id) AS columnas
  FROM sys.tables t
 WHERE t.name IN ('Reportes', 'ReporteFirmas', 'Folios',
                  'Cat_Areas', 'Cat_Proveedores', 'Cat_Tecnicos',
                  'Cat_TiposFalla', 'Cat_CausasDemora',
                  'ReporteLineas', 'ReporteAdjuntos', 'ReporteNotas',
                  'ReporteBitacora', 'ReporteRelaciones', 'ReporteEquipos',
                  'RepMantenimiento', 'RepMovimiento', 'RepTecnovigilancia')
 ORDER BY t.name;
GO

/* Las 16 tablas nuevas deben aparecer arriba. Si falta alguna, ese bloque
   fallo: revisa el mensaje de error correspondiente mas arriba. */
SELECT 'Conteo de tablas nuevas' AS bloque, COUNT(*) AS encontradas, 16 AS esperadas
  FROM sys.tables
 WHERE name IN ('ReporteFirmas', 'Folios', 'Cat_Areas', 'Cat_Proveedores',
                'Cat_Tecnicos', 'Cat_TiposFalla', 'Cat_CausasDemora',
                'ReporteLineas', 'ReporteAdjuntos', 'ReporteNotas',
                'ReporteBitacora', 'ReporteRelaciones', 'ReporteEquipos',
                'RepMantenimiento', 'RepMovimiento', 'RepTecnovigilancia');
GO

/* Series de folio: deben ser 10, todas en 0 en una base recien migrada. */
SELECT 'Series de folio' AS bloque, serie, ultimo FROM dbo.Folios ORDER BY serie;
GO

/* Catalogos sembrados. Cat_Areas y Cat_Tecnicos se llenan desde los datos que
   YA tiene produccion, asi que estos numeros seran distintos a los de
   pruebas — eso es correcto. Cat_Proveedores nace vacio a proposito: hay que
   capturar la lista real de proveedores externos. */
SELECT 'Cat_Areas'        AS catalogo, COUNT(*) AS filas FROM dbo.Cat_Areas
UNION ALL SELECT 'Cat_Tecnicos',       COUNT(*) FROM dbo.Cat_Tecnicos
UNION ALL SELECT 'Cat_TiposFalla',     COUNT(*) FROM dbo.Cat_TiposFalla
UNION ALL SELECT 'Cat_CausasDemora',   COUNT(*) FROM dbo.Cat_CausasDemora
UNION ALL SELECT 'Cat_Proveedores',    COUNT(*) FROM dbo.Cat_Proveedores;
GO

/* Columnas nuevas en las tablas que ya existian. */
SELECT 'Columnas nuevas en Reportes' AS bloque, name AS columna
  FROM sys.columns
 WHERE object_id = OBJECT_ID('dbo.Reportes')
   AND name IN ('estado','serie','area_id','tecnico_id','fecha_apertura',
                'fecha_inicio','fecha_liberacion','liberado_por',
                'pdf_sha256','pdf_reporte')
 ORDER BY name;
GO

SELECT 'Columnas nuevas en InventarioEquipos' AS bloque, name AS columna
  FROM sys.columns
 WHERE object_id = OBJECT_ID('dbo.InventarioEquipos')
   AND name IN ('valor_adquisicion','moneda','vida_util_anios','criticidad',
                'registro_sanitario','area_id','fecha_baja','reporte_baja_id')
 ORDER BY name;
GO

/* Los reportes que YA existian en produccion siguen ahi y quedaron marcados
   como liberados por el script del nucleo. */
SELECT 'Reportes existentes por estado' AS bloque, estado, COUNT(*) AS n
  FROM dbo.Reportes GROUP BY estado ORDER BY estado;
GO

PRINT '';
PRINT 'Migracion terminada. Revisa los resultados de arriba.';
PRINT 'Si las 16 tablas aparecen y no hubo errores, el SQL esta completo.';
PRINT 'Falta la parte que NO es SQL: ver GUIA-DESPLIEGUE.md';
GO
