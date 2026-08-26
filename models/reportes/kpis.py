"""
Consultas de estadística sobre reportes ya liberados.

Todo aquí lee, nada escribe. Se apoya en lo que ya existe (Reportes,
RepMantenimiento, ReporteLineas) en vez de mantener un resumen aparte: un
número que se pudiera desincronizar de los reportes que lo originan sería
peor que no tenerlo, porque una auditoría no podría confiar en él.

Solo cuentan los reportes `estado = 'liberado'`: uno en borrador o cancelado
no es un dato histórico todavía. La fecha que ancla cada período es
`fecha_liberacion` — es la misma que ya usa el PDF como "la fecha del
documento", así que un preventivo que empezó el lunes y liberó el miércoles
cuenta para el mes en que de verdad se cerró.

Lo que el plan pedía y NO está aquí — "cumplimiento del programa
(ejecutados/programados por mes)" — no se puede calcular con el esquema
actual: `MantenimientosEquipos.proximo_mantenimiento` es un solo campo que se
sobrescribe cada vez que se libera un preventivo (`sincronizar_programa`), así
que no queda un historial de qué estaba programado en un mes ya pasado.
Reconstruirlo pediría una tabla de bitácora de programación que nadie pidió
todavía. Lo que sí responde esa pregunta, con el esquema de hoy, es el
dashboard de `/mantenimientos` (al día / próximo / vencido, en este momento).
"""

from flask import current_app

MESES_ES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
           'jul', 'ago', 'sep', 'oct', 'nov', 'dic']


