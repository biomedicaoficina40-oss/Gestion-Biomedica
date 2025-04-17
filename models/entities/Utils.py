# utils.py o decorators.py
from functools import wraps
from flask import session, flash, redirect, url_for
from database.db import get_connection

db = get_connection()

def verificar_permiso(*permisos_permitidos):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Verificar si el usuario ha iniciado sesión
            user_id = session.get('user_id')
            if not user_id:
                flash("Debes iniciar sesión para acceder a esta página.", "error")
                return redirect(url_for('auth.login'))
            
            try:
                with db.cursor() as cursor:
                    sql = """
                    SELECT 
                        Permiso
                    FROM dbo.usuario 
                    WHERE IDusuario = ?
                    """
                    
                    cursor.execute(sql, (user_id,))
                    row = cursor.fetchone()
                    
                    if row:
                        # Obtener el permiso del usuario desde la consulta
                        session['permiso'] = row[0]
                    else:
                        flash("Permiso no encontrado.", "error")
                        return redirect(url_for('auth.login'))

            except Exception as e:
                # Use logging instead of print for better error tracking
                import logging
                logging.error(f"Error al obtener permisos: {str(e)}")
                flash("Error interno del servidor.", "error")
                return redirect(url_for('auth.login'))

            # Obtener el permiso del usuario desde la sesión
            permiso_usuario = session.get('permiso')
            
            # Verificar si el permiso del usuario coincide con alguno de los permisos permitidos
            if not any(str(permiso_usuario).lower().strip() == str(permiso).lower().strip() for permiso in permisos_permitidos):
                flash("No tienes permiso para acceder a esta página.", "error")
                return redirect(url_for('equipos.Catalogo'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator
