from datetime import datetime


class ModelEquipos:
    """
    Métodos para la parte PÚBLICA del catálogo.
    Usados por el blueprint 'equipos' (vistas del personal clínico).
    """

    @classmethod
    def obtener_equipo(cls, db, numero_inventario):
        """
        Obtiene un equipo por número de inventario.
        Usado en: DetalleEquipo (vista pública)
        """
        query = """
            SELECT
                id, area, equipo_unidad, marca, modelo,
                numero_serie, numero_inventario, fecha_fabricacion,
                propiedad, estado, fecha_adquisicion, fecha_fin_garantia,
                departamento, imagen, observaciones
            FROM HospitalGalenia.dbo.InventarioEquipos
            WHERE numero_inventario = ?
        """
        try:
            cursor = db.cursor()
            cursor.execute(query, (numero_inventario,))
            row = cursor.fetchone()

            if row is None:
                return None

            columns = [col[0] for col in cursor.description]
            equipo  = dict(zip(columns, row))

            for key, value in equipo.items():
                if value is None:
                    equipo[key] = ''

            cursor.close()
            return equipo

        except Exception as e:
            print(f"Error obtener_equipo [{numero_inventario}]: {e}")
            return None

    @classmethod
    def buscar_equipos(cls, db, query):
        """
        Búsqueda inteligente multi-palabra.
        Usado en: BuscarEquipos (vista pública)
        """
        try:
            cursor = db.cursor()
            query_normalizado = cls._normalizar_texto(query)
            palabras = query_normalizado.split()

            condiciones = []
            parametros  = []
            campos = [
                'area', 'numero_inventario', 'numero_serie',
                'marca', 'modelo', 'departamento', 'equipo_unidad'
            ]

            for palabra in palabras:
                conds = []
                for campo in campos:
                    conds.append(
                        f"LOWER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE("
                        f"{campo},'á','a'),'é','e'),'í','i'),'ó','o'),'ú','u')) LIKE ?"
                    )
                    parametros.append(f"%{palabra}%")
                condiciones.append(f"({' OR '.join(conds)})")

            where = ' AND '.join(condiciones) if condiciones else "1=1"
            sql   = f"SELECT * FROM InventarioEquipos WHERE {where} ORDER BY area"

            cursor.execute(sql, parametros)
            resultados = cursor.fetchall()

            # Fallback: OR entre palabras si no hay resultados
            if not resultados and len(palabras) > 1:
                where = ' OR '.join(condiciones)
                sql   = f"SELECT * FROM InventarioEquipos WHERE {where} ORDER BY area"
                cursor.execute(sql, parametros)
                resultados = cursor.fetchall()

            cursor.close()
            return resultados

        except Exception as e:
            raise Exception(e)

    # ── Helpers ───────────────────────────────────────────────
    @staticmethod
    def _normalizar_texto(texto):
        if not texto:
            return ""
        reemplazos = {
            'á':'a','é':'e','í':'i','ó':'o','ú':'u',
            'Á':'a','É':'e','Í':'i','Ó':'o','Ú':'u',
            'ñ':'n','Ñ':'n'
        }
        texto = texto.lower()
        for k, v in reemplazos.items():
            texto = texto.replace(k, v)
        return ' '.join(texto.split())