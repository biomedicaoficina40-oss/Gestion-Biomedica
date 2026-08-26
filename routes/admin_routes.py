from flask import (Blueprint, render_template, request, redirect, url_for, flash,
                   current_app, send_file, jsonify)
from flask_login import current_user
from database.db import get_connection
from models.entities.decorators import (
    requiere_rol, rol_canonico, tiene_rol,
    ROL_USUARIO, ROL_BIOMEDICO, ROL_ADMIN,
)
from datetime import date, datetime
import os
from models.ModelInventario import ModelInventario
from models.model_recursos import ModelRecursos
from models.ModelReportes import ModelReportes
from models.ModelFirmas import ModelFirmas
from models.ModelUsuarios import ModelUsuarios
from models.entities.User import User
from services import reporte_pdf

admin_bp = Blueprint('admin', __name__)

# El motor de PDF y sus utilidades viven en services/reporte_pdf.py desde que
# dejaron de ser exclusivos del acta de alta: los cinco tipos de reporte nuevos
# los reusan. Se reexportan con los nombres privados que ya usaba el resto del
# archivo, para que mover el código no obligara a tocar las rutas.
_STATIC_DIR   = reporte_pdf.STATIC_DIR
_UPLOADS_DIR  = reporte_pdf.UPLOADS_DIR
_REPORTES_DIR = reporte_pdf.REPORTES_DIR

_limitar          = reporte_pdf.limitar
_fecha_es         = reporte_pdf.fecha_es
_fecha_larga_es   = reporte_pdf.fecha_larga_es
_uri_estatica     = reporte_pdf.uri_estatica
_ruta_pdf_reporte = reporte_pdf.ruta_pdf


# Largo máximo de cada campo de captura. Es la única fuente de verdad:
# el formulario recibe estos números para pintar los `maxlength` y el POST
# los aplica de nuevo en el servidor. Los campos de identificación usan el
# largo real de su columna en InventarioEquipos; los de texto libre usan el
# largo que cabe sin romper el bloque correspondiente del PDF.
LIMITES = {
    'equipo_unidad':     200,
    'marca':             100,
    'modelo':            150,
    'numero_serie':      100,
    'area':              100,
    'departamento':      100,
    'propiedad':         100,
    'numero_inventario':  50,
    'observaciones':     600,
    'obs_reporte':       600,
    'acc_descripcion':    90,
    'firma_nombre':      150,
    'firma_cargo':       150,
}
MAX_ACCESORIOS = 25


# ── Helpers del acta de alta ───────────────────────────────────
# Lo genérico (fechas, límites, URIs, paginación del PDF) está en
# services/reporte_pdf.py. Aquí solo queda lo que es propio del alta.

def _asegurar_reporte_alta(db, equipo_id, equipo=None):
    """
    Devuelve el reporte de alta del equipo, creándolo si no existe.

    La mayoría del inventario se cargó directo en la base de datos, antes
    de que existiera este módulo, así que esos equipos nunca tuvieron acta.
    Para que el botón de "Reporte de alta" sirva en todos, aquí se levanta
    una **regularización**: un reporte real, con folio de su propia serie
    (RPT-REG-), cuyo snapshot se arma con lo que hoy tiene el equipo en la
    BD. Lo que no existe se queda en blanco para llenarse a mano.

    A partir de ese momento se comporta igual que cualquier otra acta: se
    congela, se firma y ya no cambia.

    Devuelve (reporte | None, creado: bool).
    """
    reportes = ModelReportes.get_por_equipo(db, equipo_id, tipo='alta')
    if reportes:
        return reportes[0], False

    equipo = equipo or ModelInventario.get_by_id(db, equipo_id)
    if not equipo:
        return None, False

    # El snapshot es la ficha tal como está hoy. Los campos que solo existen
    # en un alta capturada por el sistema (motivo, empresa, accesorios,
    # observaciones del reporte) van vacíos a propósito.
    datos = {
        **equipo,
        'motivo_ingreso':        None,
        'empresa_responsable':   None,
        'accesorios':            [],
        'observaciones_reporte': None,
        # Marca el acta como retroactiva: se imprime una leyenda para que
        # nadie lea la fecha del documento como fecha de recepción.
        'regularizado':          True,
    }

    ok, reporte_id, folio = ModelReportes.crear_reporte(
        db            = db,
        tipo          = 'alta',
        equipo_id     = equipo_id,
        usuario_id    = current_user.IDusuario,
        datos_equipo  = datos,
        prefijo_folio = ModelReportes.PREFIJO_REGULARIZACION,
    )
    if not ok:
        return None, False

    current_app.logger.info(
        f"Reporte de alta regularizado {folio} para el equipo {equipo_id}."
    )
    return ModelReportes.get_by_id(db, reporte_id), True


def _contexto_reporte(reporte, equipo=None, firmas=None):
    """
    Arma el contexto del PDF a partir del SNAPSHOT del reporte.

    El acta se imprime con los datos del día del alta, no con los del
    equipo hoy; `equipo` solo rellena huecos de reportes viejos cuyo
    snapshot no traía todos los campos.

    Las firmas son la excepción: no van en el snapshot porque se agregan
    después, así que llegan aparte y se resuelven al momento de imprimir.
    """
    datos = reporte.get('datos') or {}
    eq = {**(equipo or {}), **datos}

    for campo in ('fecha_adquisicion', 'fecha_fabricacion', 'fecha_fin_garantia'):
        eq[campo] = _fecha_es(eq.get(campo))
    eq['accesorios'] = ModelReportes.normalizar_lista(eq.get('accesorios'))

    imagen_url = None
    if eq.get('imagen'):
        imagen_url = _uri_estatica('uploads', *str(eq['imagen']).split('/'))

    # Las firmas se pasan ya resueltas: URI del trazo y fecha formateada,
    # para que la plantilla no tenga que saber de rutas ni de formatos.
    firmas_ctx = {}
    for rol, firma in (firmas or {}).items():
        url = _uri_estatica('uploads', *str(firma.get('imagen') or '').split('/'))
        if not url:
            continue
        firmas_ctx[rol] = {
            'nombre':    firma.get('nombre'),
            'cargo':     firma.get('cargo'),
            'url':       url,
            'fecha_txt': _fecha_es(firma.get('fecha'), '%d/%m/%Y'),
        }

    fecha = reporte.get('fecha')
    # Un acta retroactiva no documenta una recepción: documenta lo que ya
    # había en el inventario. Los huecos van en blanco para llenarse con
    # pluma, en vez del guion que se usa cuando el dato sí se capturó y
    # simplemente no existe.
    regularizado = bool(eq.get('regularizado'))

    return dict(
        eq           = eq,
        folio        = reporte.get('folio'),
        fecha_txt    = _fecha_larga_es(fecha),
        anio         = fecha.year if hasattr(fecha, 'year') else None,
        imagen_url   = imagen_url,
        logo_url     = _uri_estatica('img', 'Logo-Galenia.png'),
        firmas       = firmas_ctx,
        regularizado = regularizado,
        ph           = '' if regularizado else '—',
    )


