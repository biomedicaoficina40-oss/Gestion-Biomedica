from flask import Blueprint, render_template, request,redirect,url_for,session,flash
from flask_login import login_required,current_user
from models.ModelPanel import ModelPanel
from models.ModelAdmin import AdminConsult
from models.entities.User import User
from database.db import get_connection
from models.entities.Utils import verificar_permiso

admin_bp = Blueprint('admin', __name__)
db = get_connection()



# ============================== 
# Ruta del Home 
# ==============================
@admin_bp.route('/home', methods=['GET', 'POST'])
@login_required
@verificar_permiso('Administrador')
def home():
    try:
        if request.method == 'POST':
            estadisticas = ModelPanel.Estadistics_panel(db)
            return render_template('Admin/home.html', **estadisticas)
        else:
            estadisticas = ModelPanel.Estadistics_panel(db)
            return render_template('Admin/home.html', **estadisticas)
            
    except Exception as e:
        print(f"Error: {str(e)}")
        return render_template('Admin/home.html', 
                             pedidos_activos=0,
                             total_solicitudes=0,
                             total_observaciones=0,
                             equipos_disponibles=0)
    
# ============================== 
# Lista pedidos activos 
# ==============================    
@admin_bp.route('/lista_Pedidos', methods=['GET', 'POST'])
@login_required
@verificar_permiso('Administrador')
def ListaPedidos():
    try:
        Pedidos = AdminConsult.PedidosActivos(db)
        return render_template('Admin/PedidosActivos.html', Pedidos=Pedidos)
    except Exception as e:
        print(f"Error: {str(e)}")
        flash('Error al cargar los pedidos', 'error')
        return redirect(url_for('admin.home')) 
    
@admin_bp.route('/delete/<string:IDequipo>/<string:IDsolicitud>', methods=['GET', 'POST'])
@login_required
@verificar_permiso('Administrador')
def DeleteActivo(IDequipo, IDsolicitud):
    try:
        with db.cursor() as cursor:
            # Actualizar solicitud
            sql = """
                UPDATE [sistema_de_prestamo].[dbo].[solicitudesPrestamo]
                SET Estado = 'eliminado'
                WHERE IDsolicitud = ?;
            """
            cursor.execute(sql, (IDsolicitud,))
            
            # Actualizar equipo
            sql1 = """
                UPDATE [sistema_de_prestamo].[dbo].[equiposLab]
                SET Estado = 'Disponible'
                WHERE IDequipo = ?;
            """
            cursor.execute(sql1, (IDequipo,))
            
            db.commit()
            flash('Pedido eliminado exitosamente', 'success')
    except Exception as e:
        db.rollback()
        print(f'Error al eliminar el pedido: {str(e)}')
        flash('Error al eliminar el pedido', 'error')
    
    return redirect(url_for('admin.ListaPedidos'))





# ============================== 
# Lista solicitudes de prestamo
# ==============================  

@admin_bp.route('/lista_solicitudes', methods=['GET', 'POST'])
@login_required
@verificar_permiso('Administrador')
def ListaSolicitudes():
    
    try:
        Solicitudes = AdminConsult.Solicitudes(db)
        SolicitudesAcceso = AdminConsult.SolicitudesAcceso(db)
        # Verificar si hay pedidos activos y manejar la lógica de la respuesta
        return render_template('Admin/ListaSolicitudes.html', Pedidos=Solicitudes, 
                               SolicitudesAcceso=SolicitudesAcceso)

    except Exception as e:
        print(f"Error: {str(e)}")
        return redirect(url_for('admin.home')) 
    
    
@admin_bp.route('/Borrar/<string:IDsolicitud>', methods=['GET', 'POST'])
@login_required
@verificar_permiso('Administrador')
def Deletesolicitud(IDsolicitud):
    
        try:
            cursor = db.cursor()
            
            sql = """
                UPDATE [sistema_de_prestamo].[dbo].[solicitudesPrestamo]
                SET Estado = 'eliminado'
                WHERE IDsolicitud = ?;
                 """
            cursor.execute(sql, (IDsolicitud,))
            db.commit()
            flash('Pedido eliminado exitosamente', 'success')  # Añadido mensaje de éxito
            
        except Exception as e:
            db.rollback()  # Añadido rollback en caso de error
            print(f'Error al eliminar el pedido: {str(e)}')
      
        return redirect(url_for('admin.ListaSolicitudes'))

