from flask import Blueprint, render_template, jsonify, request, current_app, redirect, url_for, flash, session
from flask_login import login_required, current_user
from datetime import datetime
from models.ModelCatalogo import ModelEquipos
from database.db import get_connection
from models.entities.Utils import verificar_permiso

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

@equipos_bp.route('/GuiasRapidas')
def GuiasRapidas():
    return "Guías Rápidas"

@equipos_bp.route('/tarjeta')
def prueba():
    return render_template('UserC/prueba.html')


@equipos_bp.route('/InformacionTecnica')
def InformacionTecnica():
    return "Información Técnica"


@equipos_bp.route('/ManualServicio')
def ManualServicio():
    return "Manual de Servicio"


@equipos_bp.route('/ManualUsuario')
def ManualUsuario():
    return "Manual de Usuario"


@equipos_bp.route('/ProgramaMantenimiento')
def ProgramaMantenimiento():
    return "Programa de Mantenimiento"


@equipos_bp.route('/Capacitacion')
def Capacitacion():
    return "Capacitación"

















    


