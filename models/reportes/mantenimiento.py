"""
Detalle de los reportes de mantenimiento: preventivo, predictivo y correctivo.

Los tres comparten tabla porque comparten estructura; lo que cambia es qué
campos se llenan. Un preventivo no tiene fecha_falla ni causa de demora; un
correctivo sí. Separarlos obligaría a duplicar la mitad de las consultas de
estadística, que casi siempre quieren ver los dos juntos ("cuánto gastamos este
trimestre" no distingue).
"""

from datetime import datetime

from flask import current_app

PREVENTIVO = 'preventivo'
PREDICTIVO = 'predictivo'
CORRECTIVO = 'correctivo'

TIPOS_SERVICIO = (PREVENTIVO, PREDICTIVO, CORRECTIVO)

ETIQUETAS_SERVICIO = {
    PREVENTIVO: 'Preventivo',
    PREDICTIVO: 'Predictivo',
    CORRECTIVO: 'Correctivo',
}

RESULTADOS = ('operativo', 'operativo_con_restriccion', 'fuera_de_servicio', 'irreparable')

ETIQUETAS_RESULTADO = {
    'operativo':                 'Operativo',
    'operativo_con_restriccion': 'Operativo con restricciones',
    'fuera_de_servicio':         'Fuera de servicio',
    'irreparable':               'Irreparable — se sugiere baja',
}

MAX_TEXTO = 4000


