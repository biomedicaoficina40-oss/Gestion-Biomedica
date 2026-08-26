"""
Centro de Reportes — historial documental de todos los tipos.

Responde una pregunta distinta a la del dashboard de mantenimientos: aquel dice
*qué me toca hacer* (vencidos, próximos); este dice *qué se hizo*. Por eso son
dos pantallas y no una — mezclarlas haría que la lista de pendientes y el
archivo histórico compitan por el mismo espacio.

En esta etapa el acta de alta aparece en el listado pero se abre con su visor de
siempre (admin.ver_reporte_alta): funciona, está probado y no hay razón para
tocarlo. Los tipos nuevos usan el visor propio conforme se van construyendo.
"""

import os

from flask import (Blueprint, abort, flash, jsonify, redirect, render_template,
                   request, send_file, url_for)
from flask_login import current_user

from database.db import get_connection
from models.entities.decorators import (ROL_BIOMEDICO, ROL_USUARIO,
                                        requiere_rol, tiene_rol)
from models.ModelFirmas import ModelFirmas
from models.ModelInventario import ModelInventario
from models.reportes.adjuntos import CLASES as CLASES_ADJUNTO
from models.reportes.adjuntos import ModelAdjuntos
from models.reportes.base import (EDITABLES, ETIQUETAS_ESTADO, ETIQUETAS_TIPO,
                                  LIBERADO, ModelReporteBase)
from models.reportes.lineas import CLASES as CLASES_LINEA
from models.reportes.lineas import ModelLineas
from models.reportes.mantenimiento import (ETIQUETAS_RESULTADO,
                                           ETIQUETAS_SERVICIO,
                                           ModelMantenimiento)
from models.reportes.movimiento import SENTIDO_POR_TIPO, ModelMovimiento
from models.reportes.notas import ModelNotas
from models.reportes.tecnovigilancia import (CLASIFICACIONES,
                                              ETIQUETAS_CLASIFICACION,
                                              ModelTecnovigilancia)
from models.reportes.kpis import ModelKPIs
from services import reporte_contexto, reporte_pdf

reportes_bp = Blueprint('reportes', __name__)

POR_PAGINA = 15

# Tipos que abren con el buscador de un solo equipo, con su propio módulo de
# captura (editar.html) y que usan ModelMantenimiento para el detalle.
TIPOS_MANTENIMIENTO = ('preventivo', 'correctivo')

# Tipos que abren con el picker de uno-o-varios equipos, con su propio módulo
# (editar_movimiento.html) y que usan ModelMovimiento para el detalle.
TIPOS_MOVIMIENTO = ('entrada', 'salida')

# Tipos de un solo equipo pero con su propio módulo (editar_tecnovigilancia.html)
# y ModelTecnovigilancia para el detalle. Tupla de uno solo por ahora, para que
# el resto del archivo trate "a qué grupo pertenece un tipo" siempre igual
# (`in TIPOS_X`) en vez de comparar contra un string suelto en unos lugares sí
# y en otros no.
TIPOS_TECNOVIGILANCIA = ('tecnovigilancia',)

# Firmas que hay que tener capturadas para poder liberar cada tipo.
# En mantenimiento el biomédico y el responsable de área firman en el momento
# de entregar el equipo, que es cuando físicamente están juntos; por eso son
# requisito y no un paso posterior. Así el PDF nace firmado y no se regenera
# nunca. En movimiento, solo el biomédico es obligatorio — responsable de
# área y proveedor son independientes entre sí (ver `_pendientes_para_liberar`
# y `reporte_contexto._firmas_requeridas_movimiento`). Tecnovigilancia sigue el
# patrón de mantenimiento (par fijo): es un documento de cumplimiento, no una
# constancia de logística.
FIRMAS_OBLIGATORIAS = {
    'preventivo':      ('biomedico', 'responsable_area'),
    'correctivo':      ('biomedico', 'responsable_area'),
    'entrada':         ('biomedico',),
    'salida':          ('biomedico',),
    'tecnovigilancia': ('biomedico', 'responsable_area'),
}

# Tipos que se ofrecen en el selector, en el orden en que se usan.
# 'mantenimiento' queda fuera a propósito: es un valor de legado que puede
# existir en producción pero que ya no se emite.
TIPOS_LISTABLES = ('preventivo', 'correctivo', 'entrada', 'salida',
                   'tecnovigilancia', 'alta', 'baja')


@reportes_bp.app_context_processor
def _helpers_plantilla():
    """
    Publica `estatico()` para TODAS las plantillas del proyecto.

    Se registra desde un blueprint y no en app.py siguiendo el precedente de
    `puede()` y `etiqueta_rol()`, que viven en auth_routes por la misma razón:
    evitar tocar app.py.

    El problema que resuelve: app.py fija SEND_FILE_MAX_AGE_DEFAULT en 30 días,
    así que un cambio en un .js o .css de static/ NO le llega a nadie que ya
    haya visitado el sitio hasta que caduque la caché o haga una recarga dura.
    Se descubrió con firma_pad.js: el navegador seguía ejecutando la versión
    vieja mientras el archivo en disco ya tenía el arreglo.

    `estatico('Js/firma_pad.js')` cuelga la fecha de modificación del archivo
    como parámetro, así que la URL cambia sola en cuanto el archivo cambia y el
    navegador vuelve a pedirlo. Mientras no cambie, se sigue aprovechando la
    caché de 30 días.
    """
    def estatico(ruta):
        completa = os.path.join(reporte_pdf.STATIC_DIR, *ruta.split('/'))
        try:
            version = int(os.path.getmtime(completa))
        except OSError:
            version = None
        return url_for('static', filename=ruta, v=version)

    return {'estatico': estatico}


def _puede_ver_costos():
    """
    Los importes son solo para Biomédico y Administrador.

    Se consulta en la ruta y se pasa a la plantilla en vez de que la plantilla
    llame a `puede()` por su cuenta, para que el mismo valor gobierne la tabla
    en pantalla y la del PDF. Ocultar una columna en la vista no sirve de nada
    si el archivo descargado la trae.
    """
    return tiene_rol(ROL_BIOMEDICO)


def _json_adjunto(adjunto):
    """
    Un adjunto en la forma mínima que la pantalla necesita para pintarlo.

    Se devuelve al subir para que el módulo de captura inserte la miniatura en
    su sitio en vez de recargar la página. Una recarga por foto, con el equipo
    enfrente y la red del hospital, es justo lo que hace que capturar en el piso
    salga más caro que anotarlo en papel.
    """
    if not adjunto:
        return None
    return {
        'id':              adjunto.get('id'),
        'clase':           adjunto.get('clase'),
        'archivo':         adjunto.get('archivo'),
        'archivo_thumb':   adjunto.get('archivo_thumb') or adjunto.get('archivo'),
        'nombre_original': adjunto.get('nombre_original'),
        'descripcion':     adjunto.get('descripcion') or '',
        'incluir_en_pdf':  bool(adjunto.get('incluir_en_pdf')),
        'url':             url_for('static', filename='uploads/' + (adjunto.get('archivo') or '')),
        'url_thumb':       url_for('static', filename='uploads/' + (
                               adjunto.get('archivo_thumb') or adjunto.get('archivo') or '')),
    }


