"""
Ciclo de vida de un reporte.

Un reporte NO es un PDF: es un expediente que acumula datos, notas, fotos y
archivos mientras el trabajo ocurre, y que solo al liberarse produce un
documento. El PDF es una proyección de ese expediente, congelada.

De ahí el flujo:

    borrador ──► en_proceso ──► liberado
                     │
                     └────────► cancelado

Se guarda desde el primer momento, así que un preventivo que toma tres días o un
correctivo que espera dos semanas una requisición siguen existiendo entre
jornadas. El PDF aparece hasta `liberado`, y desde ahí es inmutable: se sirve el
archivo de disco, nunca se re-renderiza. El SHA-256 guardado lo vuelve
verificable.
"""

import json
from datetime import datetime
from decimal import Decimal

from flask import current_app

from models.reportes.folios import ModelFolios

BORRADOR   = 'borrador'
EN_PROCESO = 'en_proceso'
LIBERADO   = 'liberado'
CANCELADO  = 'cancelado'

ESTADOS = (BORRADOR, EN_PROCESO, LIBERADO, CANCELADO)

# Estados en los que el expediente todavía se puede editar.
EDITABLES = (BORRADOR, EN_PROCESO)

ETIQUETAS_ESTADO = {
    BORRADOR:   'Borrador',
    EN_PROCESO: 'En proceso',
    LIBERADO:   'Liberado',
    CANCELADO:  'Cancelado',
}

ETIQUETAS_TIPO = {
    'alta':            'Alta de equipo',
    'baja':            'Baja de equipo',
    'preventivo':      'Mantenimiento preventivo',
    'correctivo':      'Mantenimiento correctivo',
    'mantenimiento':   'Mantenimiento',        # legado
    'entrada':         'Entrada de equipo',
    'salida':          'Salida de equipo',
    'tecnovigilancia': 'Tecnovigilancia',
    'capacitacion':    'Capacitación',
    'carrito_rojo':    'Bitácora de carrito rojo',
}


