from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from models.ModelUser import ModelUser
from models.entities.User import User
from database.db import get_connection


auth_bp = Blueprint('auth', __name__)


# ✅ Se obtiene una conexión por request, no una global que queda abierta
def get_db():
    return get_connection()


@auth_bp.route('/')
def index():
    return redirect(url_for('equipos.Catalogo'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        # Validación básica
        if not email or not password:
            flash("Por favor ingresa correo y contraseña.")
            return redirect(url_for('auth.login'))

        db = None
        try:
            db = get_db()

            # Crear usuario temporal para validación
            user_temp = User(0, "", password, email=email)
            logged_user = ModelUser.login(db, user_temp)

            if logged_user is not None:
                login_user(logged_user)

                # Redirección según permisos
                if logged_user.Permiso == 'Total':
                    return redirect(url_for('auth.index'))
                else:
                    return redirect(url_for('equipos.Catalogo'))
            else:
                flash("Correo o contraseña incorrectos.")
                return redirect(url_for('auth.login'))

        except Exception as ex:
            print(f"Error en login route: {str(ex)}")
            flash("Error interno. Intenta de nuevo.")
            return redirect(url_for('auth.login'))

        finally:
            if db:
                db.close()

    # GET request
    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for('auth.login'))








 

    