@admin_bp.route('/Aceptar/<string:IDequipo>/<int:IDsolicitud>', methods=['GET', 'POST'])
@login_required
@verificar_permiso('Administrador')
def acceptsolicitud(IDequipo,IDsolicitud):
    
        try:
            cursor = db.cursor()
            
            sql = """
            UPDATE [sistema_de_prestamo].[dbo].[solicitudesPrestamo]
            SET Estado = 'activo', 
                FechaDeActivacion = CAST(GETDATE() AS DATE)
            WHERE IDsolicitud = ?;

                 """
            cursor.execute(sql, (IDsolicitud,))
            db.commit()

            sql2= """
                UPDATE [sistema_de_prestamo].[dbo].[equiposLab]
                SET Estado = 'En uso'
                WHERE IDequipo = ?;
                 """
            cursor.execute(sql2, (IDequipo,))
            db.commit()
            flash('Pedido Aceptado exitosamente', 'success')  # Añadido mensaje de éxito
            
        except Exception as e:
            db.rollback()  # Añadido rollback en caso de error
            print(f'Error al eliminar el pedido: {str(e)}')

        return redirect(url_for('admin.ListaSolicitudes'))


@admin_bp.route('/RechazarAcceso/<string:IDsolicitud>', methods=['GET', 'POST'])
@login_required
@verificar_permiso('Administrador')
def RechazarAcceso(IDsolicitud):
    
        try:
            cursor = db.cursor()
            
            sql = """
                UPDATE [sistema_de_prestamo].[dbo].[SolicitudesDeAcceso]
                SET Estado = 'Rechazado'
                WHERE IDsolicitudAcceso = ?;
                 """
            cursor.execute(sql, (IDsolicitud,))
            db.commit()
            flash('Solicitud rechazada exitosamente', 'success')  # Añadido mensaje de éxito
            
        except Exception as e:
            db.rollback()  # Añadido rollback en caso de error
            print(f'Error al rechazar el acceso: {str(e)}')
      
        return redirect(url_for('admin.ListaSolicitudes'))

@admin_bp.route('/AceptarAcceso/<int:IDsolicitud>', methods=['GET', 'POST'])
@login_required
@verificar_permiso('Administrador')
def AceptarAcceso(IDsolicitud):
    try:
        cursor = db.cursor()
        sql_get_usuario = """
        SELECT IDusuario
        FROM [sistema_de_prestamo].[dbo].[SolicitudesDeAcceso]
        WHERE IDsolicitudAcceso = ?;
        """
        cursor.execute(sql_get_usuario, (IDsolicitud,))
        resultado = cursor.fetchone()
        if resultado:
            IDusuario = resultado[0]
       
            sql_update_solicitud = """
            UPDATE [sistema_de_prestamo].[dbo].[SolicitudesDeAcceso]
            SET Estado = 'Aprobado',
                FechaDeActivacion = CAST(GETDATE() AS DATE)
            WHERE IDsolicitudAcceso = ?;
            """
            cursor.execute(sql_update_solicitud, (IDsolicitud,))
            sql_update_usuario = """
            UPDATE [sistema_de_prestamo].[dbo].[usuario]
            SET Permiso = 'Estudiante'
            WHERE IDusuario = ?;
            """
            cursor.execute(sql_update_usuario, (IDusuario,))
            db.commit()
            flash('Pedido Aceptado exitosamente', 'success')
        else:
            flash('No se encontró la solicitud de acceso', 'error')
            db.rollback()
            
    except Exception as e:
        db.rollback()
        flash(f'Error al procesar la solicitud: {str(e)}', 'error')
        print(f'Error al procesar la solicitud: {str(e)}')
    
    return redirect(url_for('admin.ListaSolicitudes'))












