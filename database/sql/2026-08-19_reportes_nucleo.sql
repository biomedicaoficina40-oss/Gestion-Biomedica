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
