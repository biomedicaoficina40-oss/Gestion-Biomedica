from flask import Blueprint, render_template, request, redirect, url_for, flash,current_app
from flask_login import login_required, current_user
from database.db import get_connection
from datetime import date
import os
import json
from weasyprint import HTML as WeasyHTML
from io import BytesIO
from models.ModelInventario import ModelInventario
from models.model_recursos import ModelRecursos
from models.ModelReportes import ModelReportes

admin_bp = Blueprint('admin', __name__)


# ── Gestión de Inventario ──────────────────────────────────────

@admin_bp.route('/inventario')
@login_required
def ver_inventario():
    q         = request.args.get('q', '').strip()
    depto     = request.args.get('depto', '')
    estado    = request.args.get('estado', '')
    marca     = request.args.get('marca', '')
    propiedad = request.args.get('propiedad', '')
    sort      = request.args.get('sort', '')
    dir       = request.args.get('dir', 'asc')
    page      = request.args.get('page', 1, type=int)
    per_page  = 15
    db = get_connection()
    equipos, total = ModelInventario.get_inventario(db, q, depto, estado, marca, propiedad, sort, dir, page, per_page)
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
        today=date.today()
    )

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render_template('admin/inventario_fragment.html', **ctx)

    return render_template('admin/inventario.html', **ctx)


@admin_bp.route('/inventario/agregar', methods=['GET', 'POST'])
@login_required
def agregar_equipo():
    db = None
    try:
        db = get_connection()

        if request.method == 'GET':
            # ── Datos para selects ──────────────────────────────
            departamentos = ModelInventario.get_departamentos(db)
            propiedades   = ModelInventario.get_propiedades(db)

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
                equipos_ac    = equipos_ac,
                marcas_ac     = marcas_ac,
                modelos_ac    = modelos_ac,
                num_eqme      = num_eqme,
                num_amco      = num_amco,
                prefijos       = ['EQ-ME', 'AM-CO'],
            )

        # ── POST ────────────────────────────────────────────────
        # Validar CSRF ya lo maneja Flask-WTF automáticamente

        # 1 — Recoger y sanear campos
        prefijo          = request.form.get('prefijo', '').strip()
        equipo_unidad    = request.form.get('equipo_unidad', '').strip()
        marca            = request.form.get('marca', '').strip()
        modelo           = request.form.get('modelo', '').strip()
        numero_serie     = request.form.get('numero_serie', '').strip()
        area             = request.form.get('area', '').strip()
        estado           = request.form.get('estado', '').strip()
        observaciones    = request.form.get('observaciones', '').strip()
        # ── Campos solo para el reporte (no van a la BD principal) ──
        motivo_ingreso       = request.form.get('motivo_ingreso', '').strip()
        empresa_responsable  = request.form.get('empresa_responsable', '').strip()
        obs_reporte          = request.form.get('obs_reporte', '').strip()

        # Accesorios — vienen como listas paralelas del formulario
        acc_desc      = request.form.getlist('acc_descripcion')
        acc_cant      = request.form.getlist('acc_cantidad')
        acc_condicion = request.form.getlist('acc_condicion')
        accesorios = [
            {'descripcion': d.strip(), 'cantidad': c.strip(), 'condicion': co.strip()}
            for d, c, co in zip(acc_desc, acc_cant, acc_condicion)
            if d.strip()
        ]

        # Departamento: si eligió "otro" usar el campo libre
        departamento = request.form.get('departamento', '').strip()
        if departamento == '__otro__':
            departamento = request.form.get('departamento_nuevo', '').strip()

        # Propiedad: igual
        propiedad = request.form.get('propiedad', '').strip()
        if propiedad == '__otro__':
            propiedad = request.form.get('propiedad_nueva', '').strip()

        # Fechas — pueden venir vacías
        fecha_adquisicion  = request.form.get('fecha_adquisicion')  or None
        fecha_fabricacion  = request.form.get('fecha_fabricacion')  or None
        fecha_fin_garantia = request.form.get('fecha_fin_garantia') or None

        # 2 — Validaciones del lado servidor
        errores = []
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

        # 3 — Generar número de inventario
        numero_inventario = ModelInventario.generar_numero_inventario(db, prefijo)
        if not numero_inventario:
            flash('Error al generar el número de inventario.', 'error')
            return redirect(url_for('admin.agregar_equipo'))

        # 4 — Manejar imagen (opcional)
        imagen_path = None
        imagen_file = request.files.get('imagen')
        if imagen_file and imagen_file.filename:
            try:
                imagen_path = ModelInventario.guardar_imagen(imagen_file)
            except ValueError as e:
                flash(str(e), 'error')
                return redirect(url_for('admin.agregar_equipo'))

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
            # Si falló y ya subimos imagen, limpiarla
            if imagen_path:
                ModelInventario.eliminar_archivo_fisico(imagen_path)
            flash('Error al registrar el equipo. Intenta de nuevo.', 'error')
            return redirect(url_for('admin.agregar_equipo'))

        # 6 — Crear reporte de alta
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

        flash(
            f'Equipo {numero_inventario} registrado correctamente. '
            f'{"Folio de alta: " + folio if folio else ""}',
            'success'
        )
        return redirect(url_for('admin.ver_equipo', id=equipo_id))

    except Exception as ex:
        current_app.logger.error(f"Error en agregar_equipo: {str(ex)}")
        flash('Error interno del servidor. Intenta de nuevo.', 'error')
        return redirect(url_for('admin.agregar_equipo'))

    finally:
        if db:
            db.close()