# ============================== 
# Inventario y botones 
# ==============================  

@admin_bp.route('/Inventario', methods=['GET', 'POST'])
@login_required
@verificar_permiso('Administrador')
def Inventario():
    try:
        filtro = request.args.get('filtro', 'todos')
        Equipos = AdminConsult.Inventario( db , filtro )
        # Verificar si hay pedidos activos y manejar la lógica de la respuesta
        return render_template('Admin/Inventario.html', Items=Equipos)

    except Exception as e:
        print(f"Error: {str(e)}")
        return redirect(url_for('admin.home')) 

        
@admin_bp.route('/EditarS/<string:IDequipo>', methods=['GET'])
@login_required
@verificar_permiso('Administrador')
def EditarEquipo(IDequipo):
    try:
        query = '''
            SELECT *
            FROM 
                [sistema_de_prestamo].[dbo].[equiposLab]
            WHERE 
                IDequipo = ?;
        '''
        with db.cursor() as cursor:
            cursor.execute(query, (IDequipo,))
            equipo = cursor.fetchone()
        
        if equipo is None:
            flash('Equipo no encontrado', 'danger')
            return redirect(url_for('admin.Inventario'))

        # Convertir el resultado a un diccionario para pasarlo a la plantilla
        equipo_dict = {
            'IDequipo': equipo[0],
            'Nombre': equipo[1],
            'Descripcion': equipo[2],
            'Estado': equipo[3],
            'FechaDeAdquisicion': equipo[4],
            'Ubicacion': equipo[5],
            'Imagen': equipo[6],
            'UltimaActualizacion': equipo[7],
            'Tipo': equipo[8],
            'CI': equipo[9],
            'NumeroDeInventario': equipo[10],
            'DescripcionTecnica': equipo[11],
            'Marca': equipo[12],
            'Modelo': equipo[13],
            'NumeroDeSerie': equipo[14],
            'Mantos_Anuales': equipo[15]
        }
        return render_template('Admin/operaciones/Editar.html', equipo=equipo_dict)
    except Exception as e:
        print(f"Error: {str(e)}")
        flash('Error al cargar el equipo', 'danger')
        return redirect(url_for('admin.Inventario'))

@admin_bp.route('/Editar/<string:IDequipo>', methods=['GET', 'POST'])
@login_required
@verificar_permiso('Administrador')
def AplicarCambios(IDequipo):
    try:
        nombre = request.form['nombre']
        estado = request.form['estado']
        descripcion = request.form['descripcion']
        fecha_adquisicion = request.form['fechaAdquisicion']
        ubicacion = request.form['ubicacion']
     
        tipo = request.form['tipo']
        ci = request.form['ci']
        numero_de_inventario = request.form['numeroInventario']
        descripcion_tecnica = request.form['descripcionTecnica']
        marca = request.form['marca']
        modelo = request.form['modelo']
        numero_de_serie = request.form['numeroSerie']
        mantos_anuales = request.form['mantenimientosAnuales']
        
        # Handle image upload
        imagen = request.files.get('imagen')
        imagen_url = None
        if imagen and imagen.filename:
            try:
                imagen_url = AdminConsult.guardar_imagen(imagen, flag='equipos')
            except ValueError as e:
                flash(str(e), 'danger')
                return redirect(url_for('admin.Inventario'))

        with db.cursor() as cursor:
            if imagen_url:
                # Update with new image
                query = '''
                    UPDATE [sistema_de_prestamo].[dbo].[equiposLab]
                    SET 
                        Nombre = ?,
                        Descripción = ?,
                        Estado = ?,
                        FechaDeAdquisición = ?,
                        Ubicación = ?,
                        Imagen = ?,
                        Tipo = ?,
                        CI = ?,
                        NumeroDeInventario = ?,
                        DescripcionTecnica = ?,
                        Marca = ?,
                        Modelo = ?,
                        NumeroDeSerie = ?,
                        Mantos_Anuales = ?
                    WHERE 
                        IDequipo = ?;
                '''
                cursor.execute(query, (nombre, descripcion, estado, fecha_adquisicion, 
                                     ubicacion, imagen_url,tipo,
                                      ci,numero_de_inventario,descripcion_tecnica, marca, modelo, numero_de_serie,
                                       mantos_anuales, IDequipo))
            else:
                # Update without changing the image
                query = '''
                    UPDATE [sistema_de_prestamo].[dbo].[equiposLab]
                    SET 
                        Nombre = ?,
                        Descripción = ?,
                        Estado = ?,
                        FechaDeAdquisición = ?,
                        Ubicación = ?,
                        Tipo = ?,
                        CI = ?,
                        NumeroDeInventario = ?,
                        DescripcionTecnica = ?,
                        Marca = ?,
                        Modelo = ?,
                        NumeroDeSerie = ?,
                        Mantos_Anuales = ?
                    WHERE 
                        IDequipo = ?;
                '''
                cursor.execute(query, (nombre, descripcion, estado, fecha_adquisicion, 
                                     ubicacion,tipo,
                                      ci,numero_de_inventario,descripcion_tecnica, marca, modelo, numero_de_serie,
                                       mantos_anuales, IDequipo))
            
            db.commit()
            flash('Equipo actualizado exitosamente', 'success')
            
    except Exception as e:
        db.rollback()
        print(f"Error: {str(e)}")
        flash(f'Error al actualizar el equipo: {str(e)}', 'danger')
        
    return redirect(url_for('admin.Inventario'))

