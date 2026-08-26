from flask import (
    Blueprint, render_template, redirect,
    url_for, flash, request, current_app
)
from flask_login import current_user
from database.db import get_connection
from models.model_mantenimientos import ModelMantenimientos
from models.reportes.base import ModelReporteBase
from models.entities.decorators import (
    requiere_rol, tiene_rol,
    ROL_USUARIO, ROL_BIOMEDICO,
)

mantenimientos_bp = Blueprint('mantenimientos', __name__)


def _puede_editar_mantenimientos():
    """
    El programa de mantenimiento es trabajo del biomédico, así que basta con
    ese perfil (antes exigía Administrador, lo que obligaba a que un admin
    hiciera la captura operativa).
    """
    return tiene_rol(ROL_BIOMEDICO)


# ── 1. Vista pública del equipo (reemplaza equipos.ProgramaMantenimiento) ──

@mantenimientos_bp.route('/mantenimientos/<numero_inventario>')
def programa_mantenimiento(numero_inventario):
    """
    Vista pública del estado de mantenimiento de un equipo.
    No requiere login — muestra tarjeta de solo lectura.
    Si el usuario es Biomédico o Administrador, muestra botón de edición.
    """
    try:
        db = get_connection()

        # Obtener equipo base (reutilizamos la query mínima necesaria)
        cursor = db.cursor()
        cursor.execute("""
            SELECT id, equipo_unidad, marca, modelo,
                   numero_serie, numero_inventario,
                   departamento, area, estado, imagen
            FROM HospitalGalenia.dbo.InventarioEquipos
            WHERE numero_inventario = ?
        """, (numero_inventario,))
        row = cursor.fetchone()

        if row is None:
            cursor.close()
            flash('Equipo no encontrado.', 'warning')
            return redirect(url_for('equipos.Catalogo'))

        columns = [col[0] for col in cursor.description]
        equipo  = dict(zip(columns, row))
        cursor.close()

        # Obtener mantenimiento (puede ser None si no tiene registro)
        mantenimiento = ModelMantenimientos.obtener_por_equipo(db, equipo['id'])
        db.close()

        puede_editar = _puede_editar_mantenimientos()

        return render_template(
            'UserC/Recursos/programa_mantenimiento.html',
            equipo        = equipo,
            mantenimiento = mantenimiento,
            puede_editar  = puede_editar,
        )

    except Exception as e:
        current_app.logger.error(f"Error programa_mantenimiento [{numero_inventario}]: {e}")
        flash('Error al cargar la información de mantenimiento.', 'danger')
        return redirect(url_for('equipos.Catalogo'))


# ── 2. Formulario de edición ────────────────────────────────────────────────

@mantenimientos_bp.route('/mantenimientos/<numero_inventario>/editar', methods=['GET', 'POST'])
@requiere_rol(ROL_BIOMEDICO)
def editar_mantenimiento(numero_inventario):
    """
    GET  → Muestra formulario precargado con datos actuales.
    POST → Guarda cambios y redirige a la vista pública del equipo.
    Accesible para Biomédico y Administrador.
    """

    try:
        db = get_connection()

        # Obtener equipo
        cursor = db.cursor()
        cursor.execute("""
            SELECT id, equipo_unidad, marca, modelo,
                   numero_serie, numero_inventario,
                   departamento, area, estado, imagen
            FROM HospitalGalenia.dbo.InventarioEquipos
            WHERE numero_inventario = ?
        """, (numero_inventario,))
        row = cursor.fetchone()

        if row is None:
            cursor.close()
            flash('Equipo no encontrado.', 'warning')
            return redirect(url_for('equipos.Catalogo'))

        columns = [col[0] for col in cursor.description]
        equipo  = dict(zip(columns, row))
        cursor.close()

        # Obtener mantenimiento actual (puede ser None)
        mantenimiento = ModelMantenimientos.obtener_por_equipo(db, equipo['id'])

        # ── POST: guardar ────────────────────────────────────────────────
        if request.method == 'POST':
            datos = {
                'tipo_mantenimiento':    request.form.get('tipo_mantenimiento', 'Preventivo'),
                'frecuencia_meses':      request.form.get('frecuencia_meses', 6),
                'ultimo_mantenimiento':  request.form.get('ultimo_mantenimiento')  or None,
                'proximo_mantenimiento': request.form.get('proximo_mantenimiento') or None,
                'responsable':           request.form.get('responsable', '').strip() or None,
                'notas':                 request.form.get('notas', '').strip()       or None,
            }

            ok = ModelMantenimientos.guardar(db, equipo['id'], datos)
            db.close()

            if ok:
                flash('Mantenimiento actualizado correctamente.', 'success')
            else:
                flash('Error al guardar el mantenimiento.', 'danger')

            return redirect(url_for('mantenimientos.programa_mantenimiento',
                                    numero_inventario=numero_inventario))

        # ── GET: mostrar formulario ──────────────────────────────────────
        db.close()
        return render_template(
            'UserC/Recursos/editar_mantenimiento.html',
            equipo        = equipo,
            mantenimiento = mantenimiento,
        )

    except Exception as e:
        current_app.logger.error(f"Error editar_mantenimiento [{numero_inventario}]: {e}")
        flash('Error inesperado.', 'danger')
        return redirect(url_for('mantenimientos.programa_mantenimiento',
                                numero_inventario=numero_inventario))


# ── 3. Dashboard general ────────────────────────────────────────────────────

@mantenimientos_bp.route('/mantenimientos')
@requiere_rol(ROL_USUARIO)
def dashboard():
    """
    Vista general de todos los equipos con su estado de mantenimiento.
    Filtros opcionales por GET: ?estado=vencido&departamento=UCI
    Es una pantalla de consulta: cualquier usuario autenticado puede verla.
    """
    try:
        filtro_estado       = request.args.get('estado', '').strip()       or None
        filtro_departamento = request.args.get('departamento', '').strip() or None
        page                = request.args.get('page', 1, type=int)
        per_page            = 15

        db = get_connection()
        equipos, total = ModelMantenimientos.obtener_todos(
            db, filtro_estado, filtro_departamento, page, per_page
        )
        # Independiente del filtro de estado: si no, al filtrar por
        # "Vencidos" las demás tarjetas (Al día, Próximos...) mostrarían 0
        # en vez de su total real.
        contadores    = ModelMantenimientos.obtener_stats(db, filtro_departamento)
        departamentos = ModelMantenimientos.obtener_departamentos(db)

        # Lo que está a medias va arriba de la lista de pendientes: es trabajo
        # ya empezado, y hasta ahora no se veía desde ninguna pantalla — quien
        # salía del módulo de captura no tenía por dónde volver a entrar.
        en_proceso = ModelReporteBase.abiertos(
            db, tipo=('preventivo', 'correctivo'), limite=12)
        db.close()

        return render_template(
            'UserC/Recursos/dashboard_mantenimientos.html',
            equipos             = equipos,
            total               = total,
            page                = page,
            per_page            = per_page,
            departamentos       = departamentos,
            contadores          = contadores,
            filtro_estado       = filtro_estado       or '',
            filtro_departamento = filtro_departamento or '',
            en_proceso          = en_proceso,
        )

    except Exception as e:
        current_app.logger.error(f"Error dashboard mantenimientos: {e}")
        flash('Error al cargar el dashboard.', 'danger')
        return redirect(url_for('equipos.Catalogo'))