from urllib.parse import urlparse

from flask import (
    Blueprint, current_app, flash, redirect,
    render_template, request, session, url_for
)
from flask_login import login_required, login_user, logout_user

from database.db import get_connection
from models.ModelUser import ModelUser
from models.entities.decorators import (
    ROL_ADMIN, ROL_BIOMEDICO, ROL_USUARIO,
    etiqueta_rol, tiene_rol,
)

auth_bp = Blueprint('auth', __name__)


# ✅ Se obtiene una conexión por request, no una global que queda abierta
def get_db():
    return get_connection()


# ── Helpers de plantilla ─────────────────────────────────────────────
# Se registran desde este blueprint con `app_context_processor` para que
# estén disponibles en todas las plantillas sin tocar app.py.

@auth_bp.app_context_processor
def inyectar_helpers_de_rol():
    return {
        'puede':         tiene_rol,
        'etiqueta_rol':  etiqueta_rol,
        'ROL_USUARIO':   ROL_USUARIO,
        'ROL_BIOMEDICO': ROL_BIOMEDICO,
        'ROL_ADMIN':     ROL_ADMIN,
    }


def _destino_seguro(destino):
    """
    Valida el parámetro ?next= antes de redirigir.

    Solo se aceptan rutas relativas de este mismo sitio. Sin esta
    comprobación, un enlace tipo /login?next=https://sitio-falso sería un
    open redirect: el usuario se autentica de verdad y acaba en otra parte.
    """
    if not destino or not destino.startswith('/') or destino.startswith('//'):
        return None
    if '\\' in destino:
        return None
    partes = urlparse(destino)
    if partes.scheme or partes.netloc:
        return None
    return destino


def _pantalla_inicial():
    """
    A dónde va cada perfil tras iniciar sesión: Biomédico y Administrador
    aterrizan en su pantalla de trabajo, el Usuario en el catálogo.
    Se llama después de login_user(), así que current_user ya está resuelto.
    """
    if tiene_rol(ROL_BIOMEDICO):
        return url_for('admin.ver_inventario')
    return url_for('equipos.Catalogo')


@auth_bp.route('/')
def index():
    return redirect(url_for('equipos.Catalogo'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        # Validación básica
        if not email or not password:
            flash("Por favor ingresa correo y contraseña.")
            return redirect(url_for('auth.login'))

        db = None
        try:
            db = get_db()
            logged_user = ModelUser.login(db, email, password)

            if logged_user is not None:
                login_user(logged_user)
                current_app.logger.info(
                    '[Login OK] usuario=%s rol=%s ip=%s',
                    logged_user.IDusuario, logged_user.Permiso, request.remote_addr
                )

                destino = _destino_seguro(request.args.get('next'))
                return redirect(destino or _pantalla_inicial())

            current_app.logger.warning(
                '[Login fallido] email=%s ip=%s', email, request.remote_addr
            )
            flash("Correo o contraseña incorrectos.")
            return redirect(url_for('auth.login'))

        except Exception as ex:
            current_app.logger.error(f"Error en login route: {ex}")
            flash("Error interno. Intenta de nuevo.")
            return redirect(url_for('auth.login'))

        finally:
            if db:
                db.close()

    # GET request
    return render_template('auth/login.html')


@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    """
    POST y no GET: por GET, cualquier página externa podía cerrar la sesión
    del usuario con un simple <img src="/logout">. Al ser POST pasa por la
    validación CSRF que ya tiene la aplicación.
    """
    logout_user()
    session.clear()
    return redirect(url_for('auth.login'))