def _json_linea(linea):
    """Un renglón de refacción, con el importe ya cuadrado a centavos."""
    if not linea:
        return None
    return {
        'id':              linea.get('id'),
        'descripcion':     linea.get('descripcion'),
        'clase':           linea.get('clase'),
        'cantidad':        float(linea.get('cantidad') or 0),
        'precio_unitario': (None if linea.get('precio_unitario') is None
                            else float(linea['precio_unitario'])),
        'importe':         (None if linea.get('importe') is None
                            else float(linea['importe'])),
    }


def _json_nota(nota):
    """Una anotación con autor y fecha ya formateados."""
    if not nota:
        return None
    return {
        'id':             nota.get('id'),
        'texto':          nota.get('texto'),
        'autor':          nota.get('autor') or 'Sistema',
        'fecha':          nota['fecha'].strftime('%d/%m/%Y %H:%M') if nota.get('fecha') else '',
        'incluir_en_pdf': bool(nota.get('incluir_en_pdf')),
    }


def _json_equipo(equipo):
    """Un equipo tal como lo necesita el picker de un movimiento."""
    if not equipo:
        return None
    return {
        'id':                equipo.get('id'),
        'equipo_unidad':     equipo.get('equipo_unidad'),
        'marca':             equipo.get('marca'),
        'modelo':            equipo.get('modelo'),
        'numero_serie':      equipo.get('numero_serie'),
        'numero_inventario': equipo.get('numero_inventario'),
    }


# ── Centro de Reportes ─────────────────────────────────────────

@reportes_bp.route('/reportes')
@requiere_rol(ROL_USUARIO)
def centro():
    """
    Listado con filtros y buscador.

    Igual que el inventario: los filtros van al servidor y la respuesta se
    intercambia por fetch sin recargar la página. El fragmento es el mismo
    HTML que el render inicial, así que no hay dos maquetados que mantener
    sincronizados.
    """
    db = None
    try:
        db = get_connection()

        filtros = {
            'tipo':   (request.args.get('tipo') or '').strip() or None,
            'estado': (request.args.get('estado') or '').strip() or None,
            'q':      (request.args.get('q') or '').strip() or None,
            'desde':  (request.args.get('desde') or '').strip() or None,
            'hasta':  (request.args.get('hasta') or '').strip() or None,
        }
        page = max(1, request.args.get('page', 1, type=int) or 1)

        # `estado=abiertos` no es un estado de la base: es el atajo a todo lo que
        # sigue en captura. Existe porque un borrador recién abierto y un
        # trabajo a medias son la misma pregunta para quien vuelve a buscarlos.
        consulta = dict(filtros)
        if consulta['estado'] == 'abiertos':
            consulta['estado'] = EDITABLES

        reportes, total = ModelReporteBase.listar(
            db, page=page, per_page=POR_PAGINA, **consulta)
        stats = ModelReporteBase.stats(db, tipo=filtros['tipo'])

        contexto = dict(
            reportes    = reportes,
            total       = total,
            page        = page,
            per_page    = POR_PAGINA,
            filtros     = filtros,
            stats       = stats,
            tipos       = [(t, ETIQUETAS_TIPO.get(t, t)) for t in TIPOS_LISTABLES],
            estados     = ETIQUETAS_ESTADO,
            etiq_tipo   = ETIQUETAS_TIPO,
            ver_costos  = _puede_ver_costos(),
        )

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return render_template('reportes/_fragmento.html', **contexto)
        return render_template('reportes/listado.html', **contexto)

    finally:
        if db:
            db.close()


@reportes_bp.route('/reportes/<int:reporte_id>')
@requiere_rol(ROL_USUARIO)
def ver(reporte_id):
    """
    Visor de un reporte.

    El acta de alta se manda a su pantalla de siempre: ya tiene visor, panel de
    firma y regeneración, y reimplementarlo aquí solo agregaría una segunda
    versión que mantener.
    """
    db = None
    try:
        db = get_connection()
        reporte = ModelReporteBase.get_by_id(db, reporte_id)
        if not reporte:
            abort(404)

        if reporte['tipo'] == 'alta' and reporte.get('equipo_id'):
            return redirect(url_for('admin.ver_reporte_alta', id=reporte['equipo_id']))

        equipo = (ModelInventario.get_by_id(db, reporte['equipo_id'])
                  if reporte.get('equipo_id') else None)
        adjuntos = ModelAdjuntos.get_por_reporte(db, reporte_id)
        ver_costos = _puede_ver_costos()

        # Un movimiento puede ser de varios equipos; el resto de tipos siguen
        # mostrando el único `equipo` de siempre. `equipos` viaja vacío para
        # ellos y la plantilla decide con cuál de los dos pintar la sección.
        es_movimiento = reporte['tipo'] in TIPOS_MOVIMIENTO
        detalle_movimiento = ModelMovimiento.get(db, reporte_id) if es_movimiento else None
        es_tecno = reporte['tipo'] in TIPOS_TECNOVIGILANCIA
        detalle_tecno = ModelTecnovigilancia.get(db, reporte_id) if es_tecno else None

        return render_template(
            'reportes/ver.html',
            reporte   = reporte,
            equipo    = equipo,
            equipos   = ModelMovimiento.get_equipos(db, reporte_id) if es_movimiento else [],
            movimiento = detalle_movimiento,
            tecno     = detalle_tecno,
            etiq_clasificacion = ETIQUETAS_CLASIFICACION,
            adjuntos  = ModelAdjuntos.agrupar_por_clase(adjuntos),
            notas     = ModelNotas.get_por_reporte(db, reporte_id),
            lineas    = ModelLineas.get_por_reporte(db, reporte_id) if ver_costos else [],
            totales   = ModelLineas.total(db, reporte_id) if ver_costos else None,
            bitacora  = ModelReporteBase.get_bitacora(db, reporte_id),
            etiq_tipo = ETIQUETAS_TIPO,
            etiq_est  = ETIQUETAS_ESTADO,
            ver_costos = ver_costos,
        )
    finally:
        if db:
            db.close()


