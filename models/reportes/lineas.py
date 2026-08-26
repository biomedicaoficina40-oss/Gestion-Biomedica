"""
Refacciones, consumibles y costos de un reporte.

Una sola tabla con `clase` en vez de tablas separadas. En el formulario se ve
como un bloque de renglones —que es como se pidió— pero el día que se quieran
separar consumibles de refacciones no hay migración: es una opción más en el
selector.

`precio_unitario` acepta NULL a propósito. En un preventivo es normal registrar
que se usó una refacción sin que nadie sepa cuánto costó; forzar un cero
mentiría en la suma y haría que el costo por equipo se viera artificialmente
bajo. Sin dato es sin dato, y las agregaciones lo reportan como tal.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from flask import current_app

CLASES = ('refaccion', 'consumible', 'mano_obra', 'servicio_externo', 'otro')

ETIQUETAS = {
    'refaccion':        'Refacción',
    'consumible':       'Consumible',
    'mano_obra':        'Mano de obra',
    'servicio_externo': 'Servicio externo',
    'otro':             'Otro',
}

MAX_LINEAS = 60


class ModelLineas:
    TABLE = "HospitalGalenia.dbo.ReporteLineas"
    COLS = """ id, reporte_id, clase, descripcion, cantidad, precio_unitario,
               importe, moneda, proveedor_id, factura, orden """

    @classmethod
    def get_por_reporte(cls, db, reporte_id):
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT {cls.COLS} FROM {cls.TABLE} "
                f"WHERE reporte_id = ? ORDER BY orden, id", (reporte_id,))
            columnas = [c[0] for c in cursor.description]
            lineas = [dict(zip(columnas, f)) for f in cursor.fetchall()]
            # El importe llega como DECIMAL(23,4) por ser columna calculada; se
            # cuadra aquí para que la tabla y el PDF muestren centavos y no
            # diezmilésimas.
            for linea in lineas:
                if linea.get('importe') is not None:
                    linea['importe'] = cls.centavos(linea['importe'])
            return lineas
        except Exception as e:
            current_app.logger.error(
                f"[ModelLineas.get_por_reporte] reporte={reporte_id} | {e}")
            return []
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def total(cls, db, reporte_id):
        """
        Total costeado y cuántos renglones quedaron sin precio.

        Devolver las dos cosas juntas es deliberado: un total de $1,200 sobre
        cinco renglones de los cuales tres no tienen precio no es un total, y
        la pantalla necesita poder decirlo.
        """
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT ISNULL(SUM(importe), 0), COUNT(*), "
                f"       SUM(CASE WHEN precio_unitario IS NULL THEN 1 ELSE 0 END) "
                f"FROM {cls.TABLE} WHERE reporte_id = ?", (reporte_id,))
            fila = cursor.fetchone()
            return {
                'total':       cls.centavos(fila[0]),
                'renglones':   fila[1] or 0,
                'sin_costear': fila[2] or 0,
            }
        except Exception as e:
            current_app.logger.error(f"[ModelLineas.total] reporte={reporte_id} | {e}")
            return {'total': Decimal('0'), 'renglones': 0, 'sin_costear': 0}
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def crear(cls, db, reporte_id, descripcion, cantidad=1, precio_unitario=None,
              clase='refaccion', proveedor_id=None, factura=None):
        """Agrega un renglón. Devuelve (ok, mensaje_o_id)."""
        descripcion = (descripcion or '').strip()
        if not descripcion:
            return False, "La descripción es obligatoria"
        if clase not in CLASES:
            return False, f"Clase no válida: {clase}"

        cantidad = cls._a_decimal(cantidad, por_omision=Decimal('1'))
        if cantidad is None or cantidad <= 0:
            return False, "La cantidad debe ser mayor que cero"

        precio = cls._a_decimal(precio_unitario, por_omision=None)
        if precio is not None and precio < 0:
            return False, "El precio no puede ser negativo"

        cursor = None
        try:
            cursor = db.cursor()

            cursor.execute(
                f"SELECT COUNT(*), ISNULL(MAX(orden), 0) + 1 FROM {cls.TABLE} "
                f"WHERE reporte_id = ?", (reporte_id,))
            existentes, orden = cursor.fetchone()
            if (existentes or 0) >= MAX_LINEAS:
                return False, f"Un reporte admite hasta {MAX_LINEAS} renglones"

            cursor.execute(
                f"INSERT INTO {cls.TABLE} "
                f"(reporte_id, clase, descripcion, cantidad, precio_unitario, "
                f" proveedor_id, factura, orden) "
                f"OUTPUT INSERTED.id VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (reporte_id, clase, descripcion[:300], cantidad, precio,
                 proveedor_id or None, (factura or '').strip()[:50] or None, orden))
            nuevo_id = cursor.fetchone()[0]
            db.commit()
            return True, nuevo_id

        except Exception as e:
            current_app.logger.error(f"[ModelLineas.crear] reporte={reporte_id} | {e}")
            try:
                db.rollback()
            except Exception:
                pass
            return False, "No se pudo agregar el renglón"
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def eliminar(cls, db, linea_id):
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(f"DELETE FROM {cls.TABLE} WHERE id = ?", (linea_id,))
            borrado = cursor.rowcount > 0
            db.commit()
            return borrado
        except Exception as e:
            current_app.logger.error(f"[ModelLineas.eliminar] id={linea_id} | {e}")
            try:
                db.rollback()
            except Exception:
                pass
            return False
        finally:
            if cursor:
                cursor.close()

    @staticmethod
    def centavos(valor):
        """
        Redondea un importe a dos decimales.

        La columna `importe` es calculada —cantidad DECIMAL(10,2) por
        precio_unitario DECIMAL(12,2)— así que SQL Server la devuelve como
        DECIMAL(23,4). Sumar eso da totales como 346.0000, que en una tabla de
        costos se ve mal y en un PDF se ve peor. Se cuadra aquí, en un solo
        lugar, en vez de en cada plantilla.
        """
        if valor is None:
            return Decimal('0.00')
        try:
            return Decimal(valor).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError, TypeError):
            return Decimal('0.00')

    @staticmethod
    def _a_decimal(valor, por_omision=None):
        """
        Convierte lo que venga del formulario a Decimal.

        Se usa Decimal y no float porque son importes: 0.1 + 0.2 en float da
        0.30000000000000004, y esa basura acaba sumada en un reporte de costos.
        """
        if valor is None or (isinstance(valor, str) and not valor.strip()):
            return por_omision
        try:
            return Decimal(str(valor).replace(',', '').strip())
        except (InvalidOperation, ValueError):
            return por_omision