class ModelKPIs:
    # ── Costos ───────────────────────────────────────────────────

    @classmethod
    def costo_por_periodo(cls, db, meses=12):
        """
        Costo total por mes, en los últimos `meses`. Un mes sin reportes
        liberados sale con total 0 — la gráfica necesita el hueco, no que el
        mes desaparezca de la serie.
        """
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                "SELECT YEAR(r.fecha_liberacion) AS anio, MONTH(r.fecha_liberacion) AS mes, "
                "       SUM(l.importe) AS total "
                "FROM HospitalGalenia.dbo.Reportes r "
                "JOIN HospitalGalenia.dbo.ReporteLineas l ON l.reporte_id = r.id "
                "WHERE r.estado = 'liberado' "
                "  AND r.fecha_liberacion >= DATEADD(month, -?, GETDATE()) "
                "GROUP BY YEAR(r.fecha_liberacion), MONTH(r.fecha_liberacion)",
                (meses,))
            por_mes = {(f[0], f[1]): float(f[2] or 0) for f in cursor.fetchall()}

            # Se arma la serie completa de meses aunque no traigan dato, para
            # que la gráfica muestre el hueco en vez de comprimir el eje.
            from datetime import date
            hoy = date.today()
            serie = []
            for i in range(meses - 1, -1, -1):
                y, m = hoy.year, hoy.month - i
                while m <= 0:
                    m += 12
                    y -= 1
                serie.append({
                    'etiqueta': f"{MESES_ES[m - 1]} {str(y)[2:]}",
                    'total': por_mes.get((y, m), 0.0),
                })
            return serie
        except Exception as e:
            current_app.logger.error(f"[ModelKPIs.costo_por_periodo] {e}")
            return []
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def costo_por_equipo(cls, db, top=8, meses=None):
        """Ranking de los equipos con más costo acumulado."""
        where = "r.estado = 'liberado'"
        params = []
        if meses:
            where += " AND r.fecha_liberacion >= DATEADD(month, -?, GETDATE())"
            params.append(meses)

        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT TOP {int(top)} e.id, e.equipo_unidad, e.numero_inventario, "
                f"       SUM(l.importe) AS total "
                f"FROM HospitalGalenia.dbo.Reportes r "
                f"JOIN HospitalGalenia.dbo.ReporteLineas l ON l.reporte_id = r.id "
                f"JOIN HospitalGalenia.dbo.InventarioEquipos e ON e.id = r.equipo_id "
                f"WHERE {where} "
                f"GROUP BY e.id, e.equipo_unidad, e.numero_inventario "
                f"ORDER BY total DESC",
                tuple(params))
            return [{'id': f[0], 'nombre': f[1], 'inventario': f[2], 'total': float(f[3] or 0)}
                   for f in cursor.fetchall()]
        except Exception as e:
            current_app.logger.error(f"[ModelKPIs.costo_por_equipo] {e}")
            return []
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def costo_preventivo_vs_correctivo(cls, db, meses=6):
        """Costo mensual de los últimos `meses`, separado por tipo."""
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                "SELECT YEAR(r.fecha_liberacion), MONTH(r.fecha_liberacion), r.tipo, "
                "       SUM(l.importe) "
                "FROM HospitalGalenia.dbo.Reportes r "
                "JOIN HospitalGalenia.dbo.ReporteLineas l ON l.reporte_id = r.id "
                "WHERE r.estado = 'liberado' AND r.tipo IN ('preventivo', 'correctivo') "
                "  AND r.fecha_liberacion >= DATEADD(month, -?, GETDATE()) "
                "GROUP BY YEAR(r.fecha_liberacion), MONTH(r.fecha_liberacion), r.tipo",
                (meses,))
            crudo = {}
            for anio, mes, tipo, total in cursor.fetchall():
                crudo.setdefault((anio, mes), {})[tipo] = float(total or 0)

            from datetime import date
            hoy = date.today()
            serie = []
            for i in range(meses - 1, -1, -1):
                y, m = hoy.year, hoy.month - i
                while m <= 0:
                    m += 12
                    y -= 1
                valores = crudo.get((y, m), {})
                serie.append({
                    'etiqueta':    f"{MESES_ES[m - 1]} {str(y)[2:]}",
                    'preventivo':  valores.get('preventivo', 0.0),
                    'correctivo':  valores.get('correctivo', 0.0),
                })
            return serie
        except Exception as e:
            current_app.logger.error(f"[ModelKPIs.costo_preventivo_vs_correctivo] {e}")
            return []
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def costo_por_clase(cls, db, meses=None):
        """Costo total agrupado por clase de renglón (refacción, consumible…)."""
        where = "r.estado = 'liberado'"
        params = []
        if meses:
            where += " AND r.fecha_liberacion >= DATEADD(month, -?, GETDATE())"
            params.append(meses)

        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT l.clase, SUM(l.importe) "
                f"FROM HospitalGalenia.dbo.ReporteLineas l "
                f"JOIN HospitalGalenia.dbo.Reportes r ON r.id = l.reporte_id "
                f"WHERE {where} "
                f"GROUP BY l.clase "
                f"ORDER BY SUM(l.importe) DESC",
                tuple(params))
            from models.reportes.lineas import ETIQUETAS as ETIQUETAS_CLASE
            return [{'clase': f[0], 'etiqueta': ETIQUETAS_CLASE.get(f[0], f[0]),
                    'total': float(f[1] or 0)} for f in cursor.fetchall()]
        except Exception as e:
            current_app.logger.error(f"[ModelKPIs.costo_por_clase] {e}")
            return []
        finally:
            if cursor:
                cursor.close()

    # ── Tiempo de atención ──────────────────────────────────────────

    @classmethod
    def mttr_horas(cls, db, meses=None):
        """
        MTTR: promedio de horas de paro de los correctivos liberados.
        Usa `horas_paro` (ya cuadrado, y corregible a mano) en vez de volver a
        restar fechas — es el mismo valor que el PDF de cada correctivo
        imprime, así que el promedio es trazable reporte por reporte.
        """
        where = "r.estado = 'liberado' AND r.tipo = 'correctivo' AND m.horas_paro IS NOT NULL"
        params = []
        if meses:
            where += " AND r.fecha_liberacion >= DATEADD(month, -?, GETDATE())"
            params.append(meses)

        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT AVG(m.horas_paro), COUNT(*) "
                f"FROM HospitalGalenia.dbo.RepMantenimiento m "
                f"JOIN HospitalGalenia.dbo.Reportes r ON r.id = m.reporte_id "
                f"WHERE {where}",
                tuple(params))
            promedio, n = cursor.fetchone()
            return {'horas': float(promedio) if promedio is not None else None, 'n': n or 0}
        except Exception as e:
            current_app.logger.error(f"[ModelKPIs.mttr_horas] {e}")
            return {'horas': None, 'n': 0}
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def mtbf_dias(cls, db):
        """
        MTBF: promedio de días entre correctivos consecutivos del mismo
        equipo. Un equipo con un solo correctivo no aporta intervalo —hace
        falta un "entre" para calcular algo—, así que se descarta solo, no
        se cuenta como intervalo de 0.
        """
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                "WITH ordenados AS ( "
                "  SELECT r.equipo_id, r.fecha_liberacion, "
                "         LAG(r.fecha_liberacion) OVER ( "
                "             PARTITION BY r.equipo_id ORDER BY r.fecha_liberacion "
                "         ) AS anterior "
                "  FROM HospitalGalenia.dbo.Reportes r "
                "  WHERE r.estado = 'liberado' AND r.tipo = 'correctivo' "
                "    AND r.equipo_id IS NOT NULL "
                ") "
                "SELECT AVG(CAST(DATEDIFF(DAY, anterior, fecha_liberacion) AS FLOAT)), COUNT(*) "
                "FROM ordenados WHERE anterior IS NOT NULL")
            promedio, n = cursor.fetchone()
            return {'dias': float(promedio) if promedio is not None else None, 'n': n or 0}
        except Exception as e:
            current_app.logger.error(f"[ModelKPIs.mtbf_dias] {e}")
            return {'dias': None, 'n': 0}
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def causas_demora_frecuentes(cls, db, top=6):
        """Ranking de causas de demora, solo correctivos liberados."""
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT TOP {int(top)} c.nombre, COUNT(*) AS n "
                f"FROM HospitalGalenia.dbo.RepMantenimiento m "
                f"JOIN HospitalGalenia.dbo.Reportes r ON r.id = m.reporte_id "
                f"JOIN HospitalGalenia.dbo.Cat_CausasDemora c ON c.id = m.causa_demora_id "
                f"WHERE r.estado = 'liberado' AND r.tipo = 'correctivo' "
                f"GROUP BY c.nombre ORDER BY n DESC")
            return [{'nombre': f[0], 'n': f[1]} for f in cursor.fetchall()]
        except Exception as e:
            current_app.logger.error(f"[ModelKPIs.causas_demora_frecuentes] {e}")
            return []
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def tipos_falla_frecuentes(cls, db, top=6):
        """Ranking de tipos de falla, solo correctivos liberados."""
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT TOP {int(top)} tf.nombre, COUNT(*) AS n "
                f"FROM HospitalGalenia.dbo.RepMantenimiento m "
                f"JOIN HospitalGalenia.dbo.Reportes r ON r.id = m.reporte_id "
                f"JOIN HospitalGalenia.dbo.Cat_TiposFalla tf ON tf.id = m.tipo_falla_id "
                f"WHERE r.estado = 'liberado' AND r.tipo = 'correctivo' "
                f"GROUP BY tf.nombre ORDER BY n DESC")
            return [{'nombre': f[0], 'n': f[1]} for f in cursor.fetchall()]
        except Exception as e:
            current_app.logger.error(f"[ModelKPIs.tipos_falla_frecuentes] {e}")
            return []
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def equipos_reincidentes(cls, db, top=6, meses=12):
        """Equipos con más correctivos liberados en la ventana reciente."""
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT TOP {int(top)} e.id, e.equipo_unidad, e.numero_inventario, COUNT(*) AS n "
                f"FROM HospitalGalenia.dbo.Reportes r "
                f"JOIN HospitalGalenia.dbo.InventarioEquipos e ON e.id = r.equipo_id "
                f"WHERE r.estado = 'liberado' AND r.tipo = 'correctivo' "
                f"  AND r.fecha_liberacion >= DATEADD(month, -?, GETDATE()) "
                f"GROUP BY e.id, e.equipo_unidad, e.numero_inventario "
                f"HAVING COUNT(*) > 1 "
                f"ORDER BY n DESC",
                (meses,))
            return [{'id': f[0], 'nombre': f[1], 'inventario': f[2], 'n': f[3]}
                   for f in cursor.fetchall()]
        except Exception as e:
            current_app.logger.error(f"[ModelKPIs.equipos_reincidentes] {e}")
            return []
        finally:
            if cursor:
                cursor.close()

    # ── Resumen ──────────────────────────────────────────────────

    @classmethod
    def resumen_snapshot(cls, db, meses=12):
        """Conteos simples para la fila de KPI del encabezado."""
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                "SELECT tipo, COUNT(*) FROM HospitalGalenia.dbo.Reportes "
                "WHERE estado = 'liberado' AND fecha_liberacion >= DATEADD(month, -?, GETDATE()) "
                "GROUP BY tipo",
                (meses,))
            por_tipo = {f[0]: f[1] for f in cursor.fetchall()}

            cursor.execute(
                "SELECT SUM(l.importe) FROM HospitalGalenia.dbo.ReporteLineas l "
                "JOIN HospitalGalenia.dbo.Reportes r ON r.id = l.reporte_id "
                "WHERE r.estado = 'liberado' AND r.fecha_liberacion >= DATEADD(month, -?, GETDATE())",
                (meses,))
            costo_total = cursor.fetchone()[0]

            return {
                'preventivos':  por_tipo.get('preventivo', 0),
                'correctivos':  por_tipo.get('correctivo', 0),
                'movimientos':  por_tipo.get('entrada', 0) + por_tipo.get('salida', 0),
                'tecnovigilancia': por_tipo.get('tecnovigilancia', 0),
                'costo_total':  float(costo_total or 0),
            }
        except Exception as e:
            current_app.logger.error(f"[ModelKPIs.resumen_snapshot] {e}")
            return {'preventivos': 0, 'correctivos': 0, 'movimientos': 0,
                    'tecnovigilancia': 0, 'costo_total': 0.0}
        finally:
            if cursor:
                cursor.close()

    # ── Expediente de un equipo ──────────────────────────────────────

    @classmethod
    def expediente_equipo(cls, db, equipo_id):
        """
        Línea de vida de un equipo: todos sus reportes, de cualquier tipo y
        estado, en orden cronológico descendente. Responde "¿qué le ha
        pasado a este equipo?" — por eso incluye también los que siguen en
        captura o se cancelaron, marcados como tales, en vez de solo los
        liberados: un correctivo cancelado a medias también es parte de la
        historia.
        """
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                "SELECT r.id, r.tipo, r.folio, r.estado, r.fecha, r.fecha_liberacion, "
                "       t.nombre AS tecnico_nombre, a.nombre AS area_nombre "
                "FROM HospitalGalenia.dbo.Reportes r "
                "LEFT JOIN HospitalGalenia.dbo.Cat_Tecnicos t ON t.id = r.tecnico_id "
                "LEFT JOIN HospitalGalenia.dbo.Cat_Areas a ON a.id = r.area_id "
                "WHERE r.equipo_id = ? "
                "ORDER BY COALESCE(r.fecha_liberacion, r.fecha) DESC, r.id DESC",
                (equipo_id,))
            columnas = [c[0] for c in cursor.description]
            reportes = [dict(zip(columnas, f)) for f in cursor.fetchall()]

            # El costo de cada reporte se anexa aparte: la mayoría de los
            # tipos no tienen renglones, y una columna JOIN LEFT por cada uno
            # traería NULLs que no vale la pena cargar si no se usan.
            if reportes:
                ids = tuple(r['id'] for r in reportes)
                marcadores = ', '.join('?' * len(ids))
                cursor.execute(
                    f"SELECT reporte_id, SUM(importe) FROM HospitalGalenia.dbo.ReporteLineas "
                    f"WHERE reporte_id IN ({marcadores}) GROUP BY reporte_id",
                    ids)
                costos = {f[0]: float(f[1] or 0) for f in cursor.fetchall()}
                for r in reportes:
                    r['costo'] = costos.get(r['id'])

            return reportes
        except Exception as e:
            current_app.logger.error(f"[ModelKPIs.expediente_equipo] equipo={equipo_id} | {e}")
            return []
        finally:
            if cursor:
                cursor.close()
