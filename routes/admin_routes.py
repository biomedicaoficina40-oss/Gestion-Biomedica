from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from database.db import get_connection
from datetime import date
from models.ModelInventario import ModelInventario

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
    # TODO: Implementar formulario de alta de equipo
    # GET  → mostrar formulario vacío (template: admin/agregar_equipo.html)
    #        pasar: departamentos, marcas, propiedades para los selects
    # POST → recoger campos del form (equipo_unidad, marca, modelo,
    #        numero_serie, numero_inventario, area, departamento, estado,
    #        propiedad, fecha_adquisicion, fecha_fabricacion,
    #        fecha_fin_garantia, observaciones)
    #        → llamar ModelEquipos.crear(db, datos)
    #        → flash('Equipo agregado correctamente', 'success')
    #        → redirect a ver_equipo con el id recién creado
    flash('Página en construcción', 'info')
    return redirect(url_for('admin.ver_inventario'))


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
    # TODO: Implementar edición completa
    # GET  → redirigir a ver_equipo (la edición ocurre inline en esa página)
    #        o mostrar página de edición separada si lo prefieres
    # POST → recoger todos los campos del formulario de ver_equipo_admin.html
    #        Campos esperados del form:
    #          equipo_unidad, marca, modelo, numero_serie, numero_inventario,
    #          area, departamento, estado, propiedad, observaciones,
    #          fecha_adquisicion, fecha_fabricacion, fecha_fin_garantia
    #        → llamar ModelEquipos.actualizar(db, id, datos)
    #        → flash('Cambios guardados', 'success')
    #        → redirect a ver_equipo(id)
    flash('Edición en construcción', 'info')
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
    # TODO: Implementar subida de imagen
    # 1. Verificar que viene archivo: request.files.get('imagen')
    # 2. Validar extensión permitida: {'png','jpg','jpeg','webp'}
    # 3. Generar nombre único: f"{id}_{uuid4().hex[:8]}.{ext}"
    #    → from uuid import uuid4
    # 4. Guardar en: os.path.join(app.config['UPLOAD_FOLDER'], filename)
    #    → UPLOAD_FOLDER suele ser: 'static/uploads'
    # 5. Si ya tenía imagen anterior, eliminar el archivo viejo
    # 6. ModelEquipos.actualizar_imagen(db, id, filename)
    # 7. flash('Imagen actualizada', 'success')
    # 8. redirect a ver_equipo(id)
    flash('Subida de imagen en construcción', 'info')
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