@admin_bp.route('/EliminarEquipo/<string:IDequipo>', methods=['GET', 'POST'])
@login_required
@verificar_permiso('Administrador')
def DeleteEquipo(IDequipo):
    try:
        cursor = db.cursor()
        
        # 1. Primero eliminar todas las observaciones relacionadas
        sql_obs = """
            DELETE FROM [sistema_de_prestamo].[dbo].[observacionesEquipos] 
            WHERE idEquipo = ?;
        """
        cursor.execute(sql_obs, (IDequipo,))
        
        # 2. Eliminar todas las referencias en solicitudesPrestamo
        sql_sol = """
            DELETE FROM [sistema_de_prestamo].[dbo].[solicitudesPrestamo] 
            WHERE IDequipo = ?;
        """
        cursor.execute(sql_sol, (IDequipo,))
        
        # 3. Finalmente eliminar el equipo de equiposLab
        sql_equipo = """
            DELETE FROM [sistema_de_prestamo].[dbo].[equiposLab] 
            WHERE IDequipo = ?;
        """
        cursor.execute(sql_equipo, (IDequipo,))
        
        # Confirmar todos los cambios
        db.commit()
        flash('Equipo y todas sus referencias eliminados exitosamente', 'success')

    except Exception as e:
        # En caso de error, revertir todos los cambios
        db.rollback()
        print(f'Error al eliminar el equipo: {str(e)}')
        flash('Error al eliminar el equipo y sus referencias', 'error')

    return redirect(url_for('admin.Inventario'))

@admin_bp.route('/AgregarEquipo', methods=['GET', 'POST'])
@login_required
@verificar_permiso('Administrador')
def AgregarEquipo():
    try:
        return render_template('Admin/Operaciones/AgregarEquipo.html')
    except Exception as e:
        db.rollback()
        print(f"Error: {str(e)}")
        flash(f'Error al agregar el equipo: {str(e)}', 'danger')
        return redirect(url_for('admin.Inventario'))