def _guardar_firmas_del_form(db, reporte_id):
    """
    Registra las firmas que hayan venido en el formulario de alta.

    Las dos son opcionales: un rol sin nombre o sin trazo simplemente se
    salta y queda pendiente. Una firma que falle no aborta el alta — se
    deja en el log y el reporte nace pendiente de esa parte.

    Devuelve las firmas ya registradas, listas para el PDF.
    """
    for rol in ModelFirmas.ROLES_ALTA:
        nombre = _limitar(request.form.get(f'firma_{rol}_nombre', ''), LIMITES['firma_nombre'])
        trazo  = request.form.get(f'firma_{rol}_img', '')
        if not nombre or not trazo:
            continue
        try:
            imagen_rel = ModelFirmas.guardar_firma_png(trazo)
            ok, mensaje = ModelFirmas.crear(
                db,
                reporte_id = reporte_id,
                rol        = rol,
                nombre     = nombre,
                cargo      = _limitar(request.form.get(f'firma_{rol}_cargo', ''),
                                      LIMITES['firma_cargo']),
                imagen_rel = imagen_rel,
                usuario_id = current_user.IDusuario,
            )
            if not ok:
                ModelInventario.eliminar_archivo_fisico(imagen_rel)
                current_app.logger.warning(
                    f"Firma {rol} del reporte {reporte_id} no se registró: {mensaje}"
                )
        except Exception as ex:
            current_app.logger.error(
                f"Error guardando firma {rol} del reporte {reporte_id}: {ex}"
            )

    return ModelFirmas.get_por_reporte(db, reporte_id)


def _generar_pdf_reporte(db, reporte, equipo=None, firmas=None):
    """
    Renderiza el acta de alta, la congela en disco y registra la ruta.

    La maquetacion en si (las cuatro pasadas, el corte equilibrado y el
    anclado de firmas al pie) vive en services/reporte_pdf.py. Aqui solo
    queda lo propio del alta: armar su contexto y actualizar el reporte.

    Se llama al dar de alta el equipo y cada vez que se registra una firma.
    Fuera de eso el PDF solo se lee del disco.
    """
    contexto = _contexto_reporte(reporte, equipo, firmas)
    destino, _digest = reporte_pdf.generar_pdf(
        'admin/Reportes_PDF/reporte_alta.html',
        contexto,
        reporte_pdf.ruta_pdf(reporte['folio']),
    )

    ModelReportes.actualizar_pdf(
        db, reporte['id'], f"reportes/{os.path.basename(destino)}"
    )
    return destino


# ── Gestión de Inventario ──────────────────────────────────────

@admin_bp.route('/inventario')
@requiere_rol(ROL_USUARIO)
def ver_inventario():
    q         = request.args.get('q', '').strip()
    depto     = request.args.get('depto', '')
    estado    = request.args.get('estado', '')
    marca     = request.args.get('marca', '')
    propiedad = request.args.get('propiedad', '')
    sort      = request.args.get('sort', '')
    dir       = request.args.get('dir', 'asc')
    page      = request.args.get('page', 1, type=int)
    # agrupar=0 desactiva el orden "operativos primero" (activo por defecto)
    agrupar   = request.args.get('agrupar', '1') != '0'
    per_page  = 15
    db = get_connection()
    equipos, total = ModelInventario.get_inventario(db, q, depto, estado, marca, propiedad,
                                                    sort, dir, page, per_page,
                                                    agrupar_estado=agrupar)
    stats          = ModelInventario.get_stats(db)
    marcas         = ModelInventario.get_marcas(db)
    departamentos  = ModelInventario.get_departamentos(db)
    propiedades    = ModelInventario.get_propiedades(db)
    db.close()

    ctx = dict(
        equipos=equipos, total=total, stats=stats,
        marcas=marcas, departamentos=departamentos, propiedades=propiedades,
        q=q, depto=depto, estado=estado, marca=marca, propiedad=propiedad,
        sort=sort, dir=dir, page=page, per_page=per_page,
        agrupar=agrupar, agrupar_param=None if agrupar else '0',
        today=date.today()
    )

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render_template('admin/inventario_fragment.html', **ctx)

    return render_template('admin/inventario.html', **ctx)


@admin_bp.route('/inventario/nfc')
@requiere_rol(ROL_USUARIO)
def panel_nfc():
    """
    Panel de control de equipos con chip NFC: checklist de imagen,
    guía rápida, manual, ficha técnica, capacitación y registro de
    mantenimiento, con enlaces directos para completar lo que falte.
    """
    db      = get_connection()
    equipos = ModelInventario.get_equipos_nfc(db)
    db.close()

    # Los equipos con información incompleta suben primero: es un panel
    # para "alimentar" datos, así lo que falta queda a la vista de inmediato.
    equipos.sort(key=lambda e: (e['items_completos'], e['numero_inventario']))

    contadores = {
        'total':            len(equipos),
        'completos':        sum(1 for e in equipos if e['items_completos'] == e['total_items']),
        'incompletos':      sum(1 for e in equipos if e['items_completos'] <  e['total_items']),
        'mant_pendiente':   sum(1 for e in equipos if e['estado_mant'] != 'al_dia'),
        'sin_imagen':       sum(1 for e in equipos if not e['tiene_imagen']),
        'sin_guia':         sum(1 for e in equipos if not e['tiene_guia']),
        'sin_manual':       sum(1 for e in equipos if not e['tiene_manual']),
        'sin_ficha':        sum(1 for e in equipos if not e['tiene_ficha']),
        'sin_capacitacion': sum(1 for e in equipos if not e['tiene_capacitacion']),
    }

    return render_template('admin/panel_nfc.html',
        equipos=equipos,
        contadores=contadores,
    )


