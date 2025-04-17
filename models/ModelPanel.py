


class ModelPanel():
    @classmethod
    def Estadistics_panel(cls, db):
        try:
            Contador_Solicitudes = cls.contar_solicitudes(db)
            Contador_Observaciones = cls.contar_observaciones(db)
            Contador_DispEquipo = cls.contar_equipos_disponibles(db)
            Contador_Pedidos = cls.contar_pedidos(db)
            

            return {
                'Contador_Pedidos': Contador_Pedidos,
                'Contador_Solicitudes': Contador_Solicitudes,
                'Contador_Observaciones': Contador_Observaciones,
                'Contador_DispEquipo': Contador_DispEquipo
            }
        except Exception as e:
            print(f"Error al obtener estadísticas: {str(e)}")
            return {
                'pedidos_activos': 0,
                'total_solicitudes': 0,
                'total_observaciones': 0,
                'equipos_disponibles': 0
            }
        
    @staticmethod
    def execute_query(db, query):
        try:
            with db.cursor() as cursor:
                cursor.execute(query)
                result = cursor.fetchone()[0]
                return result
        except Exception as e:

            print(f"Error en la consulta: {str(e)}")
            return 0
        finally:
            if not db.autocommit:
                db.commit()

    @classmethod
    def contar_pedidos(cls, db):
        query = '''
        SELECT COUNT(*) 
        FROM sistema_de_prestamo.dbo.solicitudesPrestamo
        WHERE Estado = 'activo'; 
        
        '''
        return cls.execute_query(db, query)
    @classmethod
    def contar_solicitudes(cls, db):
        query = '''
        IF OBJECT_ID('sistema_de_prestamo.dbo.solicitudesPrestamo') IS NOT NULL
        BEGIN
             SELECT COUNT(*) FROM sistema_de_prestamo.dbo.solicitudesPrestamo WHERE Estado = 'pendiente';
        END
        ELSE
        BEGIN
            SELECT 0;
        END
        '''
        return cls.execute_query(db, query)
    @classmethod
    def contar_observaciones(cls, db):
        query = '''
        SELECT COUNT(*) 
        FROM sistema_de_prestamo.dbo.observacionesEquipos
        '''
        return cls.execute_query(db, query)

    @classmethod
    def contar_equipos_disponibles(cls, db):
        query = '''
        SELECT COUNT(*) 
        FROM sistema_de_prestamo.dbo.equiposLab 
        WHERE Estado = 'Disponible'
        '''
        return cls.execute_query(db, query)