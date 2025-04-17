from datetime import datetime
from flask import session


class ModelEquipos:
   
    @classmethod
    def obtener_equipos(cls, db, filtro='todos'):
        try:
            CarritoID = session.get('Carrito_ID')
            if CarritoID is None:
                CarritoID = -1
            # Query base con parámetro ? 
            query = """
            SELECT 
                e.IDequipo,
                e.Nombre,
                e.Descripción,
                e.Estado,
                e.Imagen,
                e.NumeroDeInventario,
                e.Marca,
                e.Modelo,
                CASE 
                    WHEN ec.CarritoID IS NOT NULL THEN 'Agregado' 
                    ELSE 'No Agregado' 
                END AS Carrito
            FROM sistema_de_prestamo.dbo.equiposLab e
            LEFT JOIN sistema_de_prestamo.dbo.EquiposCarrito ec 
                ON e.IDequipo = ec.IDequipo 
                AND ec.CarritoID = ?
            """
            # Construir la cláusula WHERE según el filtro
            where_clause = ""
            if filtro == 'Disponible':
                where_clause = " WHERE e.Estado = 'Disponible'"
            elif filtro == "En uso":
                where_clause = " WHERE e.Estado IN ('En Uso', 'Pendiente')"
            # Agregar cláusulas WHERE y ORDER BY
            final_query = query + where_clause + " ORDER BY e.FechaDeAdquisición DESC"
            with db.cursor() as cursor:
                cursor.execute(final_query, [CarritoID])
                columns = [column[0] for column in cursor.description]
                results = cursor.fetchall()
                
                equipos = []
                for row in results:
                    equipo = dict(zip(columns, row))
                    for key in equipo:
                        if equipo[key] is None:
                            equipo[key] = ''
                    equipos.append(equipo)
                    
                return equipos

        except Exception as e:
            import logging
            logging.error(f"Error al obtener equipos: {str(e)}", exc_info=True)
            return []


    @classmethod
    def obtener_equipo(cls, db, ID):
        """
        Obtiene un equipo por su ID.
        """
        query = '''
        SELECT 
            IDequipo,
            Nombre,
            Descripción,
            Estado,
            Imagen,
            FechaDeAdquisición,
            Ubicación
        FROM sistema_de_prestamo.dbo.equiposLab 
        WHERE IDequipo = ?
        '''

        try:
            with db.cursor() as cursor:
                cursor.execute(query, (ID,))  # Se asegura de pasar el parámetro como una tupla
                row = cursor.fetchone()
                if row is None:
                    print(f"No se encontró equipo con ID {ID}.")
                    return None  # Devuelve None si no se encuentra el equipo
                columns = [column[0] for column in cursor.description]
                return dict(zip(columns, row))  # Devuelve un solo diccionario
        except Exception as e:
            print(f"Error al obtener equipo con ID {ID}: {str(e)}")
            return None  # Devuelve None en caso de excepción
    @staticmethod
    def solicitar_equipo(db_connection, equipo_id, usuario_id):
        query = '''
            BEGIN TRANSACTION;
            BEGIN TRY
                -- Verificar si el usuario existe
                IF NOT EXISTS (SELECT 1 FROM sistema_de_prestamo.dbo.Usuario WHERE IDusuario = @usuario_id)
                BEGIN
                    ROLLBACK;
                    SELECT -2 as resultado;  -- Usuario no existe
                    RETURN;
                END
                -- Verificar si el equipo está disponible
                IF EXISTS (
                    SELECT 1 
                    FROM sistema_de_prestamo.dbo.equiposLab WITH (UPDLOCK)
                    WHERE IDequipo = @equipo_id AND Estado = 'Disponible'
                )
                BEGIN
                    -- Insertar nueva solicitud
                    INSERT INTO sistema_de_prestamo.dbo.solicitudesPrestamo (
                        EquipoID,
                        UsuarioID,
                        Estado,
                        FechaSolicitud,
                        FechaLimite
                    ) VALUES (
                        @equipo_id, @usuario_id, 'Pendiente', 
                        GETDATE(), 
                        DATEADD(day, 7, GETDATE())  -- 7 días de límite
                    );
                    -- Actualizar estado del equipo (comentado para uso futuro)
                    --UPDATE sistema_de_prestamo.dbo.equiposLab
                    --SET Estado = 'Pendiente',
                    --    UltimaActualizacion = GETDATE()
                    --WHERE IDequipo = @equipo_id;
                    COMMIT;
                    SELECT 1 as resultado;
                END
                ELSE
                BEGIN
                    ROLLBACK;
                    SELECT 0 as resultado;  -- Equipo no disponible
                END
            END TRY
            BEGIN CATCH
                ROLLBACK;
                SELECT -1 as resultado;  -- Error general
                THROW;
            END CATCH
        '''
        
        try:
            # Preparar cursor
            cursor = db_connection.cursor()
            
            # Ejecutar consulta con parámetros
            cursor.execute(query, {
                'usuario_id': usuario_id, 
                'equipo_id': equipo_id
            })
            
            # Obtener resultado
            resultado = cursor.fetchone()[0]
            
            # Interpretar resultado
            if resultado == 1:
                return {"success": True, "message": "Solicitud enviada exitosamente"}
            elif resultado == 0:
                return {"success": False, "message": "El equipo no está disponible"}
            elif resultado == -2:
                return {"success": False, "message": "Usuario no encontrado"}
            else:
                return {"success": False, "message": "Error al procesar la solicitud"}
        
        except Exception as e:
            # Logging de error
            print(f"Error en solicitar_equipo: {str(e)}")
            return {"success": False, "message": "Error interno del servidor"}
        finally:
            # Cerrar cursor
            cursor.close()