@admin_bp.route('/inventario/agregar', methods=['GET', 'POST'])
@requiere_rol(ROL_BIOMEDICO)
def agregar_equipo():
    db = None
    try:
        db = get_connection()

        if request.method == 'GET':
            # ── Datos para selects ──────────────────────────────
            departamentos = ModelInventario.get_departamentos(db)
            propiedades   = ModelInventario.get_propiedades(db)
            areas = ModelInventario.get_areas(db)

            # ── Datos para autocomplete client-side ─────────────
            # Una sola consulta, sin peticiones extra desde el browser
            cursor = db.cursor()
            cursor.execute("""
                SELECT DISTINCT equipo_unidad, marca, modelo
                FROM HospitalGalenia.dbo.InventarioEquipos
                WHERE equipo_unidad IS NOT NULL
                  AND marca         IS NOT NULL
                  AND modelo        IS NOT NULL
                ORDER BY equipo_unidad
            """)
            rows = cursor.fetchall()
            cursor.close()

            equipos_ac = sorted(set(
                r[0].strip() for r in rows if r[0] and r[0].strip()
            ))
            marcas_ac  = sorted(set(
                r[1].strip() for r in rows if r[1] and r[1].strip()
            ))
            # modelos agrupados por marca para filtrado en JS
            modelos_ac = {}
            for r in rows:
                marca  = (r[1] or '').strip()
                modelo = (r[2] or '').strip()
                if marca and modelo:
                    modelos_ac.setdefault(marca, set()).add(modelo)
            # convertir sets a listas ordenadas (JSON no acepta sets)
            modelos_ac = {m: sorted(v) for m, v in modelos_ac.items()}

            # ── Números sugeridos por prefijo ───────────────────
            num_eqme = ModelInventario.generar_numero_inventario(db, 'EQ-ME')
            num_amco = ModelInventario.generar_numero_inventario(db, 'AM-CO')

            return render_template('admin/agregar_equipo.html',
                departamentos = departamentos,
                propiedades   = propiedades,
                areas         = areas,
                equipos_ac    = equipos_ac,
                marcas_ac     = marcas_ac,
                modelos_ac    = modelos_ac,
                num_eqme      = num_eqme,
                num_amco      = num_amco,
                prefijos       = ['EQ-ME', 'AM-CO'],
                limites        = LIMITES,
                max_accesorios = MAX_ACCESORIOS,
                # Quien da de alta suele ser quien entrega: se propone su
                # nombre, pero sigue siendo editable.
                firma_entrega_nombre = ' '.join(filter(None, [
                    current_user.NombreUsuario, current_user.Apellido
                ])).strip(),
            )

        # ── POST ────────────────────────────────────────────────
        # Validar CSRF ya lo maneja Flask-WTF automáticamente

        # 1 — Recoger y sanear campos
        # _limitar recorta al mismo largo que declara el formulario: el
        # maxlength del HTML no protege de un POST armado a mano.
        prefijo          = request.form.get('prefijo', '').strip()
        equipo_unidad    = _limitar(request.form.get('equipo_unidad', ''), LIMITES['equipo_unidad'])
        marca            = _limitar(request.form.get('marca', ''),         LIMITES['marca'])
        modelo           = _limitar(request.form.get('modelo', ''),        LIMITES['modelo'])
        numero_serie     = _limitar(request.form.get('numero_serie', ''),  LIMITES['numero_serie'])
        estado           = request.form.get('estado', '').strip()
        observaciones    = _limitar(request.form.get('observaciones', ''), LIMITES['observaciones'])
        # ── Campos solo para el reporte (no van a la BD principal) ──
        motivo_ingreso       = request.form.get('motivo_ingreso', '').strip()
        empresa_responsable  = request.form.get('empresa_responsable', '').strip()
        obs_reporte          = _limitar(request.form.get('obs_reporte', ''), LIMITES['obs_reporte'])

        # Accesorios — vienen como listas paralelas del formulario
        acc_desc      = request.form.getlist('acc_descripcion')
        acc_cant      = request.form.getlist('acc_cantidad')
        acc_condicion = request.form.getlist('acc_condicion')
        accesorios = [
            {
                'descripcion': _limitar(d, LIMITES['acc_descripcion']),
                'cantidad':    c.strip()[:3],
                'condicion':   co.strip()[:20],
            }
            for d, c, co in zip(acc_desc, acc_cant, acc_condicion)
            if d.strip()
        ][:MAX_ACCESORIOS]

        # Departamento: si eligió "otro" usar el campo libre
        departamento = request.form.get('departamento', '').strip()
        if departamento == '__otro__':
            departamento = request.form.get('departamento_nuevo', '')
        departamento = _limitar(departamento, LIMITES['departamento'])

        area = request.form.get('area', '').strip()
        if area == '__otro__':
            area = request.form.get('area_nueva', '')
        area = _limitar(area, LIMITES['area'])

        # Propiedad: igual
        propiedad = request.form.get('propiedad', '').strip()
        if propiedad == '__otro__':
            propiedad = request.form.get('propiedad_nueva', '')
        propiedad = _limitar(propiedad, LIMITES['propiedad'])

        # Fechas — pueden venir vacías
        fecha_adquisicion  = request.form.get('fecha_adquisicion')  or None
        fecha_fabricacion  = request.form.get('fecha_fabricacion')  or None
        fecha_fin_garantia = request.form.get('fecha_fin_garantia') or None

        # 2 — Validaciones del lado servidor
        errores = []
        usar_manual = request.form.get('numero_manual_activo') == '1'
        numero_manual = _limitar(
            request.form.get('numero_inventario_manual', ''), LIMITES['numero_inventario']
        )

        if usar_manual:
            if not numero_manual:
                errores.append('Escribe el número de inventario personalizado.')
        else:
            if prefijo not in ('EQ-ME', 'AM-CO'):
                errores.append('Prefijo de inventario inválido.')
        if not equipo_unidad:
            errores.append('El nombre del equipo es obligatorio.')
        if not departamento:
            errores.append('El departamento es obligatorio.')
        if estado not in ('Operativo', 'Mantenimiento', 'Fuera de Servicio'):
            errores.append('Estado inválido.')

        if errores:
            for e in errores:
                flash(e, 'error')
            return redirect(url_for('admin.agregar_equipo'))

        # 3 — Número de inventario (automático o manual)
        if usar_manual:
            numero_inventario = numero_manual
            # Verificar que no exista ya
            cursor = db.cursor()
            cursor.execute(
                f"SELECT COUNT(*) FROM {ModelInventario.TABLE} WHERE numero_inventario = ?",
                (numero_inventario,)
            )
            existe = cursor.fetchone()[0]
            cursor.close()
            if existe:
                flash(f'El número {numero_inventario} ya existe en el inventario.', 'error')
                return redirect(url_for('admin.agregar_equipo'))
        else:
            numero_inventario = ModelInventario.generar_numero_inventario(db, prefijo)
            if not numero_inventario:
                flash('Error al generar el número de inventario.', 'error')
                return redirect(url_for('admin.agregar_equipo'))

        # 4 — Manejar imagen (opcional)
        # imagen_nueva distingue un archivo recién subido (limpiar si falla la
        # creación) de uno reutilizado de otro equipo del mismo modelo (nunca
        # borrar: pertenece también a esos otros equipos).
        imagen_path  = None
        imagen_nueva = False
        imagen_file  = request.files.get('imagen')
        if imagen_file and imagen_file.filename:
            try:
                imagen_path  = ModelInventario.guardar_imagen(imagen_file)
                imagen_nueva = True
            except ValueError as e:
                flash(str(e), 'error')
                return redirect(url_for('admin.agregar_equipo'))
        elif modelo:
            # Sin imagen propia: reutilizar la de otro equipo del mismo
            # modelo si ya existe, para no forzar a resubirla.
            imagen_path = ModelInventario.buscar_imagen_por_modelo(db, modelo)

        # 5 — Armar datos y crear equipo
        datos = {
            'equipo_unidad':    equipo_unidad,
            'marca':            marca            or None,
            'modelo':           modelo           or None,
            'numero_serie':     numero_serie     or None,
            'numero_inventario': numero_inventario,
            'area':             area             or None,
            'departamento':     departamento,
            'estado':           estado,
            'propiedad':        propiedad        or None,
            'observaciones':    observaciones    or None,
            'fecha_adquisicion':  fecha_adquisicion,
            'fecha_fabricacion':  fecha_fabricacion,
            'fecha_fin_garantia': fecha_fin_garantia,
            'imagen':           imagen_path,
        }

        equipo_id = ModelInventario.crear(db, datos)
        if not equipo_id:
            # Si falló y la imagen era una subida nueva (no reutilizada
            # de otro equipo), limpiarla del disco
            if imagen_path and imagen_nueva:
                ModelInventario.eliminar_archivo_fisico(imagen_path)
            flash('Error al registrar el equipo. Intenta de nuevo.', 'error')
            return redirect(url_for('admin.agregar_equipo'))

        # 6 — Copiar recursos (manuales, fichas, etc.) de otros equipos del
        # mismo modelo, para no obligar a resubirlos en cada alta.
        recursos_copiados = 0
        if modelo:
            recursos_copiados = ModelRecursos.copiar_recursos_por_modelo(db, modelo, equipo_id)

        # 7 — Crear reporte de alta
        equipo_nuevo = ModelInventario.get_by_id(db, equipo_id)

        datos_reporte = {
            'motivo_ingreso':      motivo_ingreso or None,
            'empresa_responsable': empresa_responsable or None,
            'accesorios':          accesorios,
            'observaciones_reporte': obs_reporte or None,
        }

        ok, reporte_id, folio = ModelReportes.crear_reporte(
            db           = db,
            tipo         = 'alta',
            equipo_id    = equipo_id,
            usuario_id   = current_user.IDusuario,
            datos_equipo = {**equipo_nuevo, **datos_reporte},
            archivo_pdf  = None
        )

        if not ok:
            current_app.logger.warning(
                f"Equipo {equipo_id} creado pero falló el reporte de alta."
            )
        else:
            # 8 — Firmas capturadas en el momento del alta (ambas opcionales).
            # Lo que no se firme aquí queda pendiente y se cierra después
            # desde el visor del reporte.
            firmas_guardadas = _guardar_firmas_del_form(db, reporte_id)

            # 9 — Congelar el PDF ahora, con los datos de este momento.
            # Si falla no se cancela el alta: el reporte queda registrado y
            # el PDF se genera la primera vez que alguien lo abra.
            try:
                reporte = ModelReportes.get_by_id(db, reporte_id)
                _generar_pdf_reporte(db, reporte, equipo_nuevo, firmas_guardadas)
            except Exception as ex_pdf:
                current_app.logger.error(
                    f"Reporte {folio} creado pero falló el PDF: {ex_pdf}"
                )

        mensaje = f'Equipo {numero_inventario} registrado correctamente.'
        reutilizado = []
        if imagen_path and not imagen_nueva:
            reutilizado.append('imagen')
        if recursos_copiados:
            reutilizado.append(
                f'{recursos_copiados} recurso{"s" if recursos_copiados != 1 else ""}'
            )
        if reutilizado:
            mensaje += f' Se reutilizó del mismo modelo: {" y ".join(reutilizado)}.'
        if folio:
            mensaje += f' Folio de alta: {folio}'
        flash(mensaje, 'success')
        return redirect(url_for('admin.ver_equipo', id=equipo_id))

    except Exception as ex:
        current_app.logger.error(f"Error en agregar_equipo: {str(ex)}")
        flash('Error interno del servidor. Intenta de nuevo.', 'error')
        return redirect(url_for('admin.agregar_equipo'))

    finally:
        if db:
            db.close()