@reportes_bp.route('/reportes/<int:reporte_id>/archivo')
@requiere_rol(ROL_USUARIO)
def archivo(reporte_id):
    """
    Sirve el PDF del reporte.

    Liberado  → se manda el archivo de disco, SIEMPRE. Nunca se re-renderiza:
                es lo que hace que el hash guardado signifique algo, y de paso
                lo vuelve instantáneo (WeasyPrint maqueta cuatro veces).
    En curso  → vista previa al vuelo, con marca de agua, servida desde memoria
                y sin tocar el disco. Un borrador escrito en la carpeta de
                reportes sería indistinguible de uno liberado al mirarla.

    `?anexos=0` sirve la variante sin las hojas de fotos, que también se congela
    al liberar en vez de generarse a demanda.
    """
    db = None
    try:
        db = get_connection()
        reporte = ModelReporteBase.get_by_id(db, reporte_id)
        if not reporte:
            abort(404)

        con_anexos = request.args.get('anexos', '1') != '0'
        descargar = request.args.get('descargar') == '1'

        if reporte['estado'] == LIBERADO:
            relativa = (reporte.get('archivo_pdf') if con_anexos
                        else (reporte.get('pdf_reporte') or reporte.get('archivo_pdf')))
            if not relativa:
                abort(404)
            completa = os.path.join(reporte_pdf.UPLOADS_DIR, *str(relativa).split('/'))
            if not os.path.exists(completa):
                abort(404)
            return send_file(completa, mimetype='application/pdf',
                             as_attachment=descargar,
                             download_name=f"{reporte['folio']}.pdf")

        # En curso: se maqueta al vuelo, con marca de agua, servido desde
        # memoria. Nunca toca el disco — un borrador escrito en la carpeta de
        # reportes sería indistinguible de uno liberado al mirarla, y el
        # respaldo acabaría lleno de documentos que nadie firmó.
        equipo = (ModelInventario.get_by_id(db, reporte['equipo_id'])
                  if reporte.get('equipo_id') else None)
        plantilla, contexto = reporte_contexto.para(
            db, reporte, equipo, ver_costos=_puede_ver_costos())
        if not plantilla:
            abort(404)

        buffer = reporte_pdf.vista_previa(plantilla, contexto)
        return send_file(buffer, mimetype='application/pdf',
                         as_attachment=descargar,
                         download_name=f"{reporte['folio']}-borrador.pdf")

    finally:
        if db:
            db.close()


# ── Captura ────────────────────────────────────────────────────

@reportes_bp.route('/reportes/nuevo/<tipo>', methods=['GET', 'POST'])
@requiere_rol(ROL_BIOMEDICO)
def nuevo(tipo):
    """
    Abre un expediente y manda al módulo de captura.

    Con `?equipo=<id>` el equipo llega resuelto —es el caso de los botones
    sembrados en la ficha, el dashboard y la vista NFC—. Sin él, el formulario
    arranca en blanco y el equipo se elige con el buscador por número de
    inventario.

    Se abre en POST y no en GET a propósito: un GET que crea un registro se
    dispara solo con que alguien recargue o el navegador precargue el enlace,
    y dejaría folios apartados sin reporte.

    Entrada y salida se abren distinto —uno o varios equipos, no uno solo— y
    se delegan enteras a `_nuevo_movimiento`. Tecnovigilancia comparte esta
    misma función (un solo equipo, igual que mantenimiento): lo único que
    cambia es qué "crear detalle" se llama al final.
    """
    if tipo not in TIPOS_MANTENIMIENTO + TIPOS_MOVIMIENTO + TIPOS_TECNOVIGILANCIA:
        abort(404)
    if tipo in TIPOS_MOVIMIENTO:
        return _nuevo_movimiento(tipo)

    db = None
    try:
        db = get_connection()
        equipo_id = request.args.get('equipo', type=int)
        equipo = ModelInventario.get_by_id(db, equipo_id) if equipo_id else None

        if request.method == 'GET':
            # Los expedientes sin terminar se enseñan ANTES de abrir otro. Es
            # el punto donde alguien que salió del módulo de captura vuelve a
            # entrar por instinto, y sin esto la única salida era abrir un
            # duplicado y quemar un folio.
            abiertos = ModelReporteBase.abiertos(
                db, equipo_id=equipo_id, tipo=(None if equipo_id else tipo))
            return render_template(
                'reportes/nuevo.html',
                tipo      = tipo,
                etiqueta  = ETIQUETAS_TIPO.get(tipo, tipo),
                equipo    = equipo,
                abiertos  = abiertos,
                etiq_tipo = ETIQUETAS_TIPO,
                etiq_est  = ETIQUETAS_ESTADO,
                catalogos = ModelMantenimiento.get_catalogos(db),
            )

        # POST: se abre el expediente
        equipo_id = request.form.get('equipo_id', type=int) or equipo_id
        if not equipo_id:
            flash('Selecciona un equipo para abrir el reporte.', 'warning')
            return redirect(url_for('reportes.nuevo', tipo=tipo))

        equipo = ModelInventario.get_by_id(db, equipo_id)
        if not equipo:
            flash('El equipo no existe.', 'danger')
            return redirect(url_for('reportes.nuevo', tipo=tipo))

        # Dos expedientes abiertos del mismo tipo para el mismo equipo casi
        # siempre son un accidente: alguien salió del módulo de captura y no
        # supo cómo volver. Se manda al que ya existe en vez de gastar folio.
        # `forzar=1` deja abrir otro a propósito, desde el aviso de la pantalla.
        if request.form.get('forzar') != '1':
            previos = ModelReporteBase.abiertos(db, equipo_id=equipo_id, tipo=tipo)
            if previos:
                return redirect(url_for('reportes.editar', reporte_id=previos[0]['id']))

        # El área del reporte es donde ocurre el trabajo, que no siempre es
        # donde el equipo está registrado. Se propone la suya y se puede cambiar.
        area_id = request.form.get('area_id', type=int) or _area_de(db, equipo)

        ok, reporte_id, folio = ModelReporteBase.abrir(
            db, tipo=tipo, equipo_id=equipo_id,
            usuario_id=current_user.IDusuario, datos_equipo=equipo,
            area_id=area_id, tecnico_id=request.form.get('tecnico_id', type=int))
        if not ok:
            flash(folio or 'No se pudo abrir el reporte.', 'danger')
            return redirect(url_for('reportes.nuevo', tipo=tipo))

        if tipo in TIPOS_TECNOVIGILANCIA:
            ModelTecnovigilancia.crear(db, reporte_id)
        else:
            ModelMantenimiento.crear(db, reporte_id, tipo_servicio=(
                request.form.get('tipo_servicio') or
                ('correctivo' if tipo == 'correctivo' else 'preventivo')))

        return redirect(url_for('reportes.editar', reporte_id=reporte_id))

    finally:
        if db:
            db.close()


