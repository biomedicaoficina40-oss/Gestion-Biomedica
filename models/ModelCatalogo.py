from datetime import datetime
from flask import session


class ModelEquipos:
   
    @classmethod
    def obtener_equipo(cls, db, numero_inventario):
        """
        Obtiene un equipo del inventario por su número de inventario.
        """
        query = """
            SELECT
                id,
                area,
                equipo_unidad,
                marca,
                modelo,
                numero_serie,
                numero_inventario,
                fecha_fabricacion,
                propiedad,
                estado,
                fecha_adquisicion,
                fecha_fin_garantia,
                departamento,
                imagen,
                observaciones
            FROM HospitalGalenia.dbo.InventarioEquipos
            WHERE numero_inventario = ?
        """

        try:
            cursor = db.cursor()
            cursor.execute(query, (numero_inventario,))
            row = cursor.fetchone()

            if row is None:
                print(f"No se encontró equipo con número de inventario {numero_inventario}.")
                return None

            columns = [column[0] for column in cursor.description]
            equipo = dict(zip(columns, row))

            # Reemplazar None solo en campos string
            for key, value in equipo.items():
                if value is None:
                    equipo[key] = ''

            cursor.close()
            return equipo

        except Exception as e:
            print(f"Error al obtener equipo con número de inventario {numero_inventario}: {str(e)}")
            return None


    @classmethod
    def buscar_equipos(cls, db, query):
        """Buscar equipos por múltiples criterios con búsqueda inteligente"""
        try:
            cursor = db.cursor()
            
            # Normalizar el query: quitar acentos, convertir a minúsculas, quitar espacios extras
            query_normalizado = cls._normalizar_texto(query)
            
            # Dividir la búsqueda en palabras individuales
            palabras = query_normalizado.split()
            
            # Construir condiciones de búsqueda para cada palabra
            condiciones = []
            parametros = []
            
            campos = ['area', 'numero_inventario', 'numero_serie', 'marca', 'modelo', 'departamento', 'equipo_unidad']
            
            for palabra in palabras:
                condiciones_palabra = []
                for campo in campos:
                    condiciones_palabra.append(f"LOWER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE({campo}, 'á', 'a'), 'é', 'e'), 'í', 'i'), 'ó', 'o'), 'ú', 'u')) LIKE ?")
                    parametros.append(f"%{palabra}%")
                
                # Unir las condiciones de esta palabra con OR
                condiciones.append(f"({' OR '.join(condiciones_palabra)})")
            
            # Unir todas las palabras con AND (todas las palabras deben aparecer)
            where_clause = ' AND '.join(condiciones) if condiciones else "1=1"
            
            sql = f"""
                SELECT * FROM InventarioEquipos
                WHERE {where_clause}
                ORDER BY area
            """
            
            cursor.execute(sql, parametros)
            resultados = cursor.fetchall()
            
            # Si no hay resultados, intentar búsqueda más flexible (con OR entre palabras)
            if not resultados and len(palabras) > 1:
                where_clause = ' OR '.join(condiciones)
                sql = f"""
                    SELECT * FROM InventarioEquipos
                    WHERE {where_clause}
                    ORDER BY area
                """
                cursor.execute(sql, parametros)
                resultados = cursor.fetchall()
            
            return resultados
            
        except Exception as ex:
            raise Exception(ex)

    @staticmethod
    def _normalizar_texto(texto):
        """Normaliza texto para búsqueda: quita acentos, convierte a minúsculas"""
        if not texto:
            return ""
        
        # Diccionario de reemplazos para acentos
        reemplazos = {
            'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
            'Á': 'a', 'É': 'e', 'Í': 'i', 'Ó': 'o', 'Ú': 'u',
            'ñ': 'n', 'Ñ': 'n'
        }
        
        texto_normalizado = texto.lower()
        for original, reemplazo in reemplazos.items():
            texto_normalizado = texto_normalizado.replace(original, reemplazo)
        
        # Quitar espacios extras
        return ' '.join(texto_normalizado.split())