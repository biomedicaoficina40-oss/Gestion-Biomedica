from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_user, logout_user, login_required
from functools import wraps
from models.entities.Utils import verificar_permiso

from models.ModelUser import ModelUser
from models.ModelPerfil import ModelPerfil
from models.ModelAdmin import AdminConsult
from models.entities.User import User
from database.db import get_connection


auth_bp = Blueprint('auth', __name__)
db = get_connection()

@auth_bp.route('/')
def index():
    return redirect(url_for('auth.login'))

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User(0, 0, request.form['password'], 0,0,0,0,request.form['email'],0,0,0)
        logged_user = ModelUser.login(db, user)

        if logged_user != None:
            session['user_id']=logged_user.IDusuario
            session['Carrito_ID']=logged_user.CarritoID
            session['nombre']=logged_user.NombreUsuario
            session['apellido']=logged_user.Apellido
            session['permiso']=logged_user.Permiso

            lu=session.get('Carrito_ID')
            print(logged_user.CarritoID)
            print(lu)
            if logged_user.password:
                login_user(logged_user)
                if session['permiso']=='Administrador':
                    return redirect(url_for('admin.home'))
                else:
                    return redirect(url_for('equipos.Catalogo'))
            else:
                flash("Invalid password...")
                return render_template('auth/login.html')
        else:
            flash("User not found...")
            return render_template('auth/login.html')
    else:
        return render_template('auth/login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        user_data = {
            'nombre': request.form['nombre'],
            'apellido': request.form['apellido'],
            'carrera': request.form['carrera'],
            'telefono': request.form['telefono'],
            'rol': request.form['rol'],
            'email': request.form['email'],
            'password': request.form['password'],
            'confirm_password': request.form['confirm_password']
        }

        if user_data['password'] != user_data['confirm_password']:
            flash("Las contraseñas no coinciden", 'error') 
            return render_template('auth/register.html') 

        hashed_password = User.hash_password(user_data['password'])
        user_data['password'] = hashed_password

        success, message = ModelUser.register(db, user_data)
        if success:
            flash(message, 'success')
            return redirect(url_for('auth.login'))
        else:
            flash(message, 'error')
            return render_template('auth/register.html')
    
    return render_template('auth/register.html')

@auth_bp.route('/logout')
def logout():

    logout_user()
    session.clear()
    return redirect(url_for('auth.login'))

@auth_bp.route('/perfilUsuario')
@login_required
@verificar_permiso('Estudiante', 'Administrador', 'Visitante')
def perfil():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth.login'))
    
    usuario = ModelPerfil.get_user(db, user_id)
    solicitudes_pendientes = ModelPerfil.get_solicitudes_by_status(db, user_id, status= 'pendiente')
    solicitudes_aceptadas = ModelPerfil.get_solicitudes_by_status(db, user_id, status= 'activo')
    solicitudes_rechazadas = ModelPerfil.get_solicitudes_by_status(db, user_id, status= 'eliminado')
    
    return render_template('UserC/UsuarioPerfil.html',
                         usuario=usuario,
                         solicitudes_pendientes=solicitudes_pendientes,
                         solicitudes_aceptadas=solicitudes_aceptadas,
                         solicitudes_rechazadas=solicitudes_rechazadas)

@auth_bp.route('/editar_perfil', methods=['GET', 'POST'])
@login_required
@verificar_permiso('Estudiante', 'Administrador', 'Visitante')
def editar_perfil():
    user_id = session.get('user_id')
    if request.method == 'POST':
        datos_actualizados = {
            'nombre': request.form['nombre'],
            'apellido': request.form['apellido'],
            'carrera': request.form['carrera'],
            'telefono': request.form['telefono'],
            'email': request.form['email']
        }
        
        # Manejo de la imagen de perfil
        imagen = request.files.get('imagen')
        imagen_url = None
        if imagen and imagen.filename:  # Asegúrate de que se haya seleccionado un archivo
            try:
                imagen_url = AdminConsult.guardar_imagen(imagen, flag='Usuarios')
            except ValueError as e:
                flash(str(e), 'danger')
                return redirect(url_for('admin.Inventario'))
        
        success = ModelUser.update_profile(db, user_id, datos_actualizados)
        if success:
            flash('Perfil actualizado exitosamente', 'success')
            return redirect(url_for('usuarios.perfil'))
        else:
            flash('Error al actualizar el perfil', 'error')
    
    usuario = ModelUser.get_by_id(db, user_id)
    return render_template('usuarios/editar_perfil.html', usuario=usuario)

@auth_bp.route('/Editar/<int:solicitud_id>')
@login_required
@verificar_permiso('Estudiante', 'Administrador')
def editar_solicitud(solicitud_id):
    solicitud = ModelPerfil.Get_oneSolicitud_by_id(db, solicitud_id)
    if solicitud: 
        return render_template('UserC/Editar_solicitud.html', solicitud=solicitud)
    flash('No tienes permiso para editar esta solicitud', 'error')
    return redirect(url_for('auth.perfil'))