@admin_bp.route('/AgregarEquipoAplica', methods=['GET', 'POST'])
@login_required
@verificar_permiso('Administrador')
def AplicarAgregarEquipo():
    if request.method == 'POST':
        print("Datos del formulario:", request.form)
        print("Archivos:", request.files)
        
        nombre = request.form['nombre']
        estado = request.form['estado']
        descripcion = request.form['descripcion']
        fecha_adquisicion = request.form['fechaAdquisicion']
        ubicacion = request.form['ubicacion']
        
        imagen = request.files.get('imagen')
        imagen_url = None
        if imagen and imagen.filename:  # Asegúrate de que se haya seleccionado un archivo
            try:
                imagen_url = AdminConsult.guardar_imagen(imagen,flag='equipos')
            except ValueError as e:
                flash(str(e), 'danger')
                return redirect(url_for('admin.AgregarEquipo'))
        
        try:
            with db.cursor() as cursor:
                query = '''
                    INSERT INTO [sistema_de_prestamo].[dbo].[equiposLab] 
                    (Nombre, Descripción, Estado, FechaDeAdquisición, Ubicación, Imagen)
                    VALUES (?, ?, ?, ?, ?, ?);
                '''
                cursor.execute(query, (nombre, descripcion, estado, fecha_adquisicion, ubicacion, imagen_url))
                db.commit()
                flash('Equipo agregado exitosamente', 'success')
                return redirect(url_for('admin.Inventario'))
        
        except Exception as e:
            db.rollback()
            print(f"Error: {str(e)}")
            flash(f'Error al agregar el equipo: {str(e)}', 'danger')
            return redirect(url_for('admin.AgregarEquipo'))
    
    return render_template('Admin/operaciones/Agregar.html')



# ============================== 
# Usuarios y botones 
# ==============================  

@admin_bp.route('/ListaUsuario', methods=['GET', 'POST'])
@login_required
@verificar_permiso('Administrador')
def ListaUsuario():
    try:
        filtro = request.args.get('filtro', 'todos')
        Usuario = AdminConsult.Usuarios( db , filtro )
        
        return render_template('Admin/Usuario.html', Usuarios=Usuario)

    except Exception as e:
        print(f"Error: {str(e)}")
        return redirect(url_for('admin.home')) 
    
@admin_bp.route('/EditarUsuario/<string:IDusuario>', methods=['GET'])
@login_required
@verificar_permiso('Administrador')
def EditarUsuario(IDusuario):
    try:
        query = '''
            SELECT
                IDusuario,
                NombreUsuario,
                Apellido,
                Email,
                Telefono,
                Carrera,
                Rol,
                Permiso,
                Imagen
            FROM 
                [sistema_de_prestamo].[dbo].[usuario]
            WHERE 
                IDusuario = ?;
        '''
        
        with db.cursor() as cursor:
            cursor.execute(query, (IDusuario,))
            usuario = cursor.fetchone()
            
            if usuario is None:
                flash('Usuario no encontrado', 'danger')
                return redirect(url_for('admin.ListaUsuario'))
            
            # Convertir el resultado a un diccionario para pasarlo a la plantilla
            usuario_dict = {
                'IDusuario': usuario[0],
                'NombreUsuario': usuario[1],
                'Apellido': usuario[2],
                'Email': usuario[3],
                'Telefono': usuario[4],
                'Carrera': usuario[5],
                'Rol': usuario[6],
                'Permiso': usuario[7],
                'Imagen': usuario[8]
            }
            
            return render_template('Admin/operaciones/EditarUsuario.html', usuario=usuario_dict)
    
    except Exception as e:
        print(f"Error: {str(e)}")
        flash('Error al cargar el usuario', 'danger')
        return redirect(url_for('admin.ListaUsuario'))
    