def _nuevo_movimiento(tipo):
    """
    Abre una entrada o salida — uno o varios equipos, elegidos con un buscador
    que va agregando a una lista en vez de resolver uno solo.

    Separado de `nuevo()` porque la forma de elegir equipo es la única parte
    que de verdad cambia; el resto (folio, área, redirigir a captura) es
    igual y no vale la pena bifurcar con `if`s todo el cuerpo de la función.
    """
    db = None
    try:
        db = get_connection()
        equipo_id = request.args.get('equipo', type=int)
        equipo_inicial = ModelInventario.get_by_id(db, equipo_id) if equipo_id else None

        if request.method == 'GET':
            return render_template(
                'reportes/nuevo_movimiento.html',
                tipo           = tipo,
                etiqueta       = ETIQUETAS_TIPO.get(tipo, tipo),
                equipo_inicial = equipo_inicial,
                catalogos      = ModelMovimiento.get_catalogos(db),
            )

        # POST: uno o varios <input type="hidden" name="equipo_ids"> — los va
        # agregando el JS conforme se eligen en el buscador.
        equipo_ids = [i for i in request.form.getlist('equipo_ids', type=int) if i]
        if not equipo_ids:
            flash('Agrega al menos un equipo para abrir el reporte.', 'warning')
            return redirect(url_for('reportes.nuevo', tipo=tipo))

        primero = ModelInventario.get_by_id(db, equipo_ids[0])
        if not primero:
            flash('El equipo no existe.', 'danger')
            return redirect(url_for('reportes.nuevo', tipo=tipo))

        area_id = request.form.get('area_id', type=int) or _area_de(db, primero)

        ok, reporte_id, folio = ModelReporteBase.abrir(
            db, tipo=tipo, equipo_id=equipo_ids[0],
            usuario_id=current_user.IDusuario, datos_equipo=primero,
            area_id=area_id, tecnico_id=request.form.get('tecnico_id', type=int))
        if not ok:
            flash(folio or 'No se pudo abrir el reporte.', 'danger')
            return redirect(url_for('reportes.nuevo', tipo=tipo))

        ModelMovimiento.crear(db, reporte_id, sentido=SENTIDO_POR_TIPO[tipo])

        # Cada id se valida al agregarlo: uno inventado (manipulando el POST a
        # mano) simplemente no encuentra el FK y se descarta en silencio, en
        # vez de tumbar la apertura completa por un solo id malo.
        agregados = 0
        for eid in equipo_ids:
            if ModelInventario.get_by_id(db, eid):
                ok_eq, _ = ModelMovimiento.agregar_equipo(db, reporte_id, eid)
                agregados += 1 if ok_eq else 0
        if agregados == 0:
            flash('Ninguno de los equipos existe.', 'danger')

        return redirect(url_for('reportes.editar', reporte_id=reporte_id))
    finally:
        if db:
            db.close()


def _area_de(db, equipo):
    """id de Cat_Areas que corresponde al área de texto del equipo, si existe."""
    if not equipo or not equipo.get('area'):
        return None
    cursor = None
    try:
        cursor = db.cursor()
        cursor.execute(
            "SELECT id FROM HospitalGalenia.dbo.Cat_Areas WHERE nombre = ?",
            (str(equipo['area']).strip(),))
        fila = cursor.fetchone()
        return fila[0] if fila else None
    except Exception:
        return None
    finally:
        if cursor:
            cursor.close()


@reportes_bp.route('/reportes/<int:reporte_id>/editar')
@requiere_rol(ROL_BIOMEDICO)
def editar(reporte_id):
    """
    Módulo de captura: la pantalla a la que se reentra mientras dure el trabajo.

    No es un formulario que se llena de una sentada. Un preventivo puede tomar
    dos jornadas y un correctivo semanas esperando una requisición, así que
    todo se guarda conforme se captura y esta pantalla muestra el estado.
    """
    db = None
    try:
        db = get_connection()
        reporte = ModelReporteBase.get_by_id(db, reporte_id)
        if not reporte:
            abort(404)

        if reporte['estado'] not in EDITABLES:
            flash('Este reporte ya fue liberado y no se puede editar.', 'warning')
            return redirect(url_for('reportes.ver', reporte_id=reporte_id))

        adjuntos = ModelAdjuntos.get_por_reporte(db, reporte_id)
        ver_costos = _puede_ver_costos()

        # Qué falta para poder liberar. Se calcula aquí y no en la plantilla
        # para que el botón y la validación del POST usen el mismo criterio.
        firmas = ModelFirmas.get_por_reporte(db, reporte_id) or {}
        pendientes = _pendientes_para_liberar(reporte, firmas, db)

        if reporte['tipo'] in TIPOS_MOVIMIENTO:
            return render_template(
                'reportes/editar_movimiento.html',
                reporte    = reporte,
                equipos    = ModelMovimiento.get_equipos(db, reporte_id),
                detalle    = ModelMovimiento.get(db, reporte_id) or {},
                adjuntos   = ModelAdjuntos.agrupar_por_clase(adjuntos),
                notas      = ModelNotas.get_por_reporte(db, reporte_id),
                firmas     = firmas,
                pendientes = pendientes,
                catalogos  = ModelMovimiento.get_catalogos(db),
                etiq_tipo  = ETIQUETAS_TIPO,
                etiq_sentido = {'entrada': 'Entrada', 'salida': 'Salida'},
                # Salidas sin retorno, para que una entrada pueda vincularse a
                # la que cierra. Solo hace falta calcularlas para una entrada.
                salidas_abiertas = (ModelMovimiento.salidas_sin_retorno(db)
                                   if reporte['tipo'] == 'entrada' else []),
            )

        equipo = (ModelInventario.get_by_id(db, reporte['equipo_id'])
                  if reporte.get('equipo_id') else None)

        if reporte['tipo'] in TIPOS_TECNOVIGILANCIA:
            return render_template(
                'reportes/editar_tecnovigilancia.html',
                reporte    = reporte,
                equipo     = equipo,
                detalle    = ModelTecnovigilancia.get(db, reporte_id) or {},
                adjuntos   = ModelAdjuntos.agrupar_por_clase(adjuntos),
                notas      = ModelNotas.get_por_reporte(db, reporte_id),
                firmas     = firmas,
                pendientes = pendientes,
                catalogos  = ModelMantenimiento.get_catalogos(db),
                etiq_tipo  = ETIQUETAS_TIPO,
                etiq_clasificacion = ETIQUETAS_CLASIFICACION,
            )

        return render_template(
            'reportes/editar.html',
            reporte    = reporte,
            equipo     = equipo,
            detalle    = ModelMantenimiento.get(db, reporte_id) or {},
            adjuntos   = ModelAdjuntos.agrupar_por_clase(adjuntos),
            notas      = ModelNotas.get_por_reporte(db, reporte_id),
            lineas     = ModelLineas.get_por_reporte(db, reporte_id) if ver_costos else [],
            totales    = ModelLineas.total(db, reporte_id) if ver_costos else None,
            firmas     = firmas,
            pendientes = pendientes,
            catalogos  = ModelMantenimiento.get_catalogos(db),
            etiq_tipo  = ETIQUETAS_TIPO,
            etiq_serv  = ETIQUETAS_SERVICIO,
            etiq_res   = ETIQUETAS_RESULTADO,
            clases_linea = CLASES_LINEA,
            ver_costos = ver_costos,
        )
    finally:
        if db:
            db.close()