@admin_bp.route('/inventario/<int:id>/reporte-alta')
@requiere_rol(ROL_USUARIO)
def ver_reporte_alta(id):
    """
    Página visor: muestra el PDF en el navegador con pdf.js para poder
    revisarlo antes de decidir si se descarga.
    """
    db = None
    try:
        db = get_connection()

        equipo           = ModelInventario.get_by_id(db, id)
        reporte, creado  = _asegurar_reporte_alta(db, id, equipo)
        if not reporte:
            flash('No se pudo preparar el reporte de alta de este equipo.', 'error')
            return redirect(url_for('admin.ver_equipo', id=id))

        firmas = ModelFirmas.get_por_reporte(db, reporte['id'])

        return render_template(
            'admin/Reportes_PDF/ver_reporte_alta.html',
            equipo       = equipo,
            equipo_id    = id,
            reporte      = reporte,
            folio        = reporte['folio'],
            fecha_txt    = _fecha_larga_es(reporte.get('fecha')),
            firmas       = firmas,
            pendientes   = ModelFirmas.roles_pendientes(firmas),
            completo     = ModelFirmas.esta_completo(firmas),
            etiquetas    = ModelFirmas.ETIQUETAS_ROL,
            # El aviso va en la propia página y no por flash: base.html deja
            # el bloque de mensajes vacío y cada pantalla pinta los suyos, así
            # que un flash aquí no se vería y reaparecería en otra pantalla.
            recien_creado = creado,
            regularizado  = bool((reporte.get('datos') or {}).get('regularizado')),
        )

    except Exception as ex:
        current_app.logger.error(f"Error abriendo reporte alta [{id}]: {ex}")
        flash('Error al abrir el reporte. Intenta de nuevo.', 'error')
        return redirect(url_for('admin.ver_equipo', id=id))

    finally:
        if db:
            db.close()


