from flask import Blueprint, render_template, jsonify, request, current_app, redirect, url_for, flash, session
from flask_login import current_user
from datetime import datetime
from models.ModelCatalogo import ModelEquipos
from database.db import get_connection
from models.entities.decorators import requiere_rol, ROL_BIOMEDICO
from models.model_recursos import ModelRecursos

equipos_bp = Blueprint('equipos', __name__)



@equipos_bp.route('/Catalogo', methods=['GET'])
def Catalogo():
    """Página inicial del catálogo - solo buscador"""
    return render_template('UserC/Catalogo.html', equipo=None, resultados=None)


@equipos_bp.route('/Catalogo/buscar', methods=['GET'])
def BuscarEquipos():
    """Buscar equipos y mostrar resultados"""
    try:
        query = request.args.get('q', '').strip()
        
        if not query:
            flash('Por favor ingresa un término de búsqueda', 'warning')
            return redirect(url_for('equipos.Catalogo'))
        
        db = get_connection()
        resultados = ModelEquipos.buscar_equipos(db, query)
        db.close()
        
        return render_template(
            'UserC/Catalogo.html',
            equipo=None,
            resultados=resultados,
            query=query
        )
        
    except Exception as e:
        current_app.logger.error(f"Error en búsqueda: {str(e)}")
        flash('Error al realizar la búsqueda', 'danger')
        return redirect(url_for('equipos.Catalogo'))
    

@equipos_bp.route('/Catalogo/categorias', methods=['GET'])
def GetCategorias():
    """
    Retorna las categorías de equipos agrupadas para la vista inicial.
    """
    try:
        db         = get_connection()
        categorias = ModelEquipos.get_categorias(db)
        db.close()
        return jsonify(categorias)
    except Exception as e:
        current_app.logger.error(f"Error en categorías: {str(e)}")
        return jsonify([]), 500


@equipos_bp.route('/Catalogo/autocomplete', methods=['GET'])
def Autocomplete():
    """
    Búsqueda en vivo para el campo de texto del catálogo.
    Devuelve JSON con hasta 12 coincidencias.
    """
    try:
        query = request.args.get('q', '').strip()

        # Mínimo 2 caracteres para buscar
        if len(query) < 2:
            return jsonify([])

        db         = get_connection()
        resultados = ModelEquipos.buscar_equipos(db, query)
        db.close()

        # Limitar a 12 resultados para el desplegable
        return jsonify(resultados[:12])

    except Exception as e:
        current_app.logger.error(f"Error en autocomplete: {str(e)}")
        return jsonify([]), 500


@equipos_bp.route('/Catalogo/<string:numero_inventario>', methods=['GET'])
def DetalleEquipo(numero_inventario):
    """Mostrar detalle de un equipo específico"""
    try:
        db = get_connection()
        equipo = ModelEquipos.obtener_equipo(db, numero_inventario)
        db.close()
        
        if not equipo:
            flash('Equipo no encontrado', 'warning')
            return redirect(url_for('equipos.Catalogo'))
        
        return render_template(
            'UserC/Catalogo.html',
            equipo=equipo,
            resultados=None
        )
        
    except Exception as e:
        current_app.logger.error(f"Error al cargar equipo: {str(e)}")
        flash('Error al cargar el equipo', 'danger')
        return redirect(url_for('equipos.Catalogo'))

    # ==============================
# DOCUMENTACIÓN DEL EQUIPO
# ==============================

@equipos_bp.route('/GuiasRapidas/<string:numero_inventario>')
def GuiasRapidas(numero_inventario):
    db     = get_connection()
    equipo = ModelEquipos.obtener_equipo(db, numero_inventario)

    if not equipo:
        db.close()
        flash('Equipo no encontrado', 'warning')
        return redirect(url_for('equipos.Catalogo'))

    guias = ModelRecursos.get_recursos_por_equipo(
        db, equipo['id'], categoria='guia_rapida'
    )
    db.close()

    return render_template('UserC/Recursos/Guias_rapidas_user.html',
        equipo=equipo,
        guias=guias
    )