def _pendientes_para_liberar(reporte, firmas, db):
    """
    Lo que falta para liberar, en lenguaje llano y con a dónde ir a arreglarlo.

    Devolver la lista en vez de un booleano permite que la pantalla diga qué
    falta en vez de dejar el botón apagado sin explicación; el `ancla` deja
    además que el aviso lleve al campo de un toque, que en un teléfono es la
    diferencia entre corregirlo y abandonarlo.
    """
    faltantes = []

    if reporte['tipo'] in TIPOS_MOVIMIENTO:
        detalle = ModelMovimiento.get(db, reporte['id']) or {}

        if not (detalle.get('motivo') or '').strip():
            faltantes.append({'texto': 'Describe el motivo', 'ancla': 'edMotivo'})

        # No hay "descripción del trabajo" que valide un movimiento vacío: lo
        # que lo vuelve un documento real es tener al menos un equipo. Sin
        # este candado, quitar el último equipo (ModelMovimiento.quitar_equipo
        # ya lo impide) dejaría, en teoría, un reporte liberable sin nada
        # que reportar.
        if not ModelMovimiento.get_equipos(db, reporte['id']):
            faltantes.append({'texto': 'Agrega al menos un equipo', 'ancla': 's-equipos'})

    elif reporte['tipo'] in TIPOS_TECNOVIGILANCIA:
        detalle = ModelTecnovigilancia.get(db, reporte['id']) or {}

        if not (detalle.get('descripcion') or '').strip():
            faltantes.append({'texto': 'Describe lo ocurrido', 'ancla': 'edDescripcion'})

        # Sin clasificación el reporte no dice qué tan grave fue el evento —
        # es el dato que después se agrupa para saber si hay un patrón, y
        # dejarlo en blanco lo volvería inútil para eso.
        if not detalle.get('clasificacion'):
            faltantes.append({'texto': 'Elige la clasificación del evento',
                              'ancla': 'edClasificacion'})

    else:
        detalle = ModelMantenimiento.get(db, reporte['id']) or {}

        if not (detalle.get('descripcion_trabajo') or '').strip():
            faltantes.append({'texto': 'Describe el trabajo realizado',
                              'ancla': 'edDescripcion'})

        # Sin fecha de falla no hay antecedente que calcular: es el único dato
        # que hace falta para saber cuánto tardó la atención, y es lo que un
        # correctivo existe para explicar.
        if reporte['tipo'] == 'correctivo' and not detalle.get('fecha_falla'):
            faltantes.append({'texto': 'Falta la fecha de la falla',
                              'ancla': 'edFechaFalla'})

    for rol in FIRMAS_OBLIGATORIAS.get(reporte['tipo'], ()):
        if rol not in firmas:
            faltantes.append({
                'texto': f"Falta la firma: {ModelFirmas.ETIQUETAS_ROL.get(rol, rol)}",
                'ancla': f"firma-{rol}"})

    return faltantes


@reportes_bp.route('/reportes/<int:reporte_id>/guardar', methods=['POST'])
@requiere_rol(ROL_BIOMEDICO)
def guardar(reporte_id):
    """
    Guardado parcial del módulo. Responde JSON.

    Solo se mandan los campos de la pestaña activa; el modelo hace un UPDATE
    parcial, así que lo que no viaja no se pisa.
    """
    db = None
    try:
        db = get_connection()
        reporte = ModelReporteBase.get_by_id(db, reporte_id)
        if not reporte:
            return jsonify({'ok': False, 'mensaje': 'El reporte no existe'}), 404
        if reporte['estado'] not in EDITABLES:
            return jsonify({'ok': False,
                            'mensaje': 'El reporte ya fue liberado'}), 400

        campos = {}
        if reporte['tipo'] in TIPOS_MOVIMIENTO:
            for campo in ('motivo', 'accesorios', 'destino_externo'):
                if campo in request.form:
                    campos[campo] = request.form.get(campo)
            if 'proveedor_id' in request.form:
                campos['proveedor_id'] = request.form.get('proveedor_id', type=int)
            for campo in ('fecha_retorno_prevista', 'fecha_retorno_real'):
                if campo in request.form:
                    campos[campo] = request.form.get(campo) or None
            padre_nuevo = None
            if reporte['tipo'] == 'entrada' and 'movimiento_padre_id' in request.form:
                padre_nuevo = request.form.get('movimiento_padre_id', type=int)
                campos['movimiento_padre_id'] = padre_nuevo
            if campos:
                ModelMovimiento.guardar(db, reporte_id, **campos)
            # Vincular con la salida que se cierra: en el momento en que se
            # guarda el padre, esa salida deja de aparecer como "sin retorno".
            if padre_nuevo:
                ModelMovimiento.cerrar_salida(db, padre_nuevo)
        elif reporte['tipo'] in TIPOS_TECNOVIGILANCIA:
            for campo in ('clasificacion', 'descripcion', 'involucrados',
                          'acciones_inmediatas'):
                if campo in request.form:
                    campos[campo] = request.form.get(campo)
            for campo in ('fecha_evento', 'fecha_deteccion'):
                if campo in request.form:
                    # Mismo caso que fecha_falla en correctivo: datetime-local
                    # normalizado en la frontera.
                    valor = (request.form.get(campo) or '').strip()
                    campos[campo] = valor.replace('T', ' ') or None
            if campos:
                ModelTecnovigilancia.guardar(db, reporte_id, **campos)
        else:
            for campo in ('descripcion_trabajo', 'observaciones', 'tipo_servicio',
                          'resultado'):
                if campo in request.form:
                    campos[campo] = request.form.get(campo)
            for campo in ('tipo_falla_id', 'causa_demora_id'):
                if campo in request.form:
                    campos[campo] = request.form.get(campo, type=int)
            if 'horas_paro' in request.form:
                campos['horas_paro'] = request.form.get('horas_paro', type=float)
            if 'fecha_falla' in request.form:
                # El input es datetime-local: llega '2026-08-20T14:30', que SQL
                # Server no siempre interpreta igual que 'AAAA-MM-DD HH:MM'. Se
                # normaliza aquí, en la frontera, en vez de confiar en que el
                # driver adivine.
                valor = (request.form.get('fecha_falla') or '').strip()
                campos['fecha_falla'] = valor.replace('T', ' ') or None
            if campos:
                ModelMantenimiento.guardar(db, reporte_id, **campos)

        ModelReporteBase.actualizar_cabecera(
            db, reporte_id,
            area_id      = request.form.get('area_id', type=int),
            tecnico_id   = request.form.get('tecnico_id', type=int),
            fecha_inicio = request.form.get('fecha_inicio') or None)

        # El primer guardado con contenido saca al reporte de borrador, para
        # que aparezca como trabajo en curso en el dashboard.
        if reporte['estado'] == 'borrador' and campos:
            ModelReporteBase.marcar_en_proceso(db, reporte_id, current_user.IDusuario)

        # Los pendientes viajan de vuelta en cada guardado para que la barra de
        # liberación se actualice sola. Antes se calculaban solo al render, así
        # que el botón seguía apagado después de escribir la descripción hasta
        # que alguien recargaba: parecía que el guardado no había servido.
        return jsonify({
            'ok': True,
            'mensaje': 'Guardado',
            'pendientes': _pendientes_para_liberar(
                reporte, ModelFirmas.get_por_reporte(db, reporte_id) or {}, db)})
    finally:
        if db:
            db.close()