@admin_bp.route('/inventario/<int:id>/reporte-alta/archivo')
@requiere_rol(ROL_USUARIO)
def archivo_reporte_alta(id):
    """
    Entrega el PDF del reporte de alta.

    Por defecto lo sirve en línea (es lo que consume el iframe del visor).
    Con ?descargar=1 lo manda como adjunto, y con ?regenerar=1 lo rehace
    antes de servirlo — esto último solo para Biomédico o superior.

    El PDF se lee del disco; solo se genera si todavía no existe, que es
    el caso de los reportes creados antes de que se guardara el archivo.
    """
    db = None
    try:
        db = get_connection()

        equipo          = ModelInventario.get_by_id(db, id)
        reporte, creado = _asegurar_reporte_alta(db, id, equipo)
        if not reporte:
            flash('No se pudo preparar el reporte de alta de este equipo.', 'error')
            return redirect(url_for('admin.ver_equipo', id=id))

        ruta     = _ruta_pdf_reporte(reporte['folio'])
        regenera = request.args.get('regenerar') == '1' and tiene_rol(ROL_BIOMEDICO)

        if regenera or creado or not os.path.exists(ruta):
            firmas = ModelFirmas.get_por_reporte(db, reporte['id'])
            ruta   = _generar_pdf_reporte(db, reporte, equipo, firmas)

        return send_file(
            ruta,
            as_attachment = request.args.get('descargar') == '1',
            download_name = f"{reporte['folio']}.pdf",
            mimetype      = 'application/pdf',
            max_age       = 0,
        )

    except Exception as ex:
        current_app.logger.error(f"Error generando reporte alta [{id}]: {ex}")
        flash('Error al generar el PDF. Intenta de nuevo.', 'error')
        return redirect(url_for('admin.ver_equipo', id=id))

    finally:
        if db:
            db.close()


@admin_bp.route('/inventario/<int:id>/reporte-alta/firmar', methods=['POST'])
@requiere_rol(ROL_BIOMEDICO)
def firmar_reporte_alta(id):
    """
    Registra una de las dos firmas del reporte de alta y rehace el PDF.

    Quien firma en el papel puede no tener cuenta en el sistema: el
    biomédico con la sesión abierta presta el equipo para que el
    responsable del área trace su firma. Por eso el permiso es del usuario
    en sesión y el nombre se captura, no se deduce.

    Responde JSON porque lo llama el visor sin recargar la página.
    """
    db = None
    try:
        db = get_connection()

        reporte, _ = _asegurar_reporte_alta(db, id)
        if not reporte:
            return jsonify({'ok': False, 'error': 'No existe reporte de alta.'}), 404

        rol     = (request.form.get('rol') or '').strip()
        nombre  = _limitar(request.form.get('nombre', ''), LIMITES['firma_nombre'])
        cargo   = _limitar(request.form.get('cargo', ''),  LIMITES['firma_cargo'])
        trazo   = request.form.get('firma', '')

        if rol not in ModelFirmas.ROLES_ALTA:
            return jsonify({'ok': False, 'error': 'Rol de firma inválido.'}), 400
        if not nombre:
            return jsonify({'ok': False, 'error': 'Escribe el nombre de quien firma.'}), 400

        # Antes de guardar el archivo: si ese rol ya está firmado no se
        # toca nada, ni siquiera el disco.
        firmas = ModelFirmas.get_por_reporte(db, reporte['id'])
        if rol in firmas:
            return jsonify({'ok': False, 'error': 'Esa parte del reporte ya está firmada.'}), 409

        try:
            imagen_rel = ModelFirmas.guardar_firma_png(trazo)
        except ValueError as e:
            return jsonify({'ok': False, 'error': str(e)}), 400

        ok, mensaje = ModelFirmas.crear(
            db,
            reporte_id = reporte['id'],
            rol        = rol,
            nombre     = nombre,
            cargo      = cargo,
            imagen_rel = imagen_rel,
            usuario_id = current_user.IDusuario,
        )
        if not ok:
            # La fila no entró: el PNG que se acaba de guardar sobra.
            ModelInventario.eliminar_archivo_fisico(imagen_rel)
            return jsonify({'ok': False, 'error': mensaje}), 409

        firmas = ModelFirmas.get_por_reporte(db, reporte['id'])
        equipo = ModelInventario.get_by_id(db, id)
        _generar_pdf_reporte(db, reporte, equipo, firmas)

        return jsonify({
            'ok':         True,
            'completo':   ModelFirmas.esta_completo(firmas),
            'pendientes': ModelFirmas.roles_pendientes(firmas),
            'mensaje':    mensaje,
        })

    except Exception as ex:
        current_app.logger.error(f"Error firmando reporte alta [{id}]: {ex}")
        return jsonify({'ok': False, 'error': 'Error al registrar la firma.'}), 500

    finally:
        if db:
            db.close()