class ModelMantenimiento:
    TABLE = "HospitalGalenia.dbo.RepMantenimiento"
    COLS = """ reporte_id, tipo_servicio, descripcion_trabajo, observaciones,
               fecha_falla, tipo_falla_id, causa_demora_id, resultado,
               horas_paro, requiere_seguimiento """

    @classmethod
    def crear(cls, db, reporte_id, tipo_servicio=PREVENTIVO):
        """
        Crea el detalle vacío al abrir el reporte.

        Se hace de inmediato y no al primer guardado para que el resto del
        código pueda contar con que la fila existe: así los guardados
        posteriores son siempre UPDATE y no hay que decidir cada vez.
        """
        if tipo_servicio not in TIPOS_SERVICIO:
            return False

        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"INSERT INTO {cls.TABLE} (reporte_id, tipo_servicio) VALUES (?, ?)",
                (reporte_id, tipo_servicio))
            db.commit()
            return True
        except Exception as e:
            current_app.logger.error(
                f"[ModelMantenimiento.crear] reporte={reporte_id} | {e}")
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
        """
        Detalle de un reporte, con los catálogos ya resueltos a nombre.

        El LEFT JOIN trae `tipo_falla_nombre` / `causa_demora_nombre` junto con
        los IDs: así ni la plantilla de pantalla ni la de PDF necesitan una
        segunda consulta para mostrar el texto, y ambas siguen mostrando algo
        razonable si el catálogo cambia o el id queda huérfano (LEFT, no INNER).
        """
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT m.reporte_id, m.tipo_servicio, m.descripcion_trabajo, "
                f"       m.observaciones, m.fecha_falla, m.tipo_falla_id, "
                f"       m.causa_demora_id, m.resultado, m.horas_paro, "
                f"       m.requiere_seguimiento, "
                f"       tf.nombre AS tipo_falla_nombre, "
                f"       cd.nombre AS causa_demora_nombre "
                f"FROM {cls.TABLE} m "
                f"LEFT JOIN HospitalGalenia.dbo.Cat_TiposFalla tf ON tf.id = m.tipo_falla_id "
                f"LEFT JOIN HospitalGalenia.dbo.Cat_CausasDemora cd ON cd.id = m.causa_demora_id "
                f"WHERE m.reporte_id = ?",
                (reporte_id,))
            fila = cursor.fetchone()
            if not fila:
                return None
            columnas = [c[0] for c in cursor.description]
            detalle = dict(zip(columnas, fila))
            detalle['tipo_servicio_txt'] = ETIQUETAS_SERVICIO.get(
                detalle.get('tipo_servicio'), detalle.get('tipo_servicio'))
            detalle['resultado_txt'] = ETIQUETAS_RESULTADO.get(detalle.get('resultado'))
            return detalle
        except Exception as e:
            current_app.logger.error(
                f"[ModelMantenimiento.get] reporte={reporte_id} | {e}")
            return None
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def horas_desde_falla(cls, fecha_falla, hasta=None):
        """
        Horas transcurridas entre la falla y `hasta` (por omisión, ahora).

        Es lo que explica un MTTR alto, y por eso se calcula en vez de pedirle
        a alguien que reste horas a mano. Vive aquí y no solo en el JS de la
        pantalla porque `liberar()` necesita el mismo cálculo del lado del
        servidor para el valor que de verdad se guarda.
        """
        if not fecha_falla:
            return None
        fin = hasta or datetime.now()
        return round((fin - fecha_falla).total_seconds() / 3600, 1)

    @classmethod
    def guardar(cls, db, reporte_id, **campos):
        """
        Guarda los campos que vengan, ignorando los que no.

        Es un UPDATE parcial a propósito: el formulario guarda por pestañas y
        mandar todos los campos en cada guardado borraría lo que la pestaña
        activa no conoce.
        """
        permitidos = {
            'tipo_servicio':       str,
            'descripcion_trabajo': str,
            'observaciones':       str,
            'fecha_falla':         None,
            'tipo_falla_id':       int,
            'causa_demora_id':     int,
            'resultado':           str,
            'horas_paro':          None,
            'requiere_seguimiento': bool,
        }

        asignaciones, valores = [], []
        for campo, tipo in permitidos.items():
            if campo not in campos:
                continue
            valor = campos[campo]

            if campo == 'tipo_servicio' and valor not in TIPOS_SERVICIO:
                continue
            if campo == 'resultado' and valor and valor not in RESULTADOS:
                continue
            if tipo is str and valor is not None:
                valor = str(valor).strip()[:MAX_TEXTO] or None
            elif tipo is int:
                valor = int(valor) if valor not in (None, '', '0') else None
            elif tipo is bool:
                valor = 1 if valor else 0

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
                f"[ModelMantenimiento.guardar] reporte={reporte_id} | {e}")
            try:
                db.rollback()
            except Exception:
                pass
            return False
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def get_catalogos(cls, db):
        """Tipos de falla y causas de demora activos, para los selectores."""
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                "SELECT id, nombre FROM HospitalGalenia.dbo.Cat_TiposFalla "
                "WHERE activo = 1 ORDER BY nombre")
            fallas = [{'id': f[0], 'nombre': f[1]} for f in cursor.fetchall()]

            cursor.execute(
                "SELECT id, nombre FROM HospitalGalenia.dbo.Cat_CausasDemora "
                "WHERE activo = 1 ORDER BY id")
            demoras = [{'id': f[0], 'nombre': f[1]} for f in cursor.fetchall()]

            cursor.execute(
                "SELECT id, nombre FROM HospitalGalenia.dbo.Cat_Areas "
                "WHERE activa = 1 ORDER BY nombre")
            areas = [{'id': f[0], 'nombre': f[1]} for f in cursor.fetchall()]

            cursor.execute(
                "SELECT id, nombre FROM HospitalGalenia.dbo.Cat_Tecnicos "
                "WHERE activo = 1 ORDER BY nombre")
            tecnicos = [{'id': f[0], 'nombre': f[1]} for f in cursor.fetchall()]

            return {'fallas': fallas, 'demoras': demoras,
                    'areas': areas, 'tecnicos': tecnicos}
        except Exception as e:
            current_app.logger.error(f"[ModelMantenimiento.get_catalogos] {e}")
            return {'fallas': [], 'demoras': [], 'areas': [], 'tecnicos': []}
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def sincronizar_programa(cls, db, equipo_id, fecha_servicio):
        """
        Actualiza el programa de mantenimiento del equipo tras liberar uno.

        MantenimientosEquipos es el calendario (una fila por equipo, con último
        y próximo). No es historial: eso ahora vive en Reportes. Aquí solo se
        empuja la fecha para que el dashboard de "qué me toca" deje de mostrar
        vencido lo que se acaba de hacer.

        Si el equipo no tiene programa no se inventa uno: que un preventivo
        exista no significa que deba repetirse cada N meses, y esa decisión es
        de quien arma el programa.
        """
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                "UPDATE HospitalGalenia.dbo.MantenimientosEquipos "
                "SET ultimo_mantenimiento = ?, "
                "    proximo_mantenimiento = DATEADD(month, frecuencia_meses, ?), "
                "    actualizado_en = GETDATE() "
                "WHERE equipo_id = ?",
                (fecha_servicio, fecha_servicio, equipo_id))
            actualizados = cursor.rowcount
            db.commit()
            return actualizados > 0
        except Exception as e:
            current_app.logger.error(
                f"[ModelMantenimiento.sincronizar_programa] equipo={equipo_id} | {e}")
            try:
                db.rollback()
            except Exception:
                pass
            return False
        finally:
            if cursor:
                cursor.close()
