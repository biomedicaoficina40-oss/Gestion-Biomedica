from flask import Flask, url_for, redirect
from flask_wtf.csrf import CSRFProtect
from flask_login import LoginManager
from config import config
from datetime import timedelta

# Models
from models.ModelUser import ModelUser
from database.db import get_connection

# Inicializar extensiones (sin app todavía)
csrf = CSRFProtect()
login_manager_app = LoginManager()

def create_app():
    # Crear la aplicación
    app = Flask(__name__)
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = timedelta(days=30)
    # Configuración
    app.config.from_object(config['development'])
    # Asegúrate de que tu config tenga SECRET_KEY, si no:
    if not app.config.get('SECRET_KEY'):
        app.config['SECRET_KEY'] = '4a3b1c7e5d2f8b9d3e7f6a4c3d8e9b7f'
    
    # Inicializar extensiones CON la app
    csrf.init_app(app)
    login_manager_app.init_app(app)
    login_manager_app.login_view = 'auth.login'
    
    # Obtener conexión a DB DESPUÉS de configurar la app
    db = get_connection()
    
    # User loader callback
    @login_manager_app.user_loader
    def load_user(id):
        return ModelUser.get_by_id(db, id)
    
    # Registrar los blueprints
    from routes.auth_routes import auth_bp
    from routes.admin_routes import admin_bp
    from routes.Catalogo_routes import equipos_bp
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(equipos_bp)
    
    # Manejadores de error
    @app.errorhandler(401)
    def status_401(error):
        return redirect(url_for('auth.login'))
    
    @app.errorhandler(404)
    def status_404(error):
        return "<h1>Página no encontrada</h1>", 404
    
    return app

if __name__ == '__main__':
    app = create_app()
    app.run(host="0.0.0.0", port=300,debug=True)