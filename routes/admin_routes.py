from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from flask_login import login_required, current_user
from models.entities.User import User
from database.db import get_connection
from models.entities.Utils import verificar_permiso

admin_bp = Blueprint('admin', __name__)
db = get_connection()


# ── Gestión de Inventario ──────────────────────────────────────

@admin_bp.route('/inventario')
@login_required
def ver_inventario():
    return render_template('admin/inventario.html')


@admin_bp.route('/inventario/agregar')
@login_required
def agregar_equipo():
    return render_template('admin/agregar_equipo.html')


@admin_bp.route('/inventario/categorias')
@login_required
def categorias():
    return render_template('admin/categorias.html')

# ── Usuarios ───────────────────────────────────────────────────

@admin_bp.route('/usuarios')
@login_required
def usuarios():
    return render_template('admin/usuarios.html')