@reportes_bp.route('/reportes/<int:reporte_id>/equipos', methods=['POST'])
@requiere_rol(ROL_BIOMEDICO)
def agregar_equipo(reporte_id):
    """Agrega un equipo a un movimiento en captura. Responde JSON."""
    db = None
    try:
        db = get_connection()
        reporte = ModelReporteBase.get_by_id(db, reporte_id)
        if not reporte or reporte['estado'] not in EDITABLES:
            return jsonify({'ok': False, 'mensaje': 'El reporte no admite cambios'}), 400
        if reporte['tipo'] not in TIPOS_MOVIMIENTO:
            return jsonify({'ok': False, 'mensaje': 'Este reporte no admite varios equipos'}), 400

        equipo_id = request.form.get('equipo_id', type=int)
        equipo = ModelInventario.get_by_id(db, equipo_id) if equipo_id else None
        if not equipo:
            return jsonify({'ok': False, 'mensaje': 'El equipo no existe'}), 400

        ok, mensaje = ModelMovimiento.agregar_equipo(db, reporte_id, equipo_id)
        if not ok:
            return jsonify({'ok': False, 'mensaje': mensaje}), 400
        return jsonify({'ok': True, 'equipo': _json_equipo(equipo),
                        'pendientes': _pendientes_para_liberar(
                            reporte, ModelFirmas.get_por_reporte(db, reporte_id) or {}, db)})
    finally:
        if db:
            db.close()


@reportes_bp.route('/reportes/<int:reporte_id>/equipos/<int:equipo_id>/quitar', methods=['POST'])
@requiere_rol(ROL_BIOMEDICO)
def quitar_equipo(reporte_id, equipo_id):
    """Quita un equipo de un movimiento en captura. Responde JSON."""
    db = None
    try:
        db = get_connection()
        reporte = ModelReporteBase.get_by_id(db, reporte_id)
        if not reporte or reporte['estado'] not in EDITABLES:
            return jsonify({'ok': False, 'mensaje': 'El reporte no admite cambios'}), 400

        ok, mensaje = ModelMovimiento.quitar_equipo(db, reporte_id, equipo_id)
        if not ok:
            return jsonify({'ok': False, 'mensaje': mensaje}), 400
        return jsonify({'ok': True,
                        'pendientes': _pendientes_para_liberar(
                            reporte, ModelFirmas.get_por_reporte(db, reporte_id) or {}, db)})
    finally:
        if db:
            db.close()


@reportes_bp.route('/reportes/<int:reporte_id>/adjuntos', methods=['POST'])
@requiere_rol(ROL_BIOMEDICO)
def subir_adjunto(reporte_id):
    """Sube una foto o un archivo al expediente."""
    db = None
    try:
        db = get_connection()
        reporte = ModelReporteBase.get_by_id(db, reporte_id)
        if not reporte or reporte['estado'] not in EDITABLES:
            return jsonify({'ok': False, 'mensaje': 'El reporte no admite cambios'}), 400

        clase = (request.form.get('clase') or '').strip()
        if clase not in CLASES_ADJUNTO:
            return jsonify({'ok': False, 'mensaje': 'Tipo de archivo no válido'}), 400

        ok, resultado = ModelAdjuntos.crear(
            db, reporte_id, clase, request.files.get('archivo'),
            descripcion=request.form.get('descripcion'),
            usuario_id=current_user.IDusuario)
        if not ok:
            return jsonify({'ok': False, 'mensaje': resultado}), 400
        return jsonify({'ok': True, 'id': resultado,
                        'adjunto': _json_adjunto(ModelAdjuntos.get_by_id(db, resultado))})
    finally:
        if db:
            db.close()


@reportes_bp.route('/reportes/adjuntos/<int:adjunto_id>', methods=['POST'])
@requiere_rol(ROL_BIOMEDICO)
def editar_adjunto(adjunto_id):
    """Cambia el pie de foto, si entra al anexo, o la borra."""
    db = None
    try:
        db = get_connection()
        if request.form.get('accion') == 'eliminar':
            ok, mensaje = ModelAdjuntos.eliminar(db, adjunto_id)
            return jsonify({'ok': ok, 'mensaje': mensaje}), (200 if ok else 400)

        incluir = request.form.get('incluir_en_pdf')
        ModelAdjuntos.actualizar(
            db, adjunto_id,
            descripcion=request.form.get('descripcion'),
            incluir_en_pdf=(incluir == '1') if incluir is not None else None)
        return jsonify({'ok': True})
    finally:
        if db:
            db.close()


@reportes_bp.route('/reportes/<int:reporte_id>/lineas', methods=['POST'])
@requiere_rol(ROL_BIOMEDICO)
def agregar_linea(reporte_id):
    """Agrega un renglón de refacción o consumible."""
    db = None
    try:
        db = get_connection()
        reporte = ModelReporteBase.get_by_id(db, reporte_id)
        if not reporte or reporte['estado'] not in EDITABLES:
            return jsonify({'ok': False, 'mensaje': 'El reporte no admite cambios'}), 400

        ok, resultado = ModelLineas.crear(
            db, reporte_id,
            descripcion     = request.form.get('descripcion'),
            cantidad        = request.form.get('cantidad') or 1,
            precio_unitario = request.form.get('precio_unitario'),
            clase           = request.form.get('clase') or 'refaccion')
        if not ok:
            return jsonify({'ok': False, 'mensaje': resultado}), 400

        totales = ModelLineas.total(db, reporte_id)
        creada = next((l for l in ModelLineas.get_por_reporte(db, reporte_id)
                       if l['id'] == resultado), None)
        return jsonify({'ok': True, 'id': resultado,
                        'linea': _json_linea(creada),
                        'total': str(totales['total']),
                        'sin_costear': totales['sin_costear']})
    finally:
        if db:
            db.close()