@admin_bp.route('/AplicarCambiosUsuario/<int:IDusuario>', methods=['GET', 'POST'])
@login_required
@verificar_permiso('Administrador')
def AplicarCambiosUsuario(IDusuario):
    if request.method == 'POST':
        # Extract form data
        nombre_usuario = request.form['nombreUsuario']
        apellido = request.form['apellido']
        email = request.form['email']
        telefono = request.form['telefono']
        carrera = request.form['carrera']
        rol = request.form['rol']
        permiso = request.form['permiso']
        
        # Handle image upload
        imagen = request.files.get('imagen')
        imagen_url = None
        if imagen and imagen.filename:
            try:
                imagen_url = AdminConsult.guardar_imagen(imagen,flag='Usuarios')
            except ValueError as e:
                flash(str(e), 'danger')
                return redirect(url_for('admin.EditarUsuario', IDusuario=IDusuario))
        
        try:
            with db.cursor() as cursor:
                # Prepare the update query
                if imagen_url:
                    # Update with new image
                    query = '''
                    UPDATE [sistema_de_prestamo].[dbo].[usuario]
                    SET NombreUsuario = ?, 
                        Apellido = ?, 
                        Email = ?, 
                        Telefono = ?, 
                        Carrera = ?, 
                        Rol = ?, 
                        Permiso = ?,
                        Imagen = ?
                    WHERE IDusuario = ?
                    '''
                    cursor.execute(query, (nombre_usuario, apellido, email, telefono, 
                                           carrera, rol, permiso, imagen_url, IDusuario))
                else:
                    # Update without changing the image
                    query = '''
                    UPDATE [sistema_de_prestamo].[dbo].[usuario]
                    SET NombreUsuario = ?, 
                        Apellido = ?, 
                        Email = ?, 
                        Telefono = ?, 
                        Carrera = ?, 
                        Rol = ?, 
                        Permiso = ?
                    WHERE IDusuario = ?
                    '''
                    cursor.execute(query, (nombre_usuario, apellido, email, telefono, 
                                           carrera, rol, permiso, IDusuario))
                
                db.commit()
                flash('Usuario actualizado exitosamente', 'success')
                return redirect(url_for('admin.ListaUsuario'))
        
        except Exception as e:
            db.rollback()
            print(f"Error: {str(e)}")
            flash(f'Error al actualizar el usuario: {str(e)}', 'danger')
            return redirect(url_for('admin.EditarUsuario', IDusuario=IDusuario))
    
    # If somehow accessed via GET, redirect to edit page
    return redirect(url_for('admin.EditarUsuario', IDusuario=IDusuario))


@admin_bp.route('/EliminarUsuario/<string:IDusuario>', methods=['GET', 'POST'])
@login_required
@verificar_permiso('Administrador')
def DeleteUsuario(IDusuario):
    try:
        cursor = db.cursor()
        
        # 1. Primero eliminar todas las observaciones relacionadas
        sql_obs = """
            DELETE FROM [sistema_de_prestamo].[dbo].[observacionesEquipos] 
            WHERE IDusuario = ?;
        """
        cursor.execute(sql_obs, (IDusuario,))
        
        # 2. Eliminar todas las referencias en solicitudesPrestamo
        sql_sol = """
            DELETE FROM [sistema_de_prestamo].[dbo].[solicitudesPrestamo] 
            WHERE IDusuario = ?;
        """
        cursor.execute(sql_sol, (IDusuario,))
        
        # 3. Finalmente eliminar el equipo de equiposLab
        sql_equipo = """
            DELETE FROM [sistema_de_prestamo].[dbo].[usuario] 
            WHERE IDusuario = ?;
        """
        cursor.execute(sql_equipo, (IDusuario,))
        
        # Confirmar todos los cambios
        db.commit()
        flash('Usuario y todas sus referencias eliminados exitosamente', 'success')

    except Exception as e:
        # En caso de error, revertir todos los cambios
        db.rollback()
        print(f'Error al eliminar el Usuario: {str(e)}')
        flash('Error al eliminar el Usuario y sus referencias', 'error')

    return redirect(url_for('admin.ListaUsuario'))



# ============================== 
# Historial y botones
# ==============================  

@admin_bp.route('/Historial', methods=['GET', 'POST'])
@login_required
@verificar_permiso('Administrador')
def HistorialList():
    try:
        filtro = request.args.get('filtro', 'todos')
        Solicitudes = AdminConsult.Historial( db , filtro )
        # Verificar si hay pedidos activos y manejar la lógica de la respuesta
        return render_template('Admin/Historial.html', Solicitudes=Solicitudes)

    except Exception as e:
        print(f"Error: {str(e)}")
        return redirect(url_for('admin.home')) 