from flask import Blueprint, render_template, jsonify, request, current_app,redirect,url_for,flash,session
from flask_login import login_required, current_user
from datetime import datetime
from models.ModelCatalogo import ModelEquipos
from models.ModelAdmin import AdminConsult
from database.db import get_connection
from models.entities.Utils import verificar_permiso

equipos_bp = Blueprint('equipos', __name__)
db = get_connection()

@equipos_bp.route('/Catalogo', methods=['GET', 'POST'])
@login_required
def Catalogo():
    try:
        # Obtener el filtro de los parámetros URL
        filtro = request.args.get('filtro', 'todos')
        
        # Obtener conexión a la base de datos
        with get_connection() as db:
            # Obtener equipos según el filtro
            equipos = ModelEquipos.obtener_equipos(db, filtro)
            
            return render_template(
                'UserC/Catalogo.html',
                equipos=equipos,
                filtro=filtro  # Pasar el filtro actual a la plantilla
            )
    except Exception as e:
        current_app.logger.error(f"Error en catálogo: {str(e)}")
        return render_template('error.html', mensaje="Error al cargar el catálogo")
    


@equipos_bp.route('/agregar-carrito/<int:IDequipo>', methods=['GET', 'POST'])
def agregar_carrito(IDequipo):

    try:
        # Obtener CarritoID de la sesión
        CarritoID = session.get('Carrito_ID')
        
        # Verificar si existe el CarritoID
        if CarritoID is None:
            flash('No se ha encontrado un carrito activo.', 'error')
            return redirect(url_for('equipos.Catalogo'))

        # Obtener conexión a la base de datos
        with get_connection() as db:
            with db.cursor() as cursor:
                # Verificar si el equipo está disponible
                check_query = """
                SELECT Estado 
                FROM sistema_de_prestamo.dbo.equiposLab 
                WHERE IDequipo = ?
                """
                cursor.execute(check_query, [IDequipo])
                result = cursor.fetchone()
                
                if not result:
                    flash('El equipo no existe.', 'error')
                    return redirect(url_for('equipos.Catalogo'))
                
                if result[0] != 'Disponible':
                    flash('El equipo no está disponible.', 'error')
                    return redirect(url_for('equipos.Catalogo'))
                
                # Verificar si el equipo ya está en el carrito
                check_cart_query = """
                SELECT COUNT(*) 
                FROM sistema_de_prestamo.dbo.EquiposCarrito 
                WHERE CarritoID = ? AND IDequipo = ?
                """
                cursor.execute(check_cart_query, [CarritoID, IDequipo])
                if cursor.fetchone()[0] > 0:
                    flash('El equipo ya está en el carrito.', 'info')
                    return redirect(url_for('equipos.Catalogo'))
                
                # Insertar el equipo en el carrito
                insert_query = """
                INSERT INTO sistema_de_prestamo.dbo.EquiposCarrito 
                (CarritoID, IDequipo, quantity) 
                VALUES (?, ?, 1)
                """
                cursor.execute(insert_query, [CarritoID, IDequipo])
                db.commit()
                
                flash('Equipo agregado al carrito exitosamente.', 'success')
                current_app.logger.info(f'Equipo {IDequipo} agregado al carrito {CarritoID}')
                return redirect(url_for('equipos.Catalogo'))

    except Exception as e:
        current_app.logger.error(f"Error al agregar equipo al carrito: {str(e)}", exc_info=True)
        flash('Error al agregar el equipo al carrito. Por favor, intente nuevamente.', 'error')
        return redirect(url_for('equipos.Catalogo'))
    if success:
        return '', 200  # Success
    return '', 400  # Error

@equipos_bp.route('/quitar-carrito/<int:IDequipo>', methods=['GET', 'POST'])
def quitar_carrito(IDequipo):
    """
    Quita un equipo del carrito del usuario.
    
    Args:
        IDequipo (int): ID del equipo a quitar
    """
    # Guardar la URL de origen
    return_url = request.referrer or url_for('equipos.Catalogo')
    
    try:
        # Obtener CarritoID de la sesión
        CarritoID = session.get('Carrito_ID')
        
        # Verificar si existe el CarritoID
        if CarritoID is None:
            flash('No se ha encontrado un carrito activo.', 'error')
            return redirect(return_url)

        # Obtener conexión a la base de datos
        with get_connection() as db:
            with db.cursor() as cursor:
                # Verificar si el equipo está en el carrito
                check_cart_query = """
                SELECT COUNT(*) 
                FROM sistema_de_prestamo.dbo.EquiposCarrito 
                WHERE CarritoID = ? AND IDequipo = ?
                """
                cursor.execute(check_cart_query, [CarritoID, IDequipo])
                if cursor.fetchone()[0] == 0:
                    flash('El equipo no está en el carrito.', 'error')
                    return redirect(return_url)
                
                # Eliminar el equipo del carrito
                delete_query = """
                DELETE FROM sistema_de_prestamo.dbo.EquiposCarrito 
                WHERE CarritoID = ? AND IDequipo = ?
                """
                cursor.execute(delete_query, [CarritoID, IDequipo])
                db.commit()
                
                flash('Equipo quitado del carrito exitosamente.', 'success')
                current_app.logger.info(f'Equipo {IDequipo} quitado del carrito {CarritoID}')
                return redirect(return_url)

    except Exception as e:
        current_app.logger.error(f"Error al quitar equipo del carrito: {str(e)}", exc_info=True)
        flash('Error al quitar el equipo del carrito. Por favor, intente nuevamente.', 'error')
        return redirect(return_url)

