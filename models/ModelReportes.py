import ast
import json
from datetime import datetime
from decimal import Decimal


class ModelReportes:

    TABLE = "HospitalGalenia.dbo.Reportes"

    TIPOS_VALIDOS = ('alta', 'baja', 'mantenimiento', 'entrada', 'salida')

    # Serie aparte para las actas retroactivas: equipos que ya estaban en el
    # inventario antes del sistema y nunca tuvieron alta. Son 'alta' para la
    # BD (el CHECK de la tabla solo admite los cinco tipos), pero se
    # distinguen por el folio para que no se confundan con una recepción
    # real ocurrida ese día.
    PREFIJO_REGULARIZACION = 'RPT-REG-'

    # ─────────────────────────────────────────────────────────
    #  FOLIO
    # ─────────────────────────────────────────────────────────

    @classmethod
    def generar_folio(cls, db, tipo, prefijo=None):
        """
        Genera el siguiente folio para un tipo dado.
        Formato: RPT-ALTA-00001, RPT-BAJA-00001, etc.

        `prefijo` permite una serie propia sin cambiar el tipo, que es como
        se numeran las regularizaciones (RPT-REG-00001).
        """
        try:
            prefijo_folio = prefijo or f"RPT-{tipo.upper()}-"
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
                      datos_equipo, archivo_pdf=None, prefijo_folio=None):
        """
        Inserta un reporte nuevo.

        datos_equipo  = dict con snapshot del equipo en ese momento.
        archivo_pdf   = ruta relativa al PDF, None si aún no se genera.
        prefijo_folio = serie propia del folio (ver PREFIJO_REGULARIZACION).

        Devuelve (ok: bool, reporte_id: int | None, folio: str | None)
        """
        if tipo not in cls.TIPOS_VALIDOS:
            print(f"Tipo de reporte inválido: {tipo}")
            return False, None, None

        try:
            folio = cls.generar_folio(db, tipo, prefijo_folio)
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
            return [cls._hidratar(dict(zip(columns, row))) for row in rows]

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
            return cls._hidratar(dict(zip(columns, row)))
        except Exception as e:
            print(f"Error get_by_id reporte [{reporte_id}]: {e}")
            return None

    # ─────────────────────────────────────────────────────────
    #  HELPERS
    # ─────────────────────────────────────────────────────────

    @classmethod
    def _hidratar(cls, reporte):
        """
        Deja el reporte listo para el template: agrega la clave 'datos' con el
        JSON ya deserializado y los accesorios siempre como lista de dicts.
        """
        datos = {}
        if reporte.get('datos_json'):
            try:
                datos = json.loads(reporte['datos_json'])
            except (ValueError, TypeError) as e:
                print(f"Error al leer datos_json del reporte {reporte.get('id')}: {e}")
                datos = {}
        datos['accesorios'] = cls.normalizar_lista(datos.get('accesorios'))
        reporte['datos'] = datos
        return reporte

    @classmethod
    def _serializar_datos(cls, datos):
        """
        Convierte fechas y otros tipos no serializables a algo que JSON acepte,
        SIN aplanar la estructura: los dicts y listas se recorren.

        Aplanarlos con str() era lo que rompía la lista de accesorios — se
        guardaba como el texto "[{'descripcion': ...}]" y el template la
        recorría carácter por carácter, así que nunca imprimía nada.
        """
        if datos is None or isinstance(datos, (bool, int, float, str)):
            return datos
        if isinstance(datos, dict):
            return {str(k): cls._serializar_datos(v) for k, v in datos.items()}
        if isinstance(datos, (list, tuple, set)):
            return [cls._serializar_datos(v) for v in datos]
        if isinstance(datos, Decimal):
            return float(datos)
        if hasattr(datos, 'strftime'):
            return datos.strftime('%Y-%m-%d')
        if isinstance(datos, (bytes, bytearray)):
            return datos.decode('utf-8', errors='replace')
        return str(datos)

    @staticmethod
    def normalizar_lista(valor):
        """
        Devuelve siempre una lista de dicts.

        Los reportes creados antes de arreglar el serializador tienen los
        accesorios guardados como el repr de una lista de Python. Se intenta
        recuperarlos; si no se puede, se tratan como lista vacía en vez de
        reventar el PDF.
        """
        if isinstance(valor, list):
            return [v for v in valor if isinstance(v, dict)]
        if isinstance(valor, str) and valor.strip():
            try:
                recuperado = ast.literal_eval(valor)
            except (ValueError, SyntaxError):
                return []
            if isinstance(recuperado, list):
                return [v for v in recuperado if isinstance(v, dict)]
        return []