@equipos_bp.route('/InformacionTecnica/<string:numero_inventario>')
def InformacionTecnica(numero_inventario):
    db     = get_connection()
    equipo = ModelEquipos.obtener_equipo(db, numero_inventario)

    if not equipo:
        db.close()
        flash('Equipo no encontrado', 'warning')
        return redirect(url_for('equipos.Catalogo'))

    recursos = ModelRecursos.get_recursos_por_equipo(
        db, equipo['id'], categoria='ficha_tecnica'
    )
    db.close()

    return render_template('UserC/Recursos/Info_tecnica_user.html',
        equipo=equipo,
        fichas=recursos
    )


@equipos_bp.route('/Manuales/<string:numero_inventario>')
def Manuales(numero_inventario):
    db     = get_connection()
    equipo = ModelEquipos.obtener_equipo(db, numero_inventario)

    if not equipo:
        db.close()
        flash('Equipo no encontrado', 'warning')
        return redirect(url_for('equipos.Catalogo'))

    manuales_servicio = ModelRecursos.get_recursos_por_equipo(
        db, equipo['id'], categoria='manual_servicio'
    )
    manuales_usuario = ModelRecursos.get_recursos_por_equipo(
        db, equipo['id'], categoria='manual_usuario'
    )
    db.close()

    return render_template('UserC/Recursos/Manuales_user.html',
        equipo=equipo,
        manuales_servicio=manuales_servicio,
        manuales_usuario=manuales_usuario
    )


@equipos_bp.route('/ProgramaMantenimiento')
def ProgramaMantenimiento():
    return "Programa de Mantenimiento"


@equipos_bp.route('/Capacitacion/<string:numero_inventario>')
def Capacitacion(numero_inventario):
    db     = get_connection()
    equipo = ModelEquipos.obtener_equipo(db, numero_inventario)

    if not equipo:
        db.close()
        flash('Equipo no encontrado', 'warning')
        return redirect(url_for('equipos.Catalogo'))

    recursos = ModelRecursos.get_recursos_por_equipo(
        db, equipo['id'], categoria='capacitacion'
    )
    db.close()

    # Separar en el backend para no hacer lógica en Jinja
    videos = [r for r in recursos if r['tipo'] in ('video', 'link')]
    pdfs   = [r for r in recursos if r['tipo'] not in ('video', 'link')]

    return render_template('UserC/Recursos/Capacitacion_user.html',
        equipo=equipo,
        videos=videos,
        pdfs=pdfs
    )


@equipos_bp.route('/Capacitacion/<string:numero_inventario>/modulo-bombas-infusion-mindray-evp')
def ModuloBombasInfusionMindrayEVP(numero_inventario):
    """Módulo interactivo de capacitación — bomba de infusión Mindray BeneFusion eVP.
    Demo: el contenido es el mismo para todos los equipos por ahora (no depende de la BD)."""
    db     = get_connection()
    equipo = ModelEquipos.obtener_equipo(db, numero_inventario)
    db.close()

    if not equipo:
        flash('Equipo no encontrado', 'warning')
        return redirect(url_for('equipos.Catalogo'))

    return render_template('UserC/Recursos/modulo-bombas-infusion-mindray-evp.html',
        equipo=equipo
    )


@equipos_bp.route('/Catalogo/<string:numero_inventario>/toggle-nfc', methods=['POST'])
@requiere_rol(ROL_BIOMEDICO)
def ToggleNfc(numero_inventario):
    """
    Activa/desactiva el chip NFC de un equipo.
    Es una escritura sobre el inventario, así que exige perfil Biomédico:
    antes bastaba con estar autenticado y cualquier usuario de consulta
    podía marcar equipos como etiquetados.
    """
    db = None
    try:
        db = get_connection()
        nuevo_valor = ModelEquipos.toggle_nfc(db, numero_inventario)

        if nuevo_valor is None:
            return jsonify({'error': 'Error al actualizar'}), 500

        return jsonify({'tiene_nfc': nuevo_valor})
    finally:
        if db:
            db.close()

