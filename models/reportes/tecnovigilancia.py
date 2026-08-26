"""
Detalle de un reporte de tecnovigilancia.

Documento de redacción, no de captura de trabajo: un equipo, una narración de
lo ocurrido, una clasificación y firmas. Los campos alineados a
NOM-240-SSA1-2012 (desenlace, lote, notificación a COFEPRIS, ciclo
inicial→seguimiento→final) ya existen en `RepTecnovigilancia` desde la 2.0,
pero se quedan fuera de este modelo a propósito: nadie los pide todavía y el
formulario no los expone. Cuando el comité defina el formato, se agregan
juntos (columna ya está, falta exponerla) en vez de construir hoy un camino
que nadie puede alcanzar.
"""

from flask import current_app

EVENTO_ADVERSO = 'evento_adverso'
EVENTO_CENTINELA = 'evento_centinela'
CASI_INCIDENTE = 'casi_incidente'
CLASIFICACIONES = (EVENTO_ADVERSO, EVENTO_CENTINELA, CASI_INCIDENTE)

ETIQUETAS_CLASIFICACION = {
    EVENTO_ADVERSO:   'Evento adverso',
    EVENTO_CENTINELA: 'Evento centinela',
    CASI_INCIDENTE:   'Casi incidente',
}

MAX_TEXTO = 4000


class ModelTecnovigilancia:
    TABLE = "HospitalGalenia.dbo.RepTecnovigilancia"

    @classmethod
    def crear(cls, db, reporte_id):
        """Crea el detalle vacío al abrir el reporte, igual que los otros tipos."""
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"INSERT INTO {cls.TABLE} (reporte_id) VALUES (?)", (reporte_id,))
            db.commit()
            return True
        except Exception as e:
            current_app.logger.error(
                f"[ModelTecnovigilancia.crear] reporte={reporte_id} | {e}")
            try:
                db.rollback()
            except Exception:
                pass
            return False
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def get(cls, db, reporte_id):
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                "SELECT reporte_id, fecha_evento, fecha_deteccion, clasificacion, "
                "       descripcion, involucrados, acciones_inmediatas "
                f"FROM {cls.TABLE} WHERE reporte_id = ?",
                (reporte_id,))
            fila = cursor.fetchone()
            if not fila:
                return None
            columnas = [c[0] for c in cursor.description]
            detalle = dict(zip(columnas, fila))
            detalle['clasificacion_txt'] = ETIQUETAS_CLASIFICACION.get(
                detalle.get('clasificacion'))
            return detalle
        except Exception as e:
            current_app.logger.error(
                f"[ModelTecnovigilancia.get] reporte={reporte_id} | {e}")
            return None
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def guardar(cls, db, reporte_id, **campos):
        """UPDATE parcial — mismo patrón que los demás detalles de reporte."""
        permitidos = {
            'fecha_evento':        None,
            'fecha_deteccion':     None,
            'clasificacion':       str,
            'descripcion':         str,
            'involucrados':        str,
            'acciones_inmediatas': str,
        }

        asignaciones, valores = [], []
        for campo, tipo in permitidos.items():
            if campo not in campos:
                continue
            valor = campos[campo]
            if tipo is str and valor is not None:
                valor = str(valor).strip()[:MAX_TEXTO] or None
                if campo == 'clasificacion' and valor not in CLASIFICACIONES:
                    valor = None
            asignaciones.append(f"{campo} = ?")
            valores.append(valor)

        if not asignaciones:
            return True

        cursor = None
        try:
            cursor = db.cursor()
            valores.append(reporte_id)
            cursor.execute(
                f"UPDATE {cls.TABLE} SET {', '.join(asignaciones)} WHERE reporte_id = ?",
                tuple(valores))
            db.commit()
            return True
        except Exception as e:
            current_app.logger.error(
                f"[ModelTecnovigilancia.guardar] reporte={reporte_id} | {e}")
            try:
                db.rollback()
            except Exception:
                pass
            return False
        finally:
            if cursor:
                cursor.close()