@reportes_bp.route('/reportes/lineas/<int:linea_id>/eliminar', methods=['POST'])
@requiere_rol(ROL_BIOMEDICO)
def eliminar_linea(linea_id):
    db = None
    try:
        db = get_connection()
        reporte_id = request.form.get('reporte_id', type=int)
        ok = ModelLineas.eliminar(db, linea_id)
        # El total se recalcula aquí y no en el navegador: sumar en JavaScript
        # los importes ya pintados vuelve a introducir el redondeo que
        # `centavos()` acaba de quitar.
        totales = ModelLineas.total(db, reporte_id) if (ok and reporte_id) else None
        return jsonify({'ok': ok,
                        'total': str(totales['total']) if totales else None,
                        'sin_costear': totales['sin_costear'] if totales else None})
    finally:
        if db:
            db.close()


@reportes_bp.route('/reportes/<int:reporte_id>/notas', methods=['POST'])
@requiere_rol(ROL_BIOMEDICO)
def agregar_nota(reporte_id):
    """Agrega una anotación al expediente."""
    db = None
    try:
        db = get_connection()
        ok, resultado = ModelNotas.crear(
            db, reporte_id, request.form.get('texto'),
            usuario_id=current_user.IDusuario,
            incluir_en_pdf=request.form.get('incluir_en_pdf') == '1')
        if not ok:
            return jsonify({'ok': False, 'mensaje': resultado}), 400
        creada = next((n for n in ModelNotas.get_por_reporte(db, reporte_id)
                       if n['id'] == resultado), None)
        return jsonify({'ok': True, 'id': resultado, 'nota': _json_nota(creada)})
    finally:
        if db:
            db.close()


@reportes_bp.route('/reportes/<int:reporte_id>/firmar', methods=['POST'])
@requiere_rol(ROL_BIOMEDICO)
def firmar(reporte_id):
    """
    Registra una firma. Es irrevocable: una vez capturada no se puede cambiar.

    La garantía la da el UNIQUE (reporte_id, rol) de la tabla, no un `if` de la
    aplicación — así dos peticiones simultáneas tampoco pueden colarse.
    """
    db = None
    try:
        db = get_connection()
        reporte = ModelReporteBase.get_by_id(db, reporte_id)
        if not reporte or reporte['estado'] not in EDITABLES:
            return jsonify({'ok': False, 'mensaje': 'El reporte no admite cambios'}), 400

        rol = (request.form.get('rol') or '').strip()
        if rol not in ModelFirmas.ROLES:
            return jsonify({'ok': False, 'mensaje': 'Rol de firma no válido'}), 400

        nombre = (request.form.get('nombre') or '').strip()[:150]
        if not nombre:
            return jsonify({'ok': False, 'mensaje': 'Escribe el nombre de quien firma'}), 400

        try:
            imagen_rel = ModelFirmas.guardar_firma_png(request.form.get('firma', ''))
        except ValueError as e:
            return jsonify({'ok': False, 'mensaje': str(e)}), 400

        ok, mensaje = ModelFirmas.crear(
            db, reporte_id=reporte_id, rol=rol, nombre=nombre,
            cargo=(request.form.get('cargo') or '').strip()[:150] or None,
            imagen_rel=imagen_rel, usuario_id=current_user.IDusuario)
        if not ok:
            ModelInventario.eliminar_archivo_fisico(imagen_rel)
            return jsonify({'ok': False, 'mensaje': mensaje}), 400

        ModelReporteBase.registrar_evento(
            db, reporte_id, 'firmado',
            f"{ModelFirmas.ETIQUETAS_ROL.get(rol, rol)}: {nombre}",
            current_user.IDusuario)

        firmas = ModelFirmas.get_por_reporte(db, reporte_id) or {}
        firma = firmas.get(rol) or {}
        return jsonify({
            'ok': True,
            'mensaje': mensaje,
            'firma': {
                'rol':    rol,
                'nombre': firma.get('nombre') or nombre,
                'cargo':  firma.get('cargo') or '',
                'fecha':  firma['fecha'].strftime('%d/%m/%Y %H:%M') if firma.get('fecha') else '',
                'url':    url_for('static', filename='uploads/' + (firma.get('imagen') or '')),
            },
            'pendientes': _pendientes_para_liberar(reporte, firmas, db)})
    finally:
        if db:
            db.close()


@reportes_bp.route('/reportes/<int:reporte_id>/liberar', methods=['POST'])
@requiere_rol(ROL_BIOMEDICO)
def liberar(reporte_id):
    """
    Cierra el trabajo y congela el PDF.

    Se generan DOS archivos: el completo con anexos y la variante de solo la
    hoja del reporte. Los dos se congelan aquí en vez de producirse a demanda,
    para poder elegir qué imprimir sin re-renderizar nada — que es lo que haría
    que el hash guardado dejara de significar algo.
    """
    db = None
    try:
        db = get_connection()
        reporte = ModelReporteBase.get_by_id(db, reporte_id)
        if not reporte:
            return jsonify({'ok': False, 'mensaje': 'El reporte no existe'}), 404
        if reporte['estado'] not in EDITABLES:
            return jsonify({'ok': False, 'mensaje': 'El reporte ya fue liberado'}), 400

        firmas = ModelFirmas.get_por_reporte(db, reporte_id) or {}
        pendientes = _pendientes_para_liberar(reporte, firmas, db)
        if pendientes:
            return jsonify({'ok': False,
                            'mensaje': 'Falta capturar antes de liberar',
                            'pendientes': pendientes}), 400

        # Las horas de paro se recalculan aquí si nadie las tocó a mano: es el
        # valor definitivo del antecedente, y no tiene sentido pedirle a
        # alguien que reste horas cuando ya se sabe la fecha de la falla y la
        # de ahora mismo. Si ya hay un valor —porque el equipo llevaba tiempo
        # caído antes de registrarse, o porque se corrigió a mano— se respeta.
        if reporte['tipo'] == 'correctivo':
            detalle = ModelMantenimiento.get(db, reporte_id) or {}
            if detalle.get('fecha_falla') and detalle.get('horas_paro') is None:
                ModelMantenimiento.guardar(
                    db, reporte_id,
                    horas_paro=ModelMantenimiento.horas_desde_falla(detalle['fecha_falla']))

        equipo = (ModelInventario.get_by_id(db, reporte['equipo_id'])
                  if reporte.get('equipo_id') else None)

        # El PDF se arma SIEMPRE con costos: es el registro del departamento.
        # Quién puede verlos se decide al servir el archivo, no al congelarlo.
        plantilla, contexto = reporte_contexto.para(db, reporte, equipo, ver_costos=True)
        if not plantilla:
            return jsonify({'ok': False,
                            'mensaje': 'Este tipo de reporte aún no tiene formato'}), 400

        folio = reporte['folio']
        _, sha_completo = reporte_pdf.generar_pdf(
            plantilla, contexto, reporte_pdf.ruta_pdf(folio))
        reporte_pdf.generar_pdf(
            plantilla, dict(contexto, fotos_anexo=[]),
            reporte_pdf.ruta_pdf(folio, '-reporte'))

        ok, mensaje = ModelReporteBase.liberar(
            db, reporte_id, current_user.IDusuario,
            f"reportes/{folio}.pdf", f"reportes/{folio}-reporte.pdf",
            sha_completo)
        if not ok:
            return jsonify({'ok': False, 'mensaje': mensaje}), 400

        # Empuja la fecha en el programa para que el dashboard de "qué me toca"
        # deje de marcar vencido lo que se acaba de hacer. Solo aplica al
        # mantenimiento: una entrada o salida no es un servicio, y pushearle
        # la fecha de "próximo mantenimiento" a un equipo solo porque salió
        # del hospital sería un efecto secundario que nadie pidió.
        if reporte.get('equipo_id') and reporte['tipo'] in TIPOS_MANTENIMIENTO:
            from datetime import date
            ModelMantenimiento.sincronizar_programa(
                db, reporte['equipo_id'], date.today())

        return jsonify({'ok': True, 'mensaje': mensaje,
                        'url': url_for('reportes.ver', reporte_id=reporte_id)})
    finally:
        if db:
            db.close()


