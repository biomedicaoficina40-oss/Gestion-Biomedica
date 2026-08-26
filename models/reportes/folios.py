"""
Consecutivo de folio por serie.

Reemplaza el SELECT MAX(...) + 1 de ModelReportes.generar_folio, que tiene dos
defectos que solo se notan cuando el sistema se usa en serio:

  1. Condición de carrera. Dos reportes abiertos al mismo tiempo leen el mismo
     máximo y piden el mismo número; el segundo INSERT choca contra el UNIQUE
     del folio y el reporte se pierde.
  2. El filtro LIKE 'RPT-{serie}%' cuenta de más si una serie es prefijo de
     otra. Con 'ALTA' y 'REG' no pasaba; con 'MP' y 'MC' tampoco, porque las
     series se eligieron para que ninguna sea prefijo de otra — pero el diseño
     no debería depender de que nadie agregue 'MP2' algún día.

Aquí el número sale de un UPDATE ... OUTPUT, que el motor ejecuta como una sola
operación atómica: dos peticiones simultáneas se serializan y cada una recibe un
valor distinto, sin transacción explícita ni bloqueos en la aplicación.
"""

from flask import current_app

# Series conocidas. El script SQL las siembra; esto es la referencia para el
# código y el lugar donde se documenta qué significa cada una.
SERIES = {
    'ALTA': 'Alta de equipo',
    'REG':  'Alta regularizada (equipo cargado antes del sistema)',
    'MP':   'Mantenimiento preventivo',
    'MC':   'Mantenimiento correctivo',
    'BAJA': 'Baja de equipo',
    'ENT':  'Entrada de equipo',
    'SAL':  'Salida de equipo',
    'TV':   'Tecnovigilancia',
    'CAP':  'Capacitación',
    'CR':   'Bitácora de carrito rojo',
}

# Serie que le corresponde a cada tipo de reporte.
SERIE_POR_TIPO = {
    'alta':            'ALTA',
    'preventivo':      'MP',
    'correctivo':      'MC',
    'baja':            'BAJA',
    'entrada':         'ENT',
    'salida':          'SAL',
    'tecnovigilancia': 'TV',
    'capacitacion':    'CAP',
    'carrito_rojo':    'CR',
}

ANCHO = 5          # RPT-MP-00001
PREFIJO = 'RPT-'


class ModelFolios:
    TABLE = "HospitalGalenia.dbo.Folios"

    @classmethod
    def siguiente(cls, db, serie):
        """
        Aparta y devuelve el siguiente folio de la serie ('RPT-MP-00007').

        Devuelve (folio, numero) o (None, None) si algo falló.

        El número queda apartado en cuanto esta función retorna, aunque el
        reporte todavía no exista. Es a propósito: es preferible un hueco en la
        numeración (un folio apartado que nunca se usó porque el INSERT falló) a
        dos reportes con el mismo folio. Un auditor entiende un salto; no
        entiende un duplicado.
        """
        serie = (serie or '').strip().upper()
        if not serie:
            current_app.logger.error("[ModelFolios.siguiente] serie vacía")
            return None, None

        cursor = None
        try:
            cursor = db.cursor()

            # UPDATE ... OUTPUT es atómico: incrementa y devuelve el valor ya
            # incrementado sin que otra sesión pueda colarse en medio.
            cursor.execute(
                f"UPDATE {cls.TABLE} SET ultimo = ultimo + 1 "
                f"OUTPUT INSERTED.ultimo WHERE serie = ?",
                (serie,)
            )
            fila = cursor.fetchone()

            if fila is None:
                # Serie que no estaba sembrada. Se crea arrancando en 1.
                cursor.execute(
                    f"INSERT INTO {cls.TABLE} (serie, ultimo) "
                    f"OUTPUT INSERTED.ultimo VALUES (?, 1)",
                    (serie,)
                )
                fila = cursor.fetchone()

            numero = int(fila[0])
            db.commit()
            return f"{PREFIJO}{serie}-{str(numero).zfill(ANCHO)}", numero

        except Exception as e:
            current_app.logger.error(f"[ModelFolios.siguiente] serie={serie} | {e}")
            try:
                db.rollback()
            except Exception:
                pass
            return None, None
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def serie_de_tipo(cls, tipo):
        """Serie que le toca a un tipo de reporte, o None si no se conoce."""
        return SERIE_POR_TIPO.get((tipo or '').strip().lower())

    @classmethod
    def listar(cls, db):
        """Estado de los consecutivos, para diagnóstico."""
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(f"SELECT serie, ultimo FROM {cls.TABLE} ORDER BY serie")
            return [
                {'serie': r[0], 'ultimo': r[1], 'descripcion': SERIES.get(r[0], '')}
                for r in cursor.fetchall()
            ]
        except Exception as e:
            current_app.logger.error(f"[ModelFolios.listar] {e}")
            return []
        finally:
            if cursor:
                cursor.close()