@admin_bp.route('/inventario/<int:id>')
@requiere_rol(ROL_USUARIO)
def ver_equipo(id):
    db = get_connection()
    equipo        = ModelInventario.get_by_id(db, id)
    departamentos = ModelInventario.get_departamentos(db)
    propiedades   = ModelInventario.get_propiedades(db)
    db.close()

    if not equipo:
        flash('Equipo no encontrado', 'error')
        return redirect(url_for('admin.ver_inventario'))

    # TODO (historial/logs):
    # Cuando implementes auditoría, sustituye [] por:
    # logs = ModelLogs.get_by_equipo(db, id)
    # Cada log debe tener: descripcion, usuario, fecha, tipo
    # ('edicion' | 'mantenimiento' | 'otro')

    return render_template('admin/ver_equipo_admin.html',
        equipo=equipo,
        departamentos=departamentos,
        propiedades=propiedades,
        today=date.today(),
        logs=[]
    )


@admin_bp.route('/inventario/<int:id>/editar', methods=['GET', 'POST'])
@requiere_rol(ROL_BIOMEDICO)
def editar_equipo(id):
    if request.method == 'GET':
        return redirect(url_for('admin.ver_equipo', id=id))

    db = get_connection()
    ok = ModelInventario.actualizar(db, id, request.form.to_dict())
    db.close()

    if ok:
        flash('Cambios guardados correctamente', 'success')
    else:
        flash('Error al guardar los cambios', 'error')

    return redirect(url_for('admin.ver_equipo', id=id))


@admin_bp.route('/inventario/<int:id>/eliminar')
@requiere_rol(ROL_ADMIN)
def eliminar_equipo(id):
    # TODO: Implementar eliminación
    # 1. Verificar que el equipo existe: ModelEquipos.get_by_id(db, id)
    # 2. Si tiene imagen, eliminar el archivo físico de /static/uploads/
    #    → import os; os.remove(os.path.join(app.config['UPLOAD_FOLDER'], equipo.imagen))
    # 3. Eliminar registros relacionados primero si tienes FK:
    #    → logs, mantenimientos, documentos asociados
    # 4. ModelEquipos.eliminar(db, id)
    # 5. flash('Equipo eliminado', 'success')
    # 6. redirect a ver_inventario
    flash('Eliminación en construcción', 'info')
    return redirect(url_for('admin.ver_inventario'))


@admin_bp.route('/inventario/<int:id>/imagen', methods=['POST'])
@requiere_rol(ROL_BIOMEDICO)
def actualizar_imagen(id):
    imagen_file = request.files.get('imagen')
    if not imagen_file or imagen_file.filename == '':
        flash('No se seleccionó ninguna imagen', 'error')
        return redirect(url_for('admin.ver_equipo', id=id))

    try:
        # Obtener imagen actual para eliminarla después
        db  = get_connection()
        eq  = ModelInventario.get_by_id(db, id)

        # Guardar nueva imagen en disco
        nueva = ModelInventario.guardar_imagen(imagen_file)

        # Eliminar imagen vieja del disco si existía
        if eq and eq.get('imagen'):
            ruta_vieja = os.path.join(
                os.path.dirname(__file__), '..', 'static', eq['imagen']
            )
            ruta_vieja = os.path.abspath(ruta_vieja)
            if os.path.exists(ruta_vieja):
                os.remove(ruta_vieja)

        # Actualizar BD
        ModelInventario.actualizar_imagen(db, id, nueva)
        db.close()

        flash('Imagen actualizada correctamente', 'success')

    except ValueError as e:
        flash(str(e), 'error')

    return redirect(url_for('admin.ver_equipo', id=id))


@admin_bp.route('/inventario/<int:id>/imagen/eliminar')
@requiere_rol(ROL_BIOMEDICO)
def eliminar_imagen(id):
    # TODO: Implementar eliminación de imagen
    # 1. Obtener equipo: ModelEquipos.get_by_id(db, id)
    # 2. Si equipo.imagen existe:
    #    → path = os.path.join(app.config['UPLOAD_FOLDER'], equipo.imagen)
    #    → if os.path.exists(path): os.remove(path)
    # 3. ModelEquipos.actualizar_imagen(db, id, None)  ← poner NULL en BD
    # 4. flash('Imagen eliminada', 'success')
    # 5. redirect a ver_equipo(id)
    flash('Eliminación de imagen en construcción', 'info')
    return redirect(url_for('admin.ver_equipo', id=id))


@admin_bp.route('/inventario/<int:id>/mantenimientos')
@requiere_rol(ROL_USUARIO)
def ver_mantenimientos(id):
    # TODO: Implementar historial de mantenimientos
    # Necesitarás una tabla en BD, ejemplo:
    #   Mantenimientos(id, equipo_id FK, tipo, descripcion,
    #                  tecnico, fecha, costo, proximo_mantenimiento)
    # GET → listar todos los mantenimientos del equipo
    #       ModelMantenimientos.get_by_equipo(db, id)
    # Mostrar formulario para registrar uno nuevo
    # POST (ruta separada /mantenimientos/nuevo) → insertar registro
    flash('Mantenimientos en construcción', 'info')
    return redirect(url_for('admin.ver_equipo', id=id))


@admin_bp.route('/inventario/exportar')
@requiere_rol(ROL_USUARIO)
def exportar_inventario():
    # TODO: Implementar exportación a Excel
    # 1. Recoger los mismos filtros que ver_inventario (q, depto, estado, etc.)
    #    para exportar solo lo que el usuario tiene filtrado
    # 2. pip install openpyxl
    # 3. Crear workbook con openpyxl, una fila por equipo
    # 4. Columnas: No.Inventario, No.Serie, Equipo, Marca, Modelo,
    #              Departamento, Estado, Propiedad, Adquisicion, Garantia
    # 5. from flask import send_file + BytesIO
    #    → return send_file(buffer, as_attachment=True,
    #                       download_name='inventario.xlsx',
    #                       mimetype='application/vnd.openxmlformats...')
    flash('Exportación en construcción', 'info')
    return redirect(url_for('admin.ver_inventario'))


@admin_bp.route('/inventario/importar', methods=['GET', 'POST'])
@requiere_rol(ROL_BIOMEDICO)
def importar():
    # TODO: Implementar importación desde Excel
    # GET  → mostrar formulario de subida de archivo
    # POST → leer archivo .xlsx con openpyxl o pandas
    #        → iterar filas, validar datos, insertar con ModelEquipos.crear()
    #        → reportar cuántos se importaron y cuántos fallaron
    #        → flash(f'{ok} equipos importados, {err} errores', 'success')
    flash('Importación en construcción', 'info')
    return redirect(url_for('admin.ver_inventario'))


