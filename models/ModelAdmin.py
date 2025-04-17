
from PIL import Image
import os
from werkzeug.utils import secure_filename
from datetime import datetime
import uuid




class AdminConsult:

    @classmethod
    def SolicitudesAcceso(cls, db):
        try:
            # Definir la consulta SQL para obtener los pedidos activos por ID de equipo
            query = '''
                SELECT 
                    s.IDsolicitudAcceso,
                    s.IDusuario,
                    s.NombreUsuario,
                    u.Imagen AS ImagenUsuario,  -- Imagen del usuario
                    s.Motivo,
                    s.Estado,
                    s.FechaDeActivacion
                FROM 
                    [sistema_de_prestamo].[dbo].[SolicitudesDeAcceso] s
                JOIN 
                    [sistema_de_prestamo].[dbo].[Usuario] u ON s.IDusuario = u.IDusuario
                WHERE
                    s.Estado = 'Acceso';
            '''
            
            # Ejecutar la consulta
            with db.cursor() as cursor:
                cursor.execute(query)
                # Obtener los nombres de las columnas
                results=cursor.fetchall()
            if not results: 
                return "No hay solicitudes pendientes"
            return results
        except Exception as e:
            # Manejo de errores
            print(f"Error al obtener : {str(e)}")
            return []

    @classmethod
    def PedidosActivos(cls, db):
        try:
            # Definir la consulta SQL para obtener los pedidos activos por ID de equipo
            query = '''
                SELECT 
                    s.IDsolicitud,
                    s.IDequipo,
                    e.Imagen AS ImagenEquipo,  -- Imagen del equipo
                    s.NombreEquipo,
                    s.IDusuario,
                    u.Imagen AS ImagenUsuario,  -- Imagen del usuario
                    s.NombreUsuario,
                    s.FechaInicio,
                    s.FechaEntrega,
                    s.FechaSolicitud,
                    s.Motivo,
                    s.FechaDev,
                    s.Estado,
                    s.FechaDeActivacion
                FROM 
                    [sistema_de_prestamo].[dbo].[solicitudesPrestamo] s
                JOIN 
                    [sistema_de_prestamo].[dbo].[EquiposLab] e ON s.IDequipo = e.IDequipo
                JOIN 
                    [sistema_de_prestamo].[dbo].[Usuario] u ON s.IDusuario = u.IDusuario
                WHERE 
                    s.Estado = 'activo';
                    '''
            # Ejecutar la consulta
            with db.cursor() as cursor:
                cursor.execute(query)
                # Obtener los nombres de las columnas
                results=cursor.fetchall()
            if not results: 
                return "No hay pedidos activos"
            return results
        except Exception as e:
            # Manejo de errores
            print(f"Error al obtener pedidos activos: {str(e)}")
            return []
    
    @classmethod
    def Solicitudes(cls, db):
        try:
            query = '''
                SELECT 
                    s.IDsolicitud,
                    s.IDequipo,
                    e.Imagen AS ImagenEquipo,  -- Imagen del equipo
                    s.NombreEquipo,
                    s.IDusuario,
                    u.Imagen AS ImagenUsuario,  -- Imagen del usuario
                    s.NombreUsuario,
                    s.FechaInicio,
                    s.FechaEntrega,
                    s.FechaSolicitud,
                    s.Motivo,
                    s.FechaDev,
                    s.Estado,
                    s.FechaDeActivacion
                FROM 
                    [sistema_de_prestamo].[dbo].[solicitudesPrestamo] s
                JOIN 
                    [sistema_de_prestamo].[dbo].[EquiposLab] e ON s.IDequipo = e.IDequipo
                JOIN 
                    [sistema_de_prestamo].[dbo].[Usuario] u ON s.IDusuario = u.IDusuario
                WHERE
                    s.Estado = 'pendiente';
            '''       
            # Ejecutar la consulta
            with db.cursor() as cursor:
                cursor.execute(query)
                # Obtener los nombres de las columnas
                results=cursor.fetchall()
            if not results: 
                return "No hay pedidos activos"
            return results
        except Exception as e:
            # Manejo de errores
            print(f"Error al obtener pedidos activos: {str(e)}")
            return []
        
    @classmethod
    def Historial(cls, db,filtro='todos'):
            query = '''
            SELECT 
                IDsolicitud,
                IDequipo,
                NombreEquipo,
                IDusuario,
                NombreUsuario,
                FechaSolicitud,
                Motivo,
                FechaDev,
                Estado,
                FechaDeActivacion,
                FechaInicio,  
                FechaEntrega  
            FROM 
                [sistema_de_prestamo].[dbo].[solicitudesPrestamo]

            '''
            
            # Añadir filtro según el estado solicitado
            if filtro == 'Disponible':
                 query += " WHERE Estado = 'disponible'" 
            elif filtro == 'eliminado':
                 query += " WHERE Estado = 'eliminado'" 
            elif filtro == 'cancelado':
                 query += " WHERE Estado = 'cancelado'"
            elif filtro == 'rechazado': 
                query += " WHERE Estado = 'rechazado'" 
            elif filtro == 'concluido':
                 query += " WHERE Estado = 'concluido'" 
            elif filtro == 'activo': 
                query += " WHERE Estado = 'activo'"
            elif filtro == 'pendiente':
                query += " WHERE Estado = 'pendiente'"

            try:
                with db.cursor() as cursor:
                    cursor.execute(query)
                    columns = [column[0] for column in cursor.description]
                    return [dict(zip(columns, row)) for row in cursor.fetchall()]
            except Exception as e:
                print(f"Error al obtener equipos: {str(e)}")
                return []
        
    @classmethod
    def Inventario(cls, db, filtro='todos'):

            query = '''
            SELECT *
            FROM sistema_de_prestamo.dbo.equiposLab WITH (NOLOCK)
            '''
            
            # Añadir filtro según el estado solicitado
            if filtro == 'Disponible':
                query += " WHERE Estado = 'Disponible'"
            elif filtro == "En uso":
                query += " WHERE Estado IN ('En Uso', 'Pendiente')"
            
            # Ordenar por fecha de adquisición
            query += " ORDER BY FechaDeAdquisición DESC"

            try:
                with db.cursor() as cursor:
                    cursor.execute(query)
                    columns = [column[0] for column in cursor.description]
                    return [dict(zip(columns, row)) for row in cursor.fetchall()]
            except Exception as e:
                print(f"Error al obtener equipos: {str(e)}")
                return []

    @classmethod
    def guardar_imagen(cls,imagen_file,flag, max_size_mb=2, allowed_extensions=None, output_size=(800, 800)):
        """
        Guarda una imagen subida por el usuario de forma segura.

        """
        if allowed_extensions is None:
            allowed_extensions = ['.jpg', '.jpeg', '.png']

        # Verificar si se subió una imagen
        if not imagen_file:
            raise ValueError("No se proporcionó ninguna imagen")

        # Verificar el tamaño del archivo
        if len(imagen_file.read()) > max_size_mb * 1024 * 1024:  # Convertir MB a bytes
            raise ValueError(f"El archivo excede el tamaño máximo permitido de {max_size_mb}MB")
        imagen_file.seek(0)  # Resetear el puntero del archivo

        # Verificar el tipo de archivo
        file_ext = os.path.splitext(imagen_file.filename)[1].lower()
        if file_ext not in allowed_extensions:
            raise ValueError(f"Tipo de archivo no permitido. Use: {', '.join(allowed_extensions)}")

        # Verificar que sea una imagen válida
        try:
            img = Image.open(imagen_file)
            img.verify()  # Verificar que sea una imagen válida
            imagen_file.seek(0)  # Resetear el puntero después de verify()
            img = Image.open(imagen_file)  # Reabrir la imagen
        except Exception:
            raise ValueError("El archivo no es una imagen válida")

        # Generar nombre único para el archivo
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_id = str(uuid.uuid4().hex[:8])
        filename = secure_filename(f"{timestamp}_{unique_id}{file_ext}")

        # Definir la estructura de carpetas
        # Asumiendo que estás en src/models
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'static', 'uploads', flag))
        upload_folder = base_path

        # Crear el directorio si no existe
        os.makedirs(upload_folder, exist_ok=True)
        
        # Ruta completa del archivo
        filepath = os.path.join(upload_folder, filename)

        # Procesar y guardar la imagen
        try:
            # Convertir a RGB si es necesario (por ejemplo, si es PNG con transparencia)
            if img.mode in ('RGBA', 'LA'):
                background = Image.new('RGB', img.size, 'white')
                background.paste(img, mask=img.split()[-1])
                img = background

            # Redimensionar la imagen manteniendo la proporción
            img.thumbnail(output_size, Image.Resampling.LANCZOS)
            
            # Optimizar y guardar
            img.save(filepath, 'JPEG', quality=85, optimize=True)
            
            # Devolver la URL relativa para almacenar en la base de datos
            return os.path.join('uploads', flag, filename)


        except Exception as e:
            # Si algo sale mal durante el procesamiento, limpiar y relanzar la excepción
            if os.path.exists(filepath):
                os.remove(filepath)
            raise ValueError(f"Error al procesar la imagen: {str(e)}")

        
    @classmethod
    def Usuarios(cls, db, filtro='todos'):
        query = '''
        SELECT 
            IDusuario,
            NombreUsuario,
            Apellido,
            Carrera,
            Telefono,
            Rol,
            Email,
            Permiso,
            Imagen
        FROM sistema_de_prestamo.dbo.usuario WITH (NOLOCK)
        '''

        # Añadir filtro según el permiso solicitado
        if filtro == 'Visitante':
            query += " WHERE Permiso = 'Visitante'"
        elif filtro == 'Estudiante':
            query += " WHERE Permiso = 'Estudiante'"
        elif filtro == 'Administrador':
            query += " WHERE Permiso = 'Administrador'"

        # Ordenar por apellido
        query += " ORDER BY Apellido ASC"

        try:
            with db.cursor() as cursor:
                cursor.execute(query)
                columns = [column[0] for column in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
        except Exception as e:
            print(f"Error al obtener usuarios: {str(e)}")
            return []
        