@admin_bp.route('/inventario/<int:id>/reporte-alta')
@login_required
def descargar_reporte_alta(id):
    db = None
    try:
        db = get_connection()

        # Buscar el reporte de alta más reciente del equipo
        reportes = ModelReportes.get_por_equipo(db, id, tipo='alta')
        if not reportes:
            flash('No existe reporte de alta para este equipo.', 'error')
            return redirect(url_for('admin.ver_equipo', id=id))

        reporte  = reportes[0]  # el más reciente
        equipo   = ModelInventario.get_by_id(db, id)

        # Deserializar JSON
        import json
        datos = json.loads(reporte['datos_json']) if reporte.get('datos_json') else {}

        # Renderizar template HTML del reporte
        html_str = render_template(
            'admin/Reportes_PDF/reporte_alta.html',
            equipo   = equipo,
            reporte  = reporte,
            datos    = datos,
            folio    = reporte['folio'],
            fecha    = reporte['fecha'],
            static_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), '..', 'static')
            ).replace('\\', '/'),
        )

        # Generar PDF con WeasyPrint
        pdf_bytes = WeasyHTML(string=html_str).write_pdf()
        buffer    = BytesIO(pdf_bytes)

        from flask import send_file
        return send_file(
            buffer,
            as_attachment=True,
            download_name=f"{reporte['folio']}.pdf",
            mimetype='application/pdf'
        )

    except Exception as ex:
        current_app.logger.error(f"Error generando reporte alta [{id}]: {str(ex)}")
        flash('Error al generar el PDF. Intenta de nuevo.', 'error')
        return redirect(url_for('admin.ver_equipo', id=id))

    finally:
        if db:
            db.close()

@admin_bp.route('/inventario/<int:id>')
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
def categorias():
    # TODO: Implementar gestión de categorías/tipos de equipo
    # Útil para normalizar los nombres de equipos y evitar duplicados
    # Tabla sugerida: Categorias(id, nombre, descripcion, icono)
    # CRUD completo: listar, agregar, editar, eliminar categorías
    flash('Categorías en construcción', 'info')
    return redirect(url_for('admin.ver_inventario'))


# ── Usuarios ───────────────────────────────────────────────────

@admin_bp.route('/usuarios')
@login_required
def usuarios():
    # TODO: Implementar gestión de usuarios
    # Listar todos los usuarios del sistema
    # Acciones: crear, editar rol, activar/desactivar, resetear contraseña
    # Roles sugeridos: admin, tecnico, visualizador
    # Modelo: ModelUsuarios.get_all(db)
    flash('Gestión de usuarios en construcción', 'info')
    return redirect(url_for('admin.ver_inventario'))

# ── Recursos de Equipos ────────────────────────────────────────

@admin_bp.route('/inventario/<int:id>/recursos')
@login_required
def ver_recursos(id):
    db     = get_connection()
    equipo = ModelInventario.get_by_id(db, id)

    if not equipo:
        db.close()
        flash('Equipo no encontrado', 'error')
        return redirect(url_for('admin.ver_inventario'))

    recursos  = ModelRecursos.get_recursos_por_equipo(db, id)
    coinciden = ModelRecursos.contar_equipos_coincidentes(
        db, equipo['marca'], equipo['modelo']
    )
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
@login_required
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
@login_required
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