@equipos_bp.route('/solicitar/<string:IDequipo>', methods=['GET'])
@login_required
@verificar_permiso('Estudiante', 'Administrador')
def solicitar_equipo(IDequipo):
    
    equipo = ModelEquipos.obtener_equipo(db,IDequipo)
    return render_template( 'UserC/Solicitar_equipo.html',equipo=equipo)

@equipos_bp.route('/enviar_solicitud', methods=['GET', 'POST'])
@login_required
@verificar_permiso('Estudiante', 'Administrador')
def enviar_solicitud():
    if request.method == 'POST':
        # Extraer datos del formulario
        equipo_id = request.form.get('equipo_id')
        print('El id del equipo es:')
        print(equipo_id)
        motivo = request.form.get('motivo')
        fecha_inicio = request.form.get('fecha_inicio')
        fecha_entrega = request.form.get('fecha_entrega')
        profesor=request.form.get('profesor')
        materia=request.form.get('materia')
        
        # Obtener información del usuario de la sesión
        IDusuario = session.get('user_id')
        NombreUsuario = f"{session.get('nombre')} {session.get('apellido')}"
        try:
            # Obtener el nombre del equipo
            with db.cursor() as cursor:
                # Consulta para obtener el nombre del equipo
                cursor.execute("""
                    SELECT Nombre
                    FROM [sistema_de_prestamo].[dbo].[equiposLab] 
                    WHERE IDequipo = ?
                """, (equipo_id,))
                equipo = cursor.fetchone()
                NombreEquipo = equipo[0] if equipo else 'Equipo Desconocido'
            
            # Preparar la consulta de inserción
            with db.cursor() as cursor:
                query = """
                INSERT INTO [sistema_de_prestamo].[dbo].[solicitudesPrestamo] 
                (IDequipo, NombreEquipo, IDusuario, NombreUsuario, 
                FechaSolicitud, Motivo, FechaInicio, FechaEntrega, Estado, Profesor, Materia)
                VALUES (?, ?, ?, ?, CAST(GETDATE() AS DATE), ?, ?, ?, 'Pendiente', ?, ?)
                """
                
                # Ejecutar la consulta
                cursor.execute(query, (
                    equipo_id, 
                    NombreEquipo, 
                    IDusuario, 
                    NombreUsuario, 
                    motivo, 
                    fecha_inicio, 
                    fecha_entrega,
                    profesor,
                    materia
                ))
                
                # Confirmar la transacción
                db.commit()
            
            # Mensaje de éxito
            flash('Solicitud enviada exitosamente', 'success')
            return redirect(url_for('equipos.Catalogo'))
        
        except Exception as e:
            # Revertir transacción en caso de error
            db.rollback()
            
            # Imprimir error para depuración
            print(f"Error al enviar solicitud: {str(e)}")
            
            # Mensaje de error al usuario
            
            flash(f'Error al enviar la solicitud: {str(e)}', 'danger')
            return redirect(url_for('equipos.Catalogo'))
    
    # Si se accede por GET, redirigir al catálogo
    return redirect(url_for('equipos.Catalogo'))


@equipos_bp.route('/solicitarAccesoMenu', methods=['GET'])
@login_required
def solicitar_accesoMenu():
    
    return render_template( 'UserC/SolicitarAcceso.html')

@equipos_bp.route('/SolicitarAcceso', methods=['GET', 'POST'])
@login_required
def Solicitar_Acceso():
    if request.method == 'POST':
        # Extraer datos del formulario
        motivo = request.form.get('motivo')
        imagen = request.files.get('imagen')
        NombreUsuario = f"{session.get('nombre')} {session.get('apellido')}"
        # Obtener información del usuario de la sesión
        IDusuario = session.get('user_id')
        imagen_url = None

        if imagen and imagen.filename:  # Asegúrate de que se haya seleccionado un archivo
            try:
                imagen_url = AdminConsult.guardar_imagen(imagen, flag='Usuarios')
            except ValueError as e:
                flash(str(e), 'danger')
                return redirect(url_for('equipos.solicitar_accesoMenu'))
        
        try:
            # Preparar las consultas de inserción
            with db.cursor() as cursor:
                # Primera consulta: Insertar solicitud con motivo
                query_solicitud = """
                INSERT INTO [sistema_de_prestamo].[dbo].[SolicitudesDeAcceso]
                (IDusuario, NombreUsuario, Motivo, Estado)
                VALUES (?, ?, ?, 'Acceso')

                """
                cursor.execute(query_solicitud, (IDusuario, NombreUsuario, motivo,))
                
                # Segunda consulta: Actualizar imagen del usuario si existe
                if imagen_url:
                    query_imagen = """
                    UPDATE [sistema_de_prestamo].[dbo].[usuario]
                    SET Imagen = ?
                    WHERE IDusuario = ?
                    """
                    cursor.execute(query_imagen, (imagen_url, IDusuario))
                
                # Confirmar la transacción
                db.commit()
            
            # Mensaje de éxito
            flash('Solicitud enviada exitosamente', 'success')
            return redirect(url_for('equipos.Catalogo'))
        
        except Exception as e:
            # Revertir transacción en caso de error
            db.rollback()
            
            # Imprimir error para depuración
            print(f"Error al enviar solicitud: {str(e)}")
            
            # Mensaje de error al usuario
            flash(f'Error al enviar la solicitud: {str(e)}', 'danger')
            return redirect(url_for('equipos.Catalogo'))
    
    # Si se accede por GET, redirigir al catálogo
    return redirect(url_for('equipos.Catalogo'))















    


