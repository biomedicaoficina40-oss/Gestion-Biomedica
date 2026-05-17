from flask import Flask, url_for, redirect
from flask_wtf.csrf import CSRFProtect
from flask_login import LoginManager
from config import config
from datetime import timedelta
import os

# APScheduler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import atexit

# Models
from models.ModelUser import ModelUser
from database.db import get_connection

# Extensiones (sin app todavía)
csrf = CSRFProtect()
login_manager_app = LoginManager()

# Referencia global — la asigna create_app() para que el job la use
_app_instance = None


def _job_purgar_lecturas():
    """
    Job de purga diaria de ble_lecturas.
    Corre fuera del contexto de request — crea su propio
    app context y conexión a BD.
    """
    from models.ModelBLE import ModelBLE

    global _app_instance
    if _app_instance is None:
        return

    with _app_instance.app_context():
        db = None
        try:
            db = get_connection()
            eliminados = ModelBLE.purgar_lecturas_antiguas(db, dias=30)
            _app_instance.logger.info(
                f"[Scheduler/purga] {eliminados} lecturas eliminadas "
                f"(antigüedad > 30 días)"
            )
        except Exception as e:
            _app_instance.logger.error(f"[Scheduler/purga] Error: {e}")
        finally:
            if db:
                db.close()


def create_app():
    # ── Crear la aplicación ──────────────────────────────────
    app = Flask(__name__)
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = timedelta(days=30)

    # Configuración
    app.config.from_object(config['development'])

    if not app.config.get('SECRET_KEY'):
        app.config['SECRET_KEY'] = '4a3b1c7e5d2f8b9d3e7f6a4c3d8e9b7f'

    # ── Extensiones ──────────────────────────────────────────
    csrf.init_app(app)
    login_manager_app.init_app(app)
    login_manager_app.login_view = 'auth.login'

    # ── User loader ──────────────────────────────────────────
    @login_manager_app.user_loader
    def load_user(id):
        db   = get_connection()
        user = ModelUser.get_by_id(db, id)
        db.close()
        return user

    # ── Blueprints ───────────────────────────────────────────
    from routes.auth_routes import auth_bp
    from routes.admin_routes import admin_bp
    from routes.Catalogo_routes import equipos_bp
    from routes.ble_routes import ble_bp

    # En create_app(), después de registrar blueprints
    from routes.ble_routes import (
        api_purgar_lecturas_manual,
        ping,
        recibir_lecturas
    )
    csrf.exempt(api_purgar_lecturas_manual)
    csrf.exempt(ping)
    csrf.exempt(recibir_lecturas)

    app.register_blueprint(ble_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(equipos_bp)

    # ── Filtros Jinja2 ───────────────────────────────────────
    import re

    def get_youtube_id(url):
        m = re.search(r'(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})', url or '')
        return m.group(1) if m else ''

    app.jinja_env.filters['youtube_id'] = get_youtube_id

    # ── Manejadores de error ─────────────────────────────────
    @app.errorhandler(401)
    def status_401(error):
        return redirect(url_for('auth.login'))

    @app.errorhandler(404)
    def status_404(error):
        return "<h1>Página no encontrada</h1>", 404

    # ── Referencia global para el job ────────────────────────
    global _app_instance
    _app_instance = app

    # ── APScheduler — purga diaria a las 03:00 ───────────────
    # Guard necesario: en modo debug Werkzeug arranca 2 procesos,
    # sin esto el scheduler se registraría dos veces.
    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        scheduler = BackgroundScheduler(timezone="America/Cancun")
        scheduler.add_job(
            func             = _job_purgar_lecturas,
            trigger          = CronTrigger(hour=3, minute=0),
            id               = 'purga_ble_lecturas',
            name             = 'Purga diaria ble_lecturas',
            replace_existing = True,
        )
        scheduler.start()
        app.logger.info(
            "[Scheduler] Purga diaria registrada — 03:00 Cancún"
        )
        # Apagar limpiamente cuando Flask se detenga
        atexit.register(lambda: scheduler.shutdown(wait=False))

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(host="0.0.0.0", port=300, debug=True)