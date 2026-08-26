"""
Control de acceso por rol — fuente única de verdad de la autorización.

Jerarquía (cada nivel incluye los permisos del anterior):

    Usuario (1)        Solo consulta. Ve equipos, catálogo, mantenimientos
                       y localización, pero no modifica nada.

    Biomedico (2)      Operación. Da de alta y edita equipos, sube recursos,
                       gestiona mantenimientos, áreas, beacons y reglas de
                       localización. No toca la administración de usuarios.

    Administrador (3)  Todo, incluida la gestión de usuarios y las acciones
                       destructivas (bajas de equipo, purga de lecturas).

Uso en rutas:

    @admin_bp.route('/inventario')
    @requiere_rol(ROL_USUARIO)          # Usuario o superior
    def ver_inventario(): ...

Uso en plantillas (inyectado por el context processor de auth_routes):

    {% if puede(ROL_BIOMEDICO) %} ... {% endif %}
"""

from functools import wraps
import unicodedata

from flask import current_app, flash, jsonify, redirect, request, url_for
from flask_login import current_user


# ── Roles ────────────────────────────────────────────────────────────
# Se guardan en BD sin acento para evitar problemas de collation y de
# codificación al escribir desde distintos clientes.
ROL_USUARIO    = 'Usuario'
ROL_BIOMEDICO  = 'Biomedico'
ROL_ADMIN      = 'Administrador'

ROLES_VALIDOS = (ROL_USUARIO, ROL_BIOMEDICO, ROL_ADMIN)

# Cómo se muestra cada rol en pantalla (aquí sí con acento).
ETIQUETAS_ROL = {
    ROL_USUARIO:   'Usuario',
    ROL_BIOMEDICO: 'Biomédico',
    ROL_ADMIN:     'Administrador',
}

_JERARQUIA = {
    'usuario':       1,
    'biomedico':     2,
    'administrador': 3,
}


def _normalizar(valor):
    """Minúsculas y sin acentos, para que 'Biomédico' y 'Biomedico' coincidan."""
    if not valor:
        return ''
    txt = unicodedata.normalize('NFKD', str(valor).strip())
    return ''.join(c for c in txt if not unicodedata.combining(c)).lower()


def _nivel(permiso):
    """
    Nivel numérico del rol. Un valor desconocido o vacío devuelve 0, es decir
    por debajo de Usuario: se deniega todo. Es intencional — si algún registro
    quedó con un Permiso heredado ('Total', 'Visitante', NULL), preferimos que
    no pueda entrar a nada antes que concederle acceso por accidente.
    """
    return _JERARQUIA.get(_normalizar(permiso), 0)


def etiqueta_rol(permiso):
    """Nombre presentable del rol; si es desconocido, lo devuelve tal cual."""
    for rol in ROLES_VALIDOS:
        if _normalizar(rol) == _normalizar(permiso):
            return ETIQUETAS_ROL[rol]
    return permiso or 'Sin rol'


def rol_canonico(permiso):
    """
    Devuelve el valor exacto que debe persistirse en BD, o None si el valor
    recibido no corresponde a ningún rol válido. Sirve como lista blanca al
    procesar formularios.
    """
    for rol in ROLES_VALIDOS:
        if _normalizar(rol) == _normalizar(permiso):
            return rol
    return None


def tiene_rol(minimo):
    """True si el usuario autenticado alcanza al menos el rol indicado."""
    return current_user.is_authenticated and _nivel(current_user.Permiso) >= _nivel(minimo)


def _es_peticion_api():
    """
    Distingue las llamadas de JavaScript de la navegación normal, para
    responder con JSON en lugar de un redirect al login (que el fetch()
    recibiría como HTML y no sabría interpretar).
    """
    return (
        request.path.startswith('/api/')
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    )


def requiere_rol(minimo):
    """
    Exige sesión iniciada y rol suficiente.

    Sustituye a @login_required: si no hay sesión delega en Flask-Login para
    conservar el mismo comportamiento de redirección al login.
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                if _es_peticion_api():
                    return jsonify({'error': 'Sesión no iniciada'}), 401
                return current_app.login_manager.unauthorized()

            if not tiene_rol(minimo):
                current_app.logger.warning(
                    '[Acceso denegado] usuario=%s rol=%s ruta=%s requiere=%s',
                    getattr(current_user, 'IDusuario', '?'),
                    getattr(current_user, 'Permiso', '?'),
                    request.path,
                    minimo,
                )
                if _es_peticion_api():
                    return jsonify({
                        'error': 'No tienes permisos para esta acción',
                        'requiere': ETIQUETAS_ROL.get(minimo, minimo),
                    }), 403

                flash(
                    'No tienes permisos para esa sección. '
                    f'Se requiere perfil {ETIQUETAS_ROL.get(minimo, minimo)} o superior.',
                    'error'
                )
                return redirect(url_for('equipos.Catalogo'))

            return f(*args, **kwargs)

        # Queda accesible para auditar la matriz de permisos completa
        # recorriendo app.url_map (ver scripts de verificación).
        wrapper._rol_minimo = minimo
        return wrapper
    return decorator


# Atajos legibles para el caso más común.
solo_usuario   = requiere_rol(ROL_USUARIO)
solo_biomedico = requiere_rol(ROL_BIOMEDICO)
solo_admin     = requiere_rol(ROL_ADMIN)
