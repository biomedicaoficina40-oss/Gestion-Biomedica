from datetime import datetime
import logging

class ModelPerfil:


    @classmethod
    def devolver(cls, db, IDsolicitud):
        try:
            # Iniciar una transacción
            with db.cursor() as cursor:
                # Cambiar el Estado a 'Concluido' y agregar la fecha actual a 'FechaDev'
                query_solicitud = """
                UPDATE [sistema_de_prestamo].[dbo].[solicitudesPrestamo]
                SET Estado = 'Concluido', FechaDev = CAST(GETDATE() AS DATE)
                WHERE IDsolicitud = ?
                """
                cursor.execute(query_solicitud, (IDsolicitud,))
                # Obtener el IDequipo correspondiente a la solicitud
                query_equipo = """
                SELECT IDequipo
                FROM [sistema_de_prestamo].[dbo].[solicitudesPrestamo]
                WHERE IDsolicitud = ?
                """
                cursor.execute(query_equipo, (IDsolicitud,))
                row = cursor.fetchone()
                if row:
                    IDequipo = row[0]
                else:
                    raise ValueError("No se encontró el equipo para la solicitud.")
                # Actualizar el Estado del equipo a 'Disponible'
                query_update_equipo = """
                UPDATE [sistema_de_prestamo].[dbo].[EquiposLab]
                SET Estado = 'Disponible'
                WHERE IDequipo = ?
                """
                cursor.execute(query_update_equipo, (IDequipo,))
                # Confirmar la transacción
                db.commit()
                return "Solicitud concluida y equipo actualizado a 'Disponible' exitosamente."
        except Exception as e:
            # Revertir transacción en caso de error
            db.rollback()
            logging.error(f"Error al concluir la solicitud con ID {IDsolicitud}: {str(e)}")
            return f"Error al concluir la solicitud: {str(e)}"

    @classmethod
    def Get_oneSolicitud_by_id(cls, db, IDsolicitud):
        try:
            # Define SQL query to get the request by IDsolicitud
            query = '''
            SELECT
                s.IDsolicitud,
                s.IDequipo,
                e.Imagen AS ImagenEquipo,  -- Equipment image
                s.NombreEquipo,
                s.IDusuario,
                u.Imagen AS ImagenUsuario,  -- User image
                s.NombreUsuario,
                s.FechaInicio,
                s.FechaEntrega,
                s.FechaSolicitud,
                s.Motivo,
                s.FechaDev,
                s.Estado,
                s.FechaDeActivacion,
                s.Materia,
                s.Profesor
            FROM
                [sistema_de_prestamo].[dbo].[solicitudesPrestamo] s
            JOIN
                [sistema_de_prestamo].[dbo].[EquiposLab] e ON s.IDequipo = e.IDequipo
            JOIN
                [sistema_de_prestamo].[dbo].[Usuario] u ON s.IDusuario = u.IDusuario
            WHERE
                s.IDsolicitud = ?
            '''
            
            # Create a cursor and execute the query
            cursor = db.cursor()
            cursor.execute(query, (IDsolicitud,))
            
            # Fetch one row
            row = cursor.fetchone()
            
            # Return message if no request is found
            if not row:
                return "No hay pedidos activos"
            
            # Get column names
            columns = [column[0] for column in cursor.description]
            
            # Convert row to a dictionary
            result = dict(zip(columns, row))
            
            # Convertir fechas a objetos datetime
            if 'FechaInicio' in result and isinstance(result['FechaInicio'], str): 
                result['FechaInicio'] = datetime.strptime(result['FechaInicio'], '%Y-%m-%d') 
            if 'FechaEntrega' in result and isinstance(result['FechaEntrega'], str): 
                result['FechaEntrega'] = datetime.strptime(result['FechaEntrega'], '%Y-%m-%d') 
            if 'FechaSolicitud' in result and isinstance(result['FechaSolicitud'], str):
                 result['FechaSolicitud'] = datetime.strptime(result['FechaSolicitud'], '%Y-%m-%d') 
            if 'FechaDev' in result and isinstance(result['FechaDev'], str): 
                result['FechaDev'] = datetime.strptime(result['FechaDev'], '%Y-%m-%d') 
            if 'FechaDeActivacion' in result and isinstance(result['FechaDeActivacion'], str): 
                result['FechaDeActivacion'] = datetime.strptime(result['FechaDeActivacion'], '%Y-%m-%d') 
            return result
        except Exception as e:
            # Error handling with logging
            import logging
            logging.error(f"Error al obtener la solicitud con ID {IDsolicitud}: {str(e)}")
            return None


        
    @classmethod
    def get_solicitudes_by_status(cls, db, IDusuario, status):
        try:
            # Define SQL query to get active requests by user ID
            query = '''
            SELECT
                s.IDsolicitud,
                s.IDequipo,
                e.Imagen AS ImagenEquipo,  -- Equipment image
                s.NombreEquipo,
                s.IDusuario,
                u.Imagen AS ImagenUsuario,  -- User image
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
                s.IDusuario = ? AND s.Estado = ?
            '''
            
            # Create a cursor and execute the query
            cursor = db.cursor()
            cursor.execute(query, (IDusuario, status))
            
            # Fetch all rows
            rows = cursor.fetchall()
            
            # Return message if no requests found
            if not rows:
                return "No hay pedidos activos"
            
            # Get column names
            columns = [column[0] for column in cursor.description]
            
            # Convert rows to list of dictionaries
            results = [dict(zip(columns, row)) for row in rows]
            
            return results
        
        except Exception as e:
            # Error handling with logging
            import logging
            logging.error(f"Error al obtener pedidos activos: {str(e)}")
            return []
        
    @classmethod
    def get_user(cls, db, IDusuario):
        """
        Retrieve user information from the database by user ID.
        
        Args:
            db: Database connection object
            IDusuario: Unique identifier for the user
        
        Returns:
            dict: User information if found, None otherwise
        """
        try:
            with db.cursor() as cursor:
                sql = """
                SELECT 
                    IDusuario, 
                    NombreUsuario, 
                    Password, 
                    Apellido, 
                    Carrera, 
                    Telefono, 
                    Rol, 
                    Email, 
                    Permiso, 
                    Imagen
                FROM dbo.usuario 
                WHERE IDusuario = ?
                """
                
                cursor.execute(sql, (IDusuario,))
                row = cursor.fetchone()
                
                if row:
                    # Convert row to dictionary for easier access
                    user_dict = {
                        'IDusuario': row[0],
                        'NombreUsuario': row[1],
                        'Password': row[2],
                        'Apellido': row[3],
                        'Carrera': row[4],
                        'Telefono': row[5],
                        'Rol': row[6],
                        'Email': row[7],
                        'Permiso': row[8],
                        'Imagen': row[9]
                    }
                    return user_dict
                else:
                    return None
        
        except Exception as e:
            # Use logging instead of print for better error tracking
            import logging
            logging.error(f"Error al obtener pedidos activos: {str(e)}")
            return None
        
    @classmethod
    def equipos_carrito(cls, db, Carr):
        """

        """
        try:
            # Define SQL query to get active requests by user ID
            query = '''
            SELECT e.*, cp.Estado AS EstadoCarrito
            FROM EquiposLab e
            INNER JOIN EquiposCarrito ec ON e.IDequipo = ec.IDequipo
            INNER JOIN CarritoPedidos cp ON ec.CarritoID = cp.CarritoID
            WHERE cp.CarritoID = ?;
            '''
            
            # Create a cursor and execute the query
            cursor = db.cursor()
            cursor.execute(query, (Carr,))
            
            # Fetch all rows
            rows = cursor.fetchall()
            
            # Return message if no requests found
            if not rows:
                print("No hay equipos Carr")
                return "No hay equipos en carrito"
            
            # Get column names
            columns = [column[0] for column in cursor.description]
            
            # Convert rows to list of dictionaries
            results = [dict(zip(columns, row)) for row in rows]
            print (results)
            
            return results
        
        except Exception as e:
            # Error handling with logging
            import logging
            logging.error(f"Error al obtener pedidos activos: {str(e)}")
            return []
        
    @classmethod
    def get_cart_status(cls, db, cart_id):
        """
        Retrieves only the status of a cart from CarritoPedidos.
        
        Args:
            db: Database connection object
            cart_id: ID of the cart to query
            
        Returns:
            str: The status of the cart ('No encontrado' if cart doesn't exist, 
                'Error' if there's a database error)
        """
        try:
            with db.cursor() as cursor:
                query = '''
                SELECT Estado 
                FROM CarritoPedidos 
                WHERE CarritoID = ?;
                '''
                cursor.execute(query, (cart_id,))
                result = cursor.fetchone()
                
                if result:
                    return result[0]  # Usar índice entero para acceder al valor
                return 'No encontrado'
                
        except Exception as e:
            import logging
            logging.error(f"Error al consultar el estado del carrito {cart_id}: {str(e)}")
            return 'Error'


    
