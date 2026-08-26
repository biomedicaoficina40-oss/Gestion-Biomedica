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
