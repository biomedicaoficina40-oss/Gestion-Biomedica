import json
from datetime import datetime


class ModelReportes:

    TABLE = "HospitalGalenia.dbo.Reportes"

    TIPOS_VALIDOS = ('alta', 'baja', 'mantenimiento', 'entrada', 'salida')

    # ─────────────────────────────────────────────────────────
    #  FOLIO
    # ─────────────────────────────────────────────────────────

    @classmethod
    def generar_folio(cls, db, tipo):
        """
        Genera el siguiente folio para un tipo dado.
        Formato: RPT-ALTA-00001, RPT-BAJA-00001, etc.
        """
        try:
            prefijo_folio = f"RPT-{tipo.upper()}-"
            cursor = db.cursor()
            cursor.execute(
                f"SELECT folio FROM {cls.TABLE} "
                f"WHERE folio LIKE ?",
                (f"{prefijo_folio}%",)
            )
            rows = cursor.fetchall()
            cursor.close()

            numeros = []
            for row in rows:
                sufijo = row[0][len(prefijo_folio):]
                if sufijo.isdigit():
                    numeros.append(int(sufijo))

            siguiente = (max(numeros) + 1) if numeros else 1
            return f"{prefijo_folio}{str(siguiente).zfill(5)}"

        except Exception as e:
            print(f"Error generar_folio [{tipo}]: {e}")
            return None

    # ─────────────────────────────────────────────────────────
    #  ESCRITURA
    # ─────────────────────────────────────────────────────────

    @classmethod
    def crear_reporte(cls, db, tipo, equipo_id, usuario_id,
                      datos_equipo, archivo_pdf=None):
        """
        Inserta un reporte nuevo.

        datos_equipo = dict con snapshot del equipo en ese momento.
        archivo_pdf  = ruta relativa al PDF, None si aún no se genera.

        Devuelve (ok: bool, reporte_id: int | None, folio: str | None)
        """
        if tipo not in cls.TIPOS_VALIDOS:
            print(f"Tipo de reporte inválido: {tipo}")
            return False, None, None

        try:
            folio = cls.generar_folio(db, tipo)
            if not folio:
                return False, None, None

            # Serializar snapshot — fechas a string para que JSON las acepte
            datos_serializados = cls._serializar_datos(datos_equipo)

            cursor = db.cursor()
            cursor.execute(f"""
                INSERT INTO {cls.TABLE}
                    (tipo, folio, equipo_id, usuario_id,
                     fecha, datos_json, archivo_pdf)
                OUTPUT INSERTED.id
                VALUES (?, ?, ?, ?, GETDATE(), ?, ?)
            """, (
                tipo,
                folio,
                equipo_id,
                usuario_id,
                json.dumps(datos_serializados, ensure_ascii=False),
                archivo_pdf
            ))
            reporte_id = cursor.fetchone()[0]
            db.commit()
            cursor.close()
            return True, reporte_id, folio

        except Exception as e:
            print(f"Error crear_reporte [{tipo}]: {e}")
            db.rollback()
            return False, None, None

    @classmethod
    def actualizar_pdf(cls, db, reporte_id, archivo_pdf):
        """
        Actualiza la ruta del PDF una vez que se genera.
        Se usará cuando implementemos la generación de PDF.
        """
        try:
            cursor = db.cursor()
            cursor.execute(
                f"UPDATE {cls.TABLE} SET archivo_pdf = ? WHERE id = ?",
                (archivo_pdf, reporte_id)
            )
            db.commit()
            cursor.close()
            return True
        except Exception as e:
            print(f"Error actualizar_pdf [{reporte_id}]: {e}")
            db.rollback()
            return False

    # ─────────────────────────────────────────────────────────
    #  LECTURA
    # ─────────────────────────────────────────────────────────

    @classmethod
    def get_por_equipo(cls, db, equipo_id, tipo=None):
        """
        Devuelve todos los reportes de un equipo.
        Si se pasa tipo, filtra por él.
        """
        try:
            cursor = db.cursor()
            params = [equipo_id]
            tipo_sql = ""
            if tipo:
                tipo_sql = "AND tipo = ?"
                params.append(tipo)

            cursor.execute(f"""
                SELECT id, tipo, folio, equipo_id, usuario_id,
                       fecha, datos_json, archivo_pdf
                FROM {cls.TABLE}
                WHERE equipo_id = ? {tipo_sql}
                ORDER BY fecha DESC
            """, params)

            rows    = cursor.fetchall()
            columns = [col[0] for col in cursor.description]
            cursor.close()
            return [dict(zip(columns, row)) for row in rows]

        except Exception as e:
            print(f"Error get_por_equipo [{equipo_id}]: {e}")
            return []

    @classmethod
    def get_by_id(cls, db, reporte_id):
        """Obtiene un reporte por su PK."""
        try:
            cursor = db.cursor()
            cursor.execute(f"""
                SELECT id, tipo, folio, equipo_id, usuario_id,
                       fecha, datos_json, archivo_pdf
                FROM {cls.TABLE}
                WHERE id = ?
            """, (reporte_id,))
            row = cursor.fetchone()
            if not row:
                return None
            columns = [col[0] for col in cursor.description]
            cursor.close()
            reporte = dict(zip(columns, row))
            # Deserializar el JSON
            if reporte.get('datos_json'):
                reporte['datos'] = json.loads(reporte['datos_json'])
            return reporte
        except Exception as e:
            print(f"Error get_by_id reporte [{reporte_id}]: {e}")
            return None

    # ─────────────────────────────────────────────────────────
    #  HELPERS
    # ─────────────────────────────────────────────────────────

    @staticmethod
    def _serializar_datos(datos):
        """
        Convierte fechas y otros tipos no serializables a string
        para poder guardarlos en JSON.
        """
        resultado = {}
        for k, v in datos.items():
            if hasattr(v, 'strftime'):
                resultado[k] = v.strftime('%Y-%m-%d')
            elif v is None:
                resultado[k] = None
            else:
                resultado[k] = str(v) if not isinstance(v, (int, float, bool, str)) else v
        return resultado