@admin_bp.route('/inventario/categorias')
@requiere_rol(ROL_USUARIO)
def categorias():
    # TODO: Implementar gestión de categorías/tipos de equipo
    # Útil para normalizar los nombres de equipos y evitar duplicados
    # Tabla sugerida: Categorias(id, nombre, descripcion, icono)
    # CRUD completo: listar, agregar, editar, eliminar categorías
    flash('Categorías en construcción', 'info')
    return redirect(url_for('admin.ver_inventario'))




@admin_bp.route('/inventario/<int:id>/recursos')
@requiere_rol(ROL_USUARIO)
def ver_recursos(id):
    db     = get_connection()
    equipo = ModelInventario.get_by_id(db, id)

    if not equipo:
        db.close()
        flash('Equipo no encontrado', 'error')
        return redirect(url_for('admin.ver_inventario'))

    recursos  = ModelRecursos.get_recursos_por_equipo(db, id)
    coinciden = ModelRecursos.contar_equipos_coincidentes(db, equipo['modelo'])
    db.close()

    return render_template('admin/recursos_equipo.html',
        equipo=equipo,
        recursos=recursos,
        coinciden=coinciden,
        categorias=ModelRecursos.CATEGORIAS_VALIDAS,
        tipos=list(ModelRecursos.TIPOS_PERMITIDOS.keys()),
        today=date.today()
    )


@admin_bp.route('/inventario/<int:id>/recursos/subir', methods=['POST'])
@requiere_rol(ROL_BIOMEDICO)
def subir_recurso(id):
    db     = get_connection()
    equipo = ModelInventario.get_by_id(db, id)

    if not equipo:
        db.close()
        flash('Equipo no encontrado', 'error')
        return redirect(url_for('admin.ver_inventario'))

    tipo      = request.form.get('tipo', '').strip()
    categoria = request.form.get('categoria', '').strip()
    nombre    = request.form.get('nombre', '').strip()
    descripcion = request.form.get('descripcion', '').strip()
    archivo_file = request.files.get('archivo')
    url_link     = request.form.get('url_link', '').strip()

    # Construir datos para validar
    datos = {
        'nombre':      nombre,
        'tipo':        tipo,
        'categoria':   categoria,
        'descripcion': descripcion,
        'archivo':     url_link if tipo == 'link' else '',
        'subido_por':  current_user.NombreUsuario
    }

    tiene_archivo = archivo_file and archivo_file.filename != ''

    # Validar
    ok, mensaje = ModelRecursos.validar_datos(datos, tiene_archivo)
    if not ok:
        db.close()
        flash(mensaje, 'error')
        return redirect(url_for('admin.ver_recursos', id=id))

    # Guardar archivo físico si no es link
    if tipo != 'link':
        try:
            datos['archivo'] = ModelRecursos.guardar_archivo(
                archivo_file, categoria, tipo
            )
        except ValueError as e:
            db.close()
            flash(str(e), 'error')
            return redirect(url_for('admin.ver_recursos', id=id))

    # Insertar en BD y vincular equipos
    ok, recurso_id, total_vinculados = ModelRecursos.crear_recurso(db, datos, id)
    db.close()

    if ok:
        flash(
            f'Recurso subido correctamente y vinculado a {total_vinculados} equipo(s).',
            'success'
        )
    else:
        # Si falló la BD pero el archivo ya se guardó, limpiarlo
        if tipo != 'link' and datos.get('archivo'):
            ModelRecursos.eliminar_archivo_fisico(datos['archivo'])
        flash('Error al guardar el recurso. Intenta de nuevo.', 'error')

    return redirect(url_for('admin.ver_recursos', id=id))


@admin_bp.route('/inventario/<int:id>/recursos/<int:recurso_id>/eliminar')
@requiere_rol(ROL_BIOMEDICO)
def eliminar_recurso(id, recurso_id):
    db = get_connection()

    ok, archivo = ModelRecursos.eliminar_recurso(db, recurso_id)
    db.close()

    if ok:
        # Borrar archivo físico si existía
        if archivo:
            ModelRecursos.eliminar_archivo_fisico(archivo)
        flash('Recurso eliminado correctamente.', 'success')
    else:
        flash('Error al eliminar el recurso.', 'error')

    return redirect(url_for('admin.ver_recursos', id=id))

# ═════════════════════════════════════════════════════════════════════════════
#  GESTIÓN DE USUARIOS — exclusiva del Administrador
#
#  El Biomédico opera equipos y localización, pero no administra cuentas: si
#  pudiera, se podría asignar el rol de Administrador a sí mismo y el resto de
#  la matriz de permisos dejaría de significar nada.
# ═════════════════════════════════════════════════════════════════════════════


# ── Listar ────────────────────────────────────────────────────────────────────
@admin_bp.route('/usuarios')
@requiere_rol(ROL_ADMIN)
def ver_usuarios():
    usuarios = ModelUsuarios.get_all()
    return render_template('admin/usuarios.html', usuarios=usuarios)


# ── Crear ─────────────────────────────────────────────────────────────────────
@admin_bp.route('/usuarios/crear', methods=['POST'])
@requiere_rol(ROL_ADMIN)
def crear_usuario():
    nombre   = request.form.get('NombreUsuario', '').strip()
    apellido = request.form.get('Apellido', '').strip()
    email    = request.form.get('Email', '').strip().lower()
    password = request.form.get('Password', '').strip()
    permiso  = request.form.get('Permiso', ROL_USUARIO)

    # Validaciones de negocio
    errores = _validar_campos_base(nombre, apellido, email)
    errores += _validar_rol(permiso)
    errores += _validar_password(password, obligatoria=True)
    if ModelUsuarios.email_existe(email):
        errores.append('Ya existe un usuario registrado con ese email.')

    if errores:
        for e in errores:
            flash(e, 'error')
        return redirect(url_for('admin.ver_usuarios'))

    try:
        ModelUsuarios.crear(nombre, apellido, email, password, permiso)
        current_app.logger.info(
            '[Usuarios] %s creó la cuenta %s con rol %s',
            current_user.IDusuario, email, permiso
        )
        flash(f'Usuario {nombre} {apellido} creado correctamente.', 'success')
    except ValueError as exc:
        flash(str(exc), 'error')
    except Exception as exc:
        current_app.logger.error('Error al crear usuario: %s', exc)
        flash('Ocurrió un error al crear el usuario. Intenta nuevamente.', 'error')

    return redirect(url_for('admin.ver_usuarios'))