@auth_bp.route('/ActualizarSolicitud', methods=['POST'])
@login_required
@verificar_permiso('Estudiante', 'Administrador')
def actualizar_solicitud():
    if request.method == 'POST':
        # Extraer datos del formulario
        IDsolicitud = request.form.get('solicitud_id')
        motivo = request.form.get('motivo')
        fecha_inicio = request.form.get('fecha_inicio')
        fecha_entrega = request.form.get('fecha_entrega')
        profesor = request.form.get('profesor')
        materia = request.form.get('materia')

        try:
            # Preparar la consulta de actualización
            with db.cursor() as cursor:
                query =   """
                        UPDATE [sistema_de_prestamo].[dbo].[solicitudesPrestamo]
                        SET Motivo = ?, FechaInicio = ?, FechaEntrega = ?, Profesor = ?, Materia = ?
                        WHERE IDsolicitud = ?
                        """
                
                # Ejecutar la consulta
                cursor.execute(query, (
                    motivo,
                    fecha_inicio,
                    fecha_entrega,   
                    profesor,
                    materia,
                    IDsolicitud
                ))
                
                # Confirmar la transacción
                db.commit()
            
            # Mensaje de éxito
            flash('Solicitud actualizada exitosamente', 'success')
            return redirect(url_for('auth.perfil'))
        
        except Exception as e:
            # Revertir transacción en caso de error
            db.rollback()
            
            # Imprimir error para depuración
            print(f"Error al actualizar la solicitud: {str(e)}")
            
            # Mensaje de error al usuario
            flash(f'Error al actualizar la solicitud: {str(e)}', 'danger')
            return redirect(url_for('auth.editar_solicitud'))
    
    # Si se accede por GET, redirigir al catálogo
    
@auth_bp.route('/Cancelar/<int:solicitud_id>')
@login_required
@verificar_permiso('Estudiante', 'Administrador')
def cancelar_solicitud(solicitud_id):
    if ModelPerfil.cancelar(db, solicitud_id, session.get('user_id')):
        flash('Solicitud cancelada exitosamente', 'success')
    else:
        flash('Error al cancelar la solicitud', 'error')
    return redirect(url_for('usuarios.perfil'))

@auth_bp.route('/Devolver/<int:solicitud_id>')
@login_required
@verificar_permiso('Estudiante', 'Administrador')
def devolver_equipo(solicitud_id):

    if ModelPerfil.devolver(db, solicitud_id):
        flash('Equipo devuelto exitosamente', 'success')
    else:
        flash('Error al devolver el equipo', 'error')
    return redirect(url_for('auth.perfil'))

@auth_bp.route('/Eliminar/<int:solicitud_id>')
@login_required
@verificar_permiso('Estudiante', 'Administrador')
def eliminar_solicitud(solicitud_id):
    if ModelPerfil.eliminar(db, solicitud_id, session.get('user_id')):
        flash('Solicitud eliminada exitosamente', 'success')
    else:
        flash('Error al eliminar la solicitud', 'error')
    return redirect(url_for('usuarios.perfil'))

@auth_bp.route('/Carrito')
@login_required
@verificar_permiso('Estudiante', 'Administrador')
def Carrito():
    Carr = session.get('Carrito_ID')
    
    try:
        carrito = ModelPerfil.equipos_carrito(db, Carr)
        estado_carrito = ModelPerfil.get_cart_status(db, Carr)
        
        # Calculate cart count
        carrito_count = 0
        if isinstance(carrito, list):  # Check if carrito is a list of items
            carrito_count = len(carrito)
        
        # Store cart count in session to make it available globally
        session['carrito_count'] = carrito_count

        return render_template('UserC/Carrito.html', 
                             carrito=carrito, 
                             estado_carrito=estado_carrito,
                             carrito_count=carrito_count)
    
    except Exception as e:
        print(f"Error al obtener los datos del carrito: {e}")
        session['carrito_count'] = 0
        return render_template('UserC/Carrito.html', 
                             carrito=[], 
                             estado_carrito='Error',
                             carrito_count=0)
@auth_bp.route('/solicitar_todo_carrito')
@login_required
@verificar_permiso('Estudiante', 'Administrador')
def Carrito_solicitud():

    carrito_id = session.get('Carrito_ID')
    cursor = db.cursor()
    if carrito_id:
        # Realizar la consulta para cambiar el estado del carrito
        cursor.execute("""
            UPDATE CarritoPedidos
            SET estado = 'Pendiente'
            WHERE CarritoID = ?
        """, (carrito_id,))
        
        # Confirmar los cambios
        db.commit()
        
        # Cerrar la conexión
        cursor.close()
  
        
        flash('La solicitud ha sido enviada', 'success')
        return redirect(url_for('auth.Carrito'))
    else:
        flash('No hay un carrito activo en la sesión.', 'warning')

    # Redirigir a la página del carrito (o a donde prefieras)
        return redirect(url_for('auth.Carrito'))
    
@auth_bp.route('/cancelar_solicitud_carrito')
@login_required
@verificar_permiso('Estudiante', 'Administrador')
def Carrito_CancelarSolicitud():
    carrito_id = session.get('Carrito_ID')
    cursor = db.cursor()
    try:
        if carrito_id:
            # Realizar la consulta para cambiar el estado del carrito
            cursor.execute("""
                UPDATE CarritoPedidos
                SET estado = 'En Carrito'
                WHERE CarritoID = ?
            """, (carrito_id,))
            
            # Confirmar los cambios
            db.commit()
            
            # Cerrar la conexión
            cursor.close()
            
            flash('La solicitud ha sido cancelada y el carrito está "En Carrito".', 'success')
            return redirect(url_for('auth.Carrito'))
        else:
            flash('No hay un carrito activo en la sesión.', 'warning')
            return redirect(url_for('auth.Carrito'))
    except Exception as e:
        # Manejo de errores
        db.rollback()  # Deshacer cambios si ocurre un error
        flash(f'Error al procesar la solicitud: {str(e)}', 'danger')
        return redirect(url_for('auth.Carrito'))
    