# ── API para los formularios ───────────────────────────────────

@reportes_bp.route('/reportes/api/equipo')
@requiere_rol(ROL_BIOMEDICO)
def api_equipo():
    """
    Autocompletado de equipo por número de inventario o de serie.

    Es propio y no el /Catalogo/autocomplete que ya existe: aquel es una ruta
    pública (la que abre un chip NFC) y devuelve resultados de catálogo, no los
    campos que el formulario necesita para autorrellenarse.

    Con `?exacto=1` devuelve un solo equipo con todos sus campos, que es lo que
    se pide al elegir una sugerencia.
    """
    termino = (request.args.get('q') or '').strip()
    if len(termino) < 2:
        return jsonify([])

    db = None
    try:
        db = get_connection()
        cursor = db.cursor()

        if request.args.get('exacto') == '1':
            cursor.execute(
                "SELECT TOP 1 id FROM HospitalGalenia.dbo.InventarioEquipos "
                "WHERE numero_inventario = ? OR numero_serie = ?",
                (termino, termino))
            fila = cursor.fetchone()
            cursor.close()
            if not fila:
                return jsonify({}), 404
            return jsonify(ModelInventario.get_by_id(db, fila[0]) or {})

        patron = f"%{termino}%"
        cursor.execute(
            "SELECT TOP 10 id, numero_inventario, numero_serie, equipo_unidad, "
            "       marca, modelo, area "
            "FROM HospitalGalenia.dbo.InventarioEquipos "
            "WHERE numero_inventario LIKE ? OR numero_serie LIKE ? "
            "   OR equipo_unidad LIKE ? "
            "ORDER BY CASE WHEN numero_inventario = ? THEN 0 ELSE 1 END, "
            "         numero_inventario",
            (patron, patron, patron, termino))
        columnas = [c[0] for c in cursor.description]
        resultados = [dict(zip(columnas, f)) for f in cursor.fetchall()]
        cursor.close()
        return jsonify(resultados)

    finally:
        if db:
            db.close()


@reportes_bp.route('/reportes/<int:reporte_id>/cancelar', methods=['POST'])
@requiere_rol(ROL_BIOMEDICO)
def cancelar(reporte_id):
    """Cancela un reporte en curso. No se borra: se conserva con su folio."""
    db = None
    try:
        db = get_connection()
        motivo = (request.form.get('motivo') or '').strip()
        ok = ModelReporteBase.cancelar(
            db, reporte_id, current_user.IDusuario, motivo)
        if not ok:
            return jsonify({'ok': False,
                            'mensaje': 'Solo se puede cancelar un reporte en curso'}), 400
        return jsonify({'ok': True, 'mensaje': 'Reporte cancelado'})
    finally:
        if db:
            db.close()


# ── Estadísticas y expediente ────────────────────────────────────

@reportes_bp.route('/reportes/estadisticas')
@requiere_rol(ROL_USUARIO)
def estadisticas():
    """
    Dashboard de estadísticas sobre los reportes ya liberados.

    Visible para cualquier rol —igual que el Centro de Reportes—, pero las
    cifras de costo se ocultan para `Usuario` con el mismo criterio de
    siempre (`ver_costos`): el resto del dashboard (MTTR, causas de demora,
    tipos de falla, equipos reincidentes) no es información financiera.
    """
    db = None
    try:
        db = get_connection()
        meses = request.args.get('meses', 12, type=int)
        if meses not in (6, 12, 24):
            meses = 12
        ver_costos = _puede_ver_costos()

        costo_prev_vs_corr = ModelKPIs.costo_preventivo_vs_correctivo(db, meses=meses) if ver_costos else []
        maximo_apilado = max(
            (p['preventivo'] + p['correctivo'] for p in costo_prev_vs_corr), default=1)

        return render_template(
            'reportes/estadisticas.html',
            meses           = meses,
            ver_costos      = ver_costos,
            snapshot        = ModelKPIs.resumen_snapshot(db, meses),
            mttr            = ModelKPIs.mttr_horas(db, meses),
            mtbf            = ModelKPIs.mtbf_dias(db),
            costo_periodo   = ModelKPIs.costo_por_periodo(db, meses) if ver_costos else [],
            costo_equipo    = ModelKPIs.costo_por_equipo(db, top=8, meses=meses) if ver_costos else [],
            costo_prev_vs_corr = costo_prev_vs_corr,
            maximo_apilado  = maximo_apilado,
            costo_clase     = ModelKPIs.costo_por_clase(db, meses=meses) if ver_costos else [],
            causas_demora   = ModelKPIs.causas_demora_frecuentes(db, top=6),
            tipos_falla     = ModelKPIs.tipos_falla_frecuentes(db, top=6),
            reincidentes    = ModelKPIs.equipos_reincidentes(db, top=6, meses=meses),
        )
    finally:
        if db:
            db.close()


@reportes_bp.route('/reportes/equipo/<int:equipo_id>')
@requiere_rol(ROL_USUARIO)
def expediente(equipo_id):
    """
    Expediente de un equipo: línea de vida con todos sus reportes, de
    cualquier tipo, en orden cronológico. Responde "¿qué le ha pasado a este
    equipo?" — la pregunta que hoy solo contestaba una lista filtrada del
    Centro de Reportes sin el hilo cronológico entre tipos.
    """
    db = None
    try:
        db = get_connection()
        equipo = ModelInventario.get_by_id(db, equipo_id)
        if not equipo:
            abort(404)

        ver_costos = _puede_ver_costos()
        reportes = ModelKPIs.expediente_equipo(db, equipo_id)
        if not ver_costos:
            for r in reportes:
                r['costo'] = None

        return render_template(
            'reportes/expediente.html',
            equipo    = equipo,
            reportes  = reportes,
            etiq_tipo = ETIQUETAS_TIPO,
            etiq_est  = ETIQUETAS_ESTADO,
            ver_costos = ver_costos,
        )
    finally:
        if db:
            db.close()