# ── Editar ────────────────────────────────────────────────────────────────────
@admin_bp.route('/usuarios/<int:uid>/editar', methods=['POST'])
@requiere_rol(ROL_ADMIN)
def editar_usuario(uid):
    nombre   = request.form.get('NombreUsuario', '').strip()
    apellido = request.form.get('Apellido', '').strip()
    email    = request.form.get('Email', '').strip().lower()
    password = request.form.get('Password', '').strip() or None   # None = sin cambio
    permiso  = request.form.get('Permiso', ROL_USUARIO)
    estado   = 1 if str(request.form.get('Estado', 1)).strip() == '1' else 0

    # El usuario debe existir
    actual = ModelUsuarios.get_by_id(uid)
    if not actual:
        flash('Usuario no encontrado.', 'error')
        return redirect(url_for('admin.ver_usuarios'))

    # Validaciones de negocio
    errores = _validar_campos_base(nombre, apellido, email)
    errores += _validar_rol(permiso)
    errores += _validar_password(password, obligatoria=False)
    errores += _validar_salvaguardas(uid, actual, nuevo_permiso=permiso, nuevo_estado=estado)
    if ModelUsuarios.email_existe(email, exclude_uid=uid):
        errores.append('Ese email ya está en uso por otro usuario.')

    if errores:
        for e in errores:
            flash(e, 'error')
        return redirect(url_for('admin.ver_usuarios'))

    try:
        ModelUsuarios.editar(uid, nombre, apellido, email, permiso, estado, password)
        current_app.logger.info(
            '[Usuarios] %s editó la cuenta %s (rol=%s estado=%s%s)',
            current_user.IDusuario, uid, permiso, estado,
            ', contraseña restablecida' if password else ''
        )
        flash(f'Usuario {nombre} {apellido} actualizado correctamente.', 'success')
    except ValueError as exc:
        flash(str(exc), 'error')
    except Exception as exc:
        current_app.logger.error('Error al editar usuario %s: %s', uid, exc)
        flash('Ocurrió un error al actualizar el usuario. Intenta nuevamente.', 'error')

    return redirect(url_for('admin.ver_usuarios'))


# ── Toggle Estado (activar / desactivar) ──────────────────────────────────────
@admin_bp.route('/usuarios/<int:uid>/toggle', methods=['POST'])
@requiere_rol(ROL_ADMIN)
def toggle_estado_usuario(uid):
    usuario = ModelUsuarios.get_by_id(uid)

    if not usuario:
        flash('Usuario no encontrado.', 'error')
        return redirect(url_for('admin.ver_usuarios'))

    # Solo hay que validar cuando se está desactivando (Estado 1 → 0).
    if usuario['Estado']:
        errores = _validar_salvaguardas(
            uid, usuario,
            nuevo_permiso=usuario['Permiso'],
            nuevo_estado=0,
        )
        if errores:
            for e in errores:
                flash(e, 'error')
            return redirect(url_for('admin.ver_usuarios'))

    try:
        ModelUsuarios.toggle_estado(uid)
        accion = 'desactivado' if usuario['Estado'] else 'activado'
        current_app.logger.info(
            '[Usuarios] %s %s la cuenta %s', current_user.IDusuario, accion, uid
        )
        flash(
            f'Usuario {usuario["NombreUsuario"]} {usuario["Apellido"]} {accion} correctamente.',
            'success'
        )
    except Exception as exc:
        current_app.logger.error('Error al cambiar estado del usuario %s: %s', uid, exc)
        flash('Ocurrió un error al cambiar el estado. Intenta nuevamente.', 'error')

    return redirect(url_for('admin.ver_usuarios'))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers privados
# ─────────────────────────────────────────────────────────────────────────────

def _validar_campos_base(nombre, apellido, email):
    """
    Valida los campos comunes a crear y editar.
    Retorna una lista de mensajes de error (vacía si todo está bien).
    """
    errores = []
    if not nombre:
        errores.append('El nombre es obligatorio.')
    if not apellido:
        errores.append('El apellido es obligatorio.')
    if not email:
        errores.append('El email es obligatorio.')
    elif '@' not in email or '.' not in email.split('@')[-1]:
        errores.append('El email no tiene un formato válido.')
    return errores


def _validar_rol(permiso):
    """
    Lista blanca de roles. Antes se aceptaba cualquier cadena que llegara en
    el formulario y se guardaba tal cual, así que un valor con una errata
    dejaba la cuenta con un rol inexistente y sin acceso a nada.
    """
    if rol_canonico(permiso) is None:
        return [f'El rol «{permiso}» no es válido.']
    return []


def _validar_password(password, obligatoria):
    """Aplica la política de contraseñas. Al editar, vacía = sin cambio."""
    if not password:
        return ['La contraseña es obligatoria al crear un usuario.'] if obligatoria else []
    if not User.validar_password(password):
        return [User.MENSAJE_PASSWORD]
    return []


def _validar_salvaguardas(uid, actual, nuevo_permiso, nuevo_estado):
    """
    Evita los dos escenarios en los que el panel de usuarios se puede dejar
    a sí mismo sin salida:

      1. Un administrador se degrada o se desactiva por error y pierde el
         acceso al propio panel que necesitaría para revertirlo.
      2. Se degrada o desactiva al último administrador activo y el sistema
         queda sin nadie que pueda gestionar cuentas.
    """
    errores = []
    era_admin  = rol_canonico(actual.get('Permiso')) == ROL_ADMIN
    sigue_admin = rol_canonico(nuevo_permiso) == ROL_ADMIN and nuevo_estado == 1

    if uid == current_user.IDusuario:
        if rol_canonico(nuevo_permiso) != ROL_ADMIN:
            errores.append(
                'No puedes cambiar tu propio rol. Pídeselo a otro administrador.'
            )
        if nuevo_estado == 0:
            errores.append('No puedes desactivar tu propia cuenta.')

    if era_admin and not sigue_admin:
        if ModelUsuarios.contar_administradores_activos(excluir_uid=uid) == 0:
            errores.append(
                'Es el único administrador activo. Asigna ese rol a otra '
                'cuenta antes de cambiarlo o desactivarlo.'
            )

    return errores