class ModelReporteBase:
    TABLE = "HospitalGalenia.dbo.Reportes"
    TABLA_BITACORA = "HospitalGalenia.dbo.ReporteBitacora"

    COLS = """ id, tipo, folio, equipo_id, usuario_id, fecha, datos_json,
               archivo_pdf, estado, serie, area_id, tecnico_id, fecha_apertura,
               fecha_inicio, fecha_liberacion, liberado_por, pdf_sha256,
               pdf_reporte """

    # ── Apertura ───────────────────────────────────────────────

    @classmethod
    def abrir(cls, db, tipo, equipo_id, usuario_id, datos_equipo=None,
              area_id=None, tecnico_id=None):
        """
        Crea el expediente en estado borrador y devuelve (ok, id, folio).

        `datos_equipo` es el SNAPSHOT: la ficha del equipo tal como está hoy. Se
        congela aquí y no se vuelve a tocar, para que el documento diga lo que
        decía el día del trabajo aunque el equipo cambie de área después.

        equipo_id acepta None: la bitácora de carrito rojo no cuelga de un
        equipo, se genera por área y fecha.
        """
        serie = ModelFolios.serie_de_tipo(tipo)
        if not serie:
            return False, None, f"Tipo de reporte desconocido: {tipo}"

        folio, _numero = ModelFolios.siguiente(db, serie)
        if not folio:
            return False, None, "No se pudo generar el folio"

        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"INSERT INTO {cls.TABLE} "
                f"(tipo, folio, serie, equipo_id, usuario_id, datos_json, "
                f" estado, area_id, tecnico_id, fecha_apertura) "
                f"OUTPUT INSERTED.id "
                f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, GETDATE())",
                (tipo, folio, serie, equipo_id, usuario_id,
                 cls.serializar(datos_equipo or {}),
                 BORRADOR, area_id, tecnico_id)
            )
            reporte_id = cursor.fetchone()[0]
            db.commit()

            cls.registrar_evento(db, reporte_id, 'abierto',
                                 f"Reporte {folio} abierto", usuario_id)
            return True, reporte_id, folio

        except Exception as e:
            current_app.logger.error(
                f"[ModelReporteBase.abrir] tipo={tipo} equipo={equipo_id} | {e}")
            try:
                db.rollback()
            except Exception:
                pass
            return False, None, "No se pudo abrir el reporte"
        finally:
            if cursor:
                cursor.close()

    # ── Lectura ────────────────────────────────────────────────

    @classmethod
    def get_by_id(cls, db, reporte_id):
        """Un reporte con su snapshot ya deserializado en la clave 'datos'."""
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT {cls.COLS} FROM {cls.TABLE} WHERE id = ?", (reporte_id,))
            fila = cursor.fetchone()
            if not fila:
                return None
            columnas = [c[0] for c in cursor.description]
            return cls._hidratar(dict(zip(columnas, fila)))
        except Exception as e:
            current_app.logger.error(f"[ModelReporteBase.get_by_id] id={reporte_id} | {e}")
            return None
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def get_por_folio(cls, db, folio):
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT {cls.COLS} FROM {cls.TABLE} WHERE folio = ?", (folio,))
            fila = cursor.fetchone()
            if not fila:
                return None
            columnas = [c[0] for c in cursor.description]
            return cls._hidratar(dict(zip(columnas, fila)))
        except Exception as e:
            current_app.logger.error(f"[ModelReporteBase.get_por_folio] {folio} | {e}")
            return None
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def listar(cls, db, tipo=None, estado=None, equipo_id=None, area_id=None,
               tecnico_id=None, desde=None, hasta=None, q=None,
               page=1, per_page=15):
        """
        Centro de Reportes: listado paginado en el servidor.

        Devuelve (lista, total). La paginación va en SQL y no en Python porque
        el historial crece sin techo: traerse todo para mostrar 15 renglones
        deja de funcionar en cuanto haya un año de correctivos.
        """
        where = ["1 = 1"]
        params = []

        if tipo:
            where.append("r.tipo = ?")
            params.append(tipo)
        if estado:
            # Acepta uno o varios: el atajo "lo que está a medias" pide
            # borrador y en_proceso juntos, y las fichas de conteo uno solo.
            estados = (estado,) if isinstance(estado, str) else tuple(estado)
            where.append(f"r.estado IN ({', '.join('?' * len(estados))})")
            params.extend(estados)
        if equipo_id:
            where.append("r.equipo_id = ?")
            params.append(equipo_id)
        if area_id:
            where.append("r.area_id = ?")
            params.append(area_id)
        if tecnico_id:
            where.append("r.tecnico_id = ?")
            params.append(tecnico_id)
        if desde:
            where.append("r.fecha >= ?")
            params.append(desde)
        if hasta:
            # Hasta el final del día: si el usuario pide "hasta el 19", espera
            # ver lo del 19, no todo lo anterior a las 00:00 del 19.
            where.append("r.fecha < DATEADD(day, 1, CAST(? AS DATE))")
            params.append(hasta)
        if q:
            where.append(
                "(r.folio LIKE ? OR e.numero_inventario LIKE ? "
                " OR e.equipo_unidad LIKE ? OR e.numero_serie LIKE ? "
                " OR e.marca LIKE ? OR e.modelo LIKE ?)")
            patron = f"%{q.strip()}%"
            params.extend([patron] * 6)

        # Los JOIN van en el FROM compartido para que el COUNT y la página
        # cuenten exactamente lo mismo. Todos son LEFT: un reporte sin equipo
        # (carrito rojo), sin área o sin técnico asignado debe seguir saliendo
        # en el listado, no desaparecer de él.
        base_from = (
            f"FROM {cls.TABLE} r "
            f"LEFT JOIN HospitalGalenia.dbo.InventarioEquipos e ON e.id = r.equipo_id "
            f"LEFT JOIN HospitalGalenia.dbo.Cat_Areas a    ON a.id = r.area_id "
            f"LEFT JOIN HospitalGalenia.dbo.Cat_Tecnicos t ON t.id = r.tecnico_id "
            f"WHERE {' AND '.join(where)}")

        cursor = None
        try:
            cursor = db.cursor()

            cursor.execute(f"SELECT COUNT(*) {base_from}", tuple(params))
            total = cursor.fetchone()[0] or 0

            page = max(1, int(page or 1))
            offset = (page - 1) * per_page
            cursor.execute(
                f"SELECT r.id, r.tipo, r.folio, r.serie, r.estado, r.fecha, "
                f"       r.fecha_liberacion, r.equipo_id, r.archivo_pdf, "
                f"       e.numero_inventario, e.equipo_unidad, e.marca, e.modelo, "
                f"       e.imagen, a.nombre AS area_nombre, t.nombre AS tecnico_nombre "
                f"{base_from} "
                f"ORDER BY r.fecha DESC, r.id DESC "
                f"OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
                tuple(params) + (offset, per_page))
            columnas = [c[0] for c in cursor.description]
            filas = [dict(zip(columnas, f)) for f in cursor.fetchall()]
            return filas, total

        except Exception as e:
            current_app.logger.error(f"[ModelReporteBase.listar] {e}")
            return [], 0
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def stats(cls, db, tipo=None):
        """Conteo por estado, en una sola pasada."""
        cursor = None
        try:
            cursor = db.cursor()
            sql = (
                f"SELECT COUNT(*), "
                f"  SUM(CASE WHEN estado = 'borrador'   THEN 1 ELSE 0 END), "
                f"  SUM(CASE WHEN estado = 'en_proceso' THEN 1 ELSE 0 END), "
                f"  SUM(CASE WHEN estado = 'liberado'   THEN 1 ELSE 0 END), "
                f"  SUM(CASE WHEN estado = 'cancelado'  THEN 1 ELSE 0 END) "
                f"FROM {cls.TABLE}")
            params = ()
            if tipo:
                sql += " WHERE tipo = ?"
                params = (tipo,)
            cursor.execute(sql, params)
            fila = cursor.fetchone()
            return {
                'total':      fila[0] or 0,
                'borrador':   fila[1] or 0,
                'en_proceso': fila[2] or 0,
                'liberado':   fila[3] or 0,
                'cancelado':  fila[4] or 0,
            }
        except Exception as e:
            current_app.logger.error(f"[ModelReporteBase.stats] {e}")
            return {'total': 0, 'borrador': 0, 'en_proceso': 0,
                    'liberado': 0, 'cancelado': 0}
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def abiertos(cls, db, equipo_id=None, tipo=None, limite=None):
        """
        Expedientes que siguen en captura: borrador o en proceso.

        Existe aparte de `listar` porque responde a otra pregunta —"¿qué dejé a
        medias?"— y esa pregunta se hace desde tres pantallas distintas: el
        dashboard de mantenimientos, la apertura de un reporte nuevo (para no
        abrir dos del mismo equipo) y la ficha del equipo. Tenerla en un solo
        lugar evita que cada una arme su propio WHERE y se desincronicen.

        Ordena por el trabajo tocado más recientemente, que es el que casi
        siempre se busca.
        """
        where = ["r.estado IN ('borrador', 'en_proceso')"]
        params = []
        if equipo_id:
            where.append("r.equipo_id = ?")
            params.append(equipo_id)
        if tipo:
            # Acepta un tipo o varios: el dashboard de mantenimientos quiere
            # preventivos y correctivos juntos, la apertura quiere solo uno.
            tipos = (tipo,) if isinstance(tipo, str) else tuple(tipo)
            where.append(f"r.tipo IN ({', '.join('?' * len(tipos))})")
            params.extend(tipos)

        tope = f"TOP {int(limite)} " if limite else ""

        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT {tope}r.id, r.tipo, r.folio, r.estado, r.fecha, "
                f"       r.fecha_apertura, r.fecha_inicio, r.equipo_id, "
                f"       e.numero_inventario, e.equipo_unidad, e.marca, e.modelo, "
                f"       a.nombre AS area_nombre, t.nombre AS tecnico_nombre "
                f"FROM {cls.TABLE} r "
                f"LEFT JOIN HospitalGalenia.dbo.InventarioEquipos e ON e.id = r.equipo_id "
                f"LEFT JOIN HospitalGalenia.dbo.Cat_Areas a    ON a.id = r.area_id "
                f"LEFT JOIN HospitalGalenia.dbo.Cat_Tecnicos t ON t.id = r.tecnico_id "
                f"WHERE {' AND '.join(where)} "
                f"ORDER BY r.fecha_apertura DESC, r.id DESC",
                tuple(params))
            columnas = [c[0] for c in cursor.description]
            return [dict(zip(columnas, f)) for f in cursor.fetchall()]
        except Exception as e:
            current_app.logger.error(f"[ModelReporteBase.abiertos] {e}")
            return []
        finally:
            if cursor:
                cursor.close()

    # ── Cambios de estado ──────────────────────────────────────

    @classmethod
    def marcar_en_proceso(cls, db, reporte_id, usuario_id=None):
        """Primer guardado con contenido: el borrador pasa a trabajo en curso."""
        return cls._cambiar_estado(db, reporte_id, EN_PROCESO, usuario_id,
                                   desde=(BORRADOR,))

    @classmethod
    def liberar(cls, db, reporte_id, usuario_id, pdf_rel, pdf_reporte_rel,
                sha256, fecha_inicio=None):
        """
        Cierra el expediente y congela el PDF. Devuelve (ok, mensaje).

        A partir de aquí el reporte no se edita ni se re-renderiza. Si resulta
        que tiene un error, se cancela y se levanta uno nuevo: así funciona un
        documento firmado.
        """
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"UPDATE {cls.TABLE} SET estado = ?, archivo_pdf = ?, "
                f"       pdf_reporte = ?, pdf_sha256 = ?, "
                f"       fecha_liberacion = GETDATE(), liberado_por = ?, "
                f"       fecha_inicio = ISNULL(?, fecha_inicio) "
                f"WHERE id = ? AND estado IN (?, ?)",
                (LIBERADO, pdf_rel, pdf_reporte_rel, sha256, usuario_id,
                 fecha_inicio, reporte_id, BORRADOR, EN_PROCESO))
            if cursor.rowcount == 0:
                return False, "El reporte ya estaba liberado o cancelado"
            db.commit()

            cls.registrar_evento(db, reporte_id, 'liberado',
                                 f"PDF congelado ({(sha256 or '')[:12]}…)",
                                 usuario_id)
            return True, "Reporte liberado"

        except Exception as e:
            current_app.logger.error(f"[ModelReporteBase.liberar] id={reporte_id} | {e}")
            try:
                db.rollback()
            except Exception:
                pass
            return False, "No se pudo liberar el reporte"
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def cancelar(cls, db, reporte_id, usuario_id=None, motivo=None):
        """
        Cancela un reporte. No se borra: se conserva con su folio.

        Borrarlo dejaría un hueco en la numeración que nadie podría explicar
        después, y perdería la evidencia de que alguien empezó a trabajar en
        ese equipo.
        """
        ok = cls._cambiar_estado(db, reporte_id, CANCELADO, usuario_id,
                                 desde=(BORRADOR, EN_PROCESO))
        if ok:
            cls.registrar_evento(db, reporte_id, 'cancelado',
                                 motivo or 'Sin motivo especificado', usuario_id)
        return ok

    @classmethod
    def _cambiar_estado(cls, db, reporte_id, nuevo, usuario_id=None, desde=None):
        cursor = None
        try:
            cursor = db.cursor()
            sql = f"UPDATE {cls.TABLE} SET estado = ? WHERE id = ?"
            params = [nuevo, reporte_id]
            if desde:
                marcas = ', '.join('?' for _ in desde)
                sql += f" AND estado IN ({marcas})"
                params.extend(desde)
            cursor.execute(sql, tuple(params))
            cambiado = cursor.rowcount > 0
            db.commit()
            return cambiado
        except Exception as e:
            current_app.logger.error(
                f"[ModelReporteBase._cambiar_estado] id={reporte_id} -> {nuevo} | {e}")
            try:
                db.rollback()
            except Exception:
                pass
            return False
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def actualizar_cabecera(cls, db, reporte_id, area_id=None, tecnico_id=None,
                            fecha_inicio=None):
        """Campos de la cabecera que se capturan durante el trabajo."""
        campos, valores = [], []
        if area_id is not None:
            campos.append("area_id = ?")
            valores.append(area_id or None)
        if tecnico_id is not None:
            campos.append("tecnico_id = ?")
            valores.append(tecnico_id or None)
        if fecha_inicio is not None:
            campos.append("fecha_inicio = ?")
            valores.append(fecha_inicio or None)
        if not campos:
            return True

        cursor = None
        try:
            cursor = db.cursor()
            valores.append(reporte_id)
            cursor.execute(
                f"UPDATE {cls.TABLE} SET {', '.join(campos)} "
                f"WHERE id = ? AND estado IN ('{BORRADOR}', '{EN_PROCESO}')",
                tuple(valores))
            db.commit()
            return True
        except Exception as e:
            current_app.logger.error(
                f"[ModelReporteBase.actualizar_cabecera] id={reporte_id} | {e}")
            try:
                db.rollback()
            except Exception:
                pass
            return False
        finally:
            if cursor:
                cursor.close()

    # ── Bitácora ───────────────────────────────────────────────

    @classmethod
    def registrar_evento(cls, db, reporte_id, evento, detalle=None, usuario_id=None):
        """
        Anota un evento en la bitácora de auditoría.

        Esto lo escribe el sistema y nadie lo edita — es lo que responde "quién
        liberó este reporte y cuándo" frente a un auditor. Las anotaciones que
        el técnico escribe a mano van en ReporteNotas, que es otra cosa.

        Un fallo aquí no aborta la operación que se estaba registrando: perder
        una línea de bitácora es malo, perder el reporte es peor.
        """
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"INSERT INTO {cls.TABLA_BITACORA} "
                f"(reporte_id, evento, detalle, usuario_id) VALUES (?, ?, ?, ?)",
                (reporte_id, evento[:30], (detalle or '')[:500] or None, usuario_id))
            db.commit()
            return True
        except Exception as e:
            current_app.logger.warning(
                f"[ModelReporteBase.registrar_evento] id={reporte_id} {evento} | {e}")
            return False
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def get_bitacora(cls, db, reporte_id):
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT b.id, b.evento, b.detalle, b.fecha, b.usuario_id, "
                f"       u.NombreUsuario "
                f"FROM {cls.TABLA_BITACORA} b "
                f"LEFT JOIN HospitalGalenia.dbo.usuario u ON u.IDusuario = b.usuario_id "
                f"WHERE b.reporte_id = ? ORDER BY b.fecha, b.id", (reporte_id,))
            columnas = [c[0] for c in cursor.description]
            return [dict(zip(columnas, f)) for f in cursor.fetchall()]
        except Exception as e:
            current_app.logger.error(f"[ModelReporteBase.get_bitacora] {e}")
            return []
        finally:
            if cursor:
                cursor.close()

    # ── Serialización del snapshot ─────────────────────────────

    @classmethod
    def serializar(cls, datos):
        """
        Convierte el snapshot a JSON, resolviendo lo que json no sabe manejar.

        Se recorre en profundidad a propósito: una versión anterior aplanaba con
        str() y dejaba las listas guardadas como repr() de Python, que después
        había que recuperar con ast.literal_eval.
        """
        return json.dumps(cls._limpiar(datos), ensure_ascii=False)

    @classmethod
    def _limpiar(cls, valor):
        if isinstance(valor, dict):
            return {k: cls._limpiar(v) for k, v in valor.items()}
        if isinstance(valor, (list, tuple)):
            return [cls._limpiar(v) for v in valor]
        if isinstance(valor, Decimal):
            return float(valor)
        if isinstance(valor, datetime):
            return valor.strftime('%Y-%m-%d %H:%M:%S')
        if hasattr(valor, 'strftime'):
            return valor.strftime('%Y-%m-%d')
        if isinstance(valor, bytes):
            return valor.decode('utf-8', errors='replace')
        return valor

    @classmethod
    def _hidratar(cls, reporte):
        """Agrega la clave 'datos' con el snapshot deserializado."""
        if not reporte:
            return reporte
        crudo = reporte.get('datos_json')
        try:
            reporte['datos'] = json.loads(crudo) if crudo else {}
        except (ValueError, TypeError):
            current_app.logger.warning(
                f"[ModelReporteBase] datos_json ilegible en el reporte {reporte.get('id')}")
            reporte['datos'] = {}
        reporte['editable'] = reporte.get('estado') in EDITABLES
        return reporte
