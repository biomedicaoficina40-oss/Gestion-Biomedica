# models/ModelBLE.py
# Sistema de Localizacion BLE — Hospital Galenia
# Sigue exactamente el patron de ModelInventario:
#   - Clase con @classmethod
#   - Constantes TABLE / COLS
#   - try / except / finally con cursor.close() garantizado
#   - current_app.logger para todos los errores
#   - Nunca lanza excepcion hacia la ruta; retorna None / [] / False en fallo

from datetime import datetime, timedelta
from flask import current_app


class ModelBLE:

    # ── Tablas ────────────────────────────────────────────────
    T_AREAS    = "HospitalGalenia.dbo.ble_areas"
    T_BEACONS  = "HospitalGalenia.dbo.ble_beacons"
    T_LECTURAS = "HospitalGalenia.dbo.ble_lecturas"
    T_POS      = "HospitalGalenia.dbo.ble_posicion_actual"
    T_INV      = "HospitalGalenia.dbo.InventarioEquipos"
    T_REGLAS   = "HospitalGalenia.dbo.ble_reglas_alerta"
    # Token compartido con los ESP32
    # Mover a config.py / variable de entorno antes de produccion
    BLE_TOKEN  = "galenia-ble-2025"

    # RSSI minimo aceptado (igual que el firmware)
    RSSI_MIN   = -85

    # Minutos sin reporte para marcar Sin senal
    TIMEOUT_SIN_SENAL = 2

    # Minutos sin reporte para alerta de bateria
    TIMEOUT_BATERIA   = 10

    # ══════════════════════════════════════════════════════════
    #  SEGURIDAD
    # ══════════════════════════════════════════════════════════

    @classmethod
    def validar_token(cls, token: str) -> bool:
        """Compara el token del ESP32 con el esperado."""
        return token == cls.BLE_TOKEN

    # ══════════════════════════════════════════════════════════
    #  AREAS
    # ══════════════════════════════════════════════════════════

    @classmethod
    def get_area_por_esp32(cls, db, esp32_id: str) -> dict | None:
        """
        Verifica que el ESP32 este registrado y activo.
        Retorna el area o None si no existe / esta inactiva.
        Llamado en cada POST de lecturas como primer filtro de seguridad.
        """
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT id, nombre, piso "
                f"FROM {cls.T_AREAS} "
                f"WHERE esp32_id = ? AND activa = 1",
                (esp32_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {"id": row[0], "nombre": row[1], "piso": row[2]}

        except Exception as e:
            current_app.logger.error(
                f"[ModelBLE.get_area_por_esp32] esp32_id={esp32_id} | {e}"
            )
            return None

        finally:
            if cursor:
                cursor.close()

    @classmethod
    def get_todas_las_areas(cls, db) -> list[dict]:
        """Lista de areas activas para el panel y formularios."""
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT id, nombre, piso, esp32_id "
                f"FROM {cls.T_AREAS} "
                f"WHERE activa = 1 "
                f"ORDER BY piso, nombre"
            )
            rows = cursor.fetchall()
            return [
                {"id": r[0], "nombre": r[1], "piso": r[2], "esp32_id": r[3]}
                for r in rows
            ]

        except Exception as e:
            current_app.logger.error(f"[ModelBLE.get_todas_las_areas] {e}")
            return []

        finally:
            if cursor:
                cursor.close()

    @classmethod
    def registrar_area(cls, db, nombre: str, piso: int, esp32_id: str) -> int | None:
        """
        Alta de area nueva.
        Retorna el id generado o None si falla.
        Uso: script de carga inicial de los 10 ESP32 (Fase 4).
        """
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"INSERT INTO {cls.T_AREAS} (nombre, piso, esp32_id) "
                f"OUTPUT INSERTED.id "
                f"VALUES (?, ?, ?)",
                (nombre, piso, esp32_id)
            )
            new_id = cursor.fetchone()[0]
            db.commit()
            return new_id

        except Exception as e:
            current_app.logger.error(
                f"[ModelBLE.registrar_area] nombre={nombre} esp32_id={esp32_id} | {e}"
            )
            db.rollback()
            return None

        finally:
            if cursor:
                cursor.close()

    # ══════════════════════════════════════════════════════════
    #  BEACONS
    # ══════════════════════════════════════════════════════════

    @classmethod
    def get_beacon_por_mac(cls, db, mac: str) -> dict | None:
        """
        Busca un beacon por MAC.
        Retorna None si la MAC no esta registrada o el beacon esta inactivo.
        La ruta ignora silenciosamente las MACs desconocidas.
        """
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT id, nombre, equipo_id "
                f"FROM {cls.T_BEACONS} "
                f"WHERE mac = ? AND activo = 1",
                (mac,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {"id": row[0], "nombre": row[1], "equipo_id": row[2]}

        except Exception as e:
            current_app.logger.error(
                f"[ModelBLE.get_beacon_por_mac] mac={mac} | {e}"
            )
            return None

        finally:
            if cursor:
                cursor.close()

    @classmethod
    def registrar_beacon(cls, db, mac: str,
                         nombre: str = None,
                         equipo_id: int = None) -> int | None:
        """
        Alta de beacon nuevo.
        Retorna el id generado o None si falla.
        Uso: script de carga de MACs capturadas por ESP32 (Fase 4).
        """
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"INSERT INTO {cls.T_BEACONS} (mac, nombre, equipo_id) "
                f"OUTPUT INSERTED.id "
                f"VALUES (?, ?, ?)",
                (mac, nombre, equipo_id)
            )
            new_id = cursor.fetchone()[0]
            db.commit()
            return new_id

        except Exception as e:
            current_app.logger.error(
                f"[ModelBLE.registrar_beacon] mac={mac} | {e}"
            )
            db.rollback()
            return None

        finally:
            if cursor:
                cursor.close()

    @classmethod
    def registrar_beacon_auto(cls, db, mac: str, nombre: str) -> int | None:
        """
        Auto-registro de beacon desconocido durante recepción de lecturas.
        Se diferencia de registrar_beacon() en que:
        - Siempre genera un nombre automático si no se pasa uno
        - Loguea la MAC como 'auto-registrada' para auditoría
        - No lanza excepción; retorna None si falla (la ruta continúa)
        Retorna el id generado o None si falla.
        """
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"INSERT INTO {cls.T_BEACONS} (mac, nombre, activo) "
                f"OUTPUT INSERTED.id "
                f"VALUES (?, ?, 1)",
                (mac.upper(), nombre)
            )
            new_id = cursor.fetchone()[0]
            db.commit()
            current_app.logger.info(
                f"[ModelBLE.registrar_beacon_auto] MAC={mac} id={new_id}"
            )
            return new_id

        except Exception as e:
            current_app.logger.error(
                f"[ModelBLE.registrar_beacon_auto] mac={mac} | {e}"
            )
            db.rollback()
            return None

        finally:
            if cursor:
                cursor.close()

    @classmethod
    def get_todos_los_beacons(cls, db) -> list[dict]:
        """
        Lista completa de beacons activos con nombre del equipo asignado.
        JOIN a InventarioEquipos usando la columna beacon_id existente.
        """
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT "
                f"  b.id, b.mac, b.nombre, b.equipo_id, "
                f"  b.bateria_pct, b.activo, "
                f"  e.equipo_unidad "
                f"FROM {cls.T_BEACONS} b "
                f"LEFT JOIN {cls.T_INV} e ON e.beacon_id = b.id "
                f"WHERE b.activo = 1 "
                f"ORDER BY b.nombre"
            )
            rows = cursor.fetchall()
            return [
                {
                    "id":            r[0],
                    "mac":           r[1],
                    "nombre":        r[2] or "",
                    "equipo_id":     r[3],
                    "bateria_pct":   r[4],
                    "activo":        r[5],
                    "equipo_nombre": r[6] or "Sin asignar",
                }
                for r in rows
            ]

        except Exception as e:
            current_app.logger.error(f"[ModelBLE.get_todos_los_beacons] {e}")
            return []

        finally:
            if cursor:
                cursor.close()

    # ══════════════════════════════════════════════════════════
    #  LECTURAS
    # ══════════════════════════════════════════════════════════

    @classmethod
    def insertar_lectura(cls, db, beacon_id: int,
                         area_id: int, rssi: int) -> bool:
        """
        Guarda una lectura RSSI en el historial ble_lecturas.
        Retorna True si se guardo correctamente, False si fallo.
        """
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"INSERT INTO {cls.T_LECTURAS} (beacon_id, area_id, rssi) "
                f"VALUES (?, ?, ?)",
                (beacon_id, area_id, rssi)
            )
            db.commit()
            return True

        except Exception as e:
            current_app.logger.error(
                f"[ModelBLE.insertar_lectura] "
                f"beacon_id={beacon_id} area_id={area_id} rssi={rssi} | {e}"
            )
            db.rollback()
            return False

        finally:
            if cursor:
                cursor.close()

    @classmethod
    def get_historial_equipo(cls, db, equipo_id: int,
                             horas: int = 24) -> list[dict]:
        """
        Movimientos de un equipo en las ultimas N horas.
        Hace JOIN por beacon_id en InventarioEquipos para seguir
        la relacion existente en la tabla real.
        """
        cursor = None
        try:
            desde = datetime.utcnow() - timedelta(hours=horas)
            cursor = db.cursor()
            cursor.execute(
                f"SELECT a.nombre, a.piso, l.rssi, l.timestamp "
                f"FROM {cls.T_LECTURAS} l "
                f"JOIN {cls.T_BEACONS} b  ON b.id = l.beacon_id "
                f"JOIN {cls.T_AREAS}   a  ON a.id = l.area_id "
                f"JOIN {cls.T_INV}     e  ON e.beacon_id = b.id "
                f"WHERE e.id = ? AND l.timestamp >= ? "
                f"ORDER BY l.timestamp DESC",
                (equipo_id, desde)
            )
            rows = cursor.fetchall()
            return [
                {
                    "area":      r[0],
                    "piso":      r[1],
                    "rssi":      r[2],
                    "timestamp": r[3].isoformat() if r[3] else None,
                }
                for r in rows
            ]

        except Exception as e:
            current_app.logger.error(
                f"[ModelBLE.get_historial_equipo] equipo_id={equipo_id} | {e}"
            )
            return []

        finally:
            if cursor:
                cursor.close()

    # ══════════════════════════════════════════════════════════
    #  POSICION ACTUAL
    # ══════════════════════════════════════════════════════════

    @classmethod
    def upsert_posicion_actual(cls, db, beacon_id: int,
                            area_id: int, rssi: int) -> bool:
        """
        Actualiza la posición actual del beacon.
        - Si ya existe en la misma área: refresca ultima_vez y rssi_max si mejora.
        - Si existe en área distinta: solo mueve si el nuevo RSSI supera en ≥5 dBm
        al mejor registrado (anti-parpadeo entre áreas adyacentes).
        - Si no existe: inserta.
        En TODOS los casos donde el beacon ya existe actualiza ultima_vez
        para evitar falsos 'Sin señal'.
        """
        cursor = None
        try:
            ahora = datetime.utcnow()
            cursor = db.cursor()

            # ── 1. Leer estado actual ─────────────────────────────────
            cursor.execute(
                f"SELECT area_id, rssi_max "
                f"FROM {cls.T_POS} "
                f"WHERE beacon_id = ?",
                (beacon_id,)
            )
            row = cursor.fetchone()

            if row is None:
                # ── 2a. Primera vez que se ve este beacon ─────────────
                cursor.execute(
                    f"INSERT INTO {cls.T_POS} "
                    f"(beacon_id, area_id, rssi_max, ultima_vez, estado) "
                    f"VALUES (?, ?, ?, ?, 'Localizado')",
                    (beacon_id, area_id, rssi, ahora)
                )

            else:
                area_actual  = row[0]
                rssi_max_act = row[1] if row[1] is not None else -100

                if area_actual == area_id:
                    # ── 2b. Misma área: refrescar siempre ────────────
                    nuevo_rssi_max = rssi if rssi > rssi_max_act else rssi_max_act
                    cursor.execute(
                        f"UPDATE {cls.T_POS} "
                        f"SET rssi_max = ?, ultima_vez = ?, estado = 'Localizado' "
                        f"WHERE beacon_id = ?",
                        (nuevo_rssi_max, ahora, beacon_id)
                    )
                elif rssi > (rssi_max_act - 5):
                    # ── 2c. Área distinta con señal suficientemente mejor:
                    #        mover el beacon (y actualizar ultima_vez) ──────
                    cursor.execute(
                        f"UPDATE {cls.T_POS} "
                        f"SET area_id = ?, rssi_max = ?, "
                        f"    ultima_vez = ?, estado = 'Localizado' "
                        f"WHERE beacon_id = ?",
                        (area_id, rssi, ahora, beacon_id)
                    )
                else:
                    # ── 2d. Área distinta con señal débil: NO mover,
                    #        pero SÍ refrescar ultima_vez para no marcar
                    #        como 'Sin señal' un beacon que sigue activo ──
                    cursor.execute(
                        f"UPDATE {cls.T_POS} "
                        f"SET ultima_vez = ?, estado = 'Localizado' "
                        f"WHERE beacon_id = ?",
                        (ahora, beacon_id)
                    )

            db.commit()
            return True

        except Exception as e:
            current_app.logger.error(
                f"[ModelBLE.upsert_posicion_actual] "
                f"beacon_id={beacon_id} area_id={area_id} rssi={rssi} | {e}"
            )
            db.rollback()
            return False

        finally:
            if cursor:
                cursor.close()

    @classmethod
    def marcar_sin_senal(cls, db) -> int:
        """
        Marca como 'Sin senal' los beacons sin reporte
        en los ultimos TIMEOUT_SIN_SENAL minutos.
        Retorna el numero de filas afectadas (util para el log de la ruta).
        """
        cursor = None
        try:
            minutos_timeout = cls.get_regla_activa_por_tipo(db, 'sin_senal') or cls.TIMEOUT_SIN_SENAL
            limite = datetime.utcnow() - timedelta(minutes=minutos_timeout)
            cursor = db.cursor()
            cursor.execute(
                f"UPDATE {cls.T_POS} "
                f"SET estado = 'Sin senal' "
                f"WHERE ultima_vez < ? AND estado = 'Localizado'",
                (limite,)
            )
            afectados = cursor.rowcount
            db.commit()
            return afectados

        except Exception as e:
            current_app.logger.error(f"[ModelBLE.marcar_sin_senal] {e}")
            db.rollback()
            return 0

        finally:
            if cursor:
                cursor.close()

    @classmethod
    def get_posicion_actual_todos(cls, db) -> list[dict]:
        """
        Posicion actual de todos los equipos activos.
        JOIN directo a InventarioEquipos via beacon_id (columna real).
        Usado por el polling del panel cada 10 segundos.
        """
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT "
                f"  b.id           AS beacon_id, "
                f"  b.mac, "
                f"  b.nombre       AS beacon_nombre, "
                f"  e.id           AS equipo_id, "
                f"  e.equipo_unidad, "
                f"  e.numero_inventario, "
                f"  e.departamento, "
                f"  a.nombre       AS area_nombre, "
                f"  a.piso, "
                f"  p.rssi_max, "
                f"  p.ultima_vez, "
                f"  p.estado "
                f"FROM {cls.T_POS} p "
                f"JOIN {cls.T_BEACONS} b ON b.id = p.beacon_id "
                f"JOIN {cls.T_AREAS}   a ON a.id = p.area_id "
                f"LEFT JOIN {cls.T_INV} e ON e.beacon_id = b.id "
                f"WHERE b.activo = 1 "
                f"ORDER BY p.estado, a.piso, a.nombre"
            )
            rows = cursor.fetchall()
            return [
                {
                    "beacon_id":           r[0],
                    "mac":                 r[1],
                    "beacon_nombre":       r[2] or "",
                    "equipo_id":           r[3],
                    "equipo_nombre":       r[4] or "Sin asignar",
                    "numero_inventario":   r[5] or "",
                    "departamento":        r[6] or "",
                    "area_nombre":         r[7],
                    "piso":                r[8],
                    "rssi_max":            r[9],
                    "ultima_vez":          r[10].isoformat() if r[10] else None,
                    "estado":              r[11],
                }
                for r in rows
            ]

        except Exception as e:
            current_app.logger.error(f"[ModelBLE.get_posicion_actual_todos] {e}")
            return []

        finally:
            if cursor:
                cursor.close()

    @classmethod
    def get_posicion_actual_por_area(cls, db, area_id: int) -> list[dict]:
        """Equipos presentes en un area especifica en este momento."""
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT "
                f"  b.mac, "
                f"  b.nombre       AS beacon_nombre, "
                f"  e.id           AS equipo_id, "
                f"  e.equipo_unidad, "
                f"  e.numero_inventario, "
                f"  p.rssi_max, "
                f"  p.ultima_vez, "
                f"  p.estado "
                f"FROM {cls.T_POS} p "
                f"JOIN {cls.T_BEACONS} b ON b.id = p.beacon_id "
                f"LEFT JOIN {cls.T_INV} e ON e.beacon_id = b.id "
                f"WHERE p.area_id = ? AND b.activo = 1 "
                f"ORDER BY p.rssi_max DESC",
                (area_id,)
            )
            rows = cursor.fetchall()
            return [
                {
                    "mac":               r[0],
                    "beacon_nombre":     r[1] or "",
                    "equipo_id":         r[2],
                    "equipo_nombre":     r[3] or "Sin asignar",
                    "numero_inventario": r[4] or "",
                    "rssi_max":          r[5],
                    "ultima_vez":        r[6].isoformat() if r[6] else None,
                    "estado":            r[7],
                }
                for r in rows
            ]

        except Exception as e:
            current_app.logger.error(
                f"[ModelBLE.get_posicion_actual_por_area] area_id={area_id} | {e}"
            )
            return []

        finally:
            if cursor:
                cursor.close()

    @classmethod
    def get_alertas_activas(cls, db) -> list[dict]:
        """
        Beacons en estado 'Sin senal'.
        Clasifica adicionalmente los que llevan mas de TIMEOUT_BATERIA
        minutos sin reporte como posible bateria descargada.
        """
        cursor = None
        try:
# DESPUÉS
            minutos_bateria = cls.get_regla_activa_por_tipo(db, 'bateria') or cls.TIMEOUT_BATERIA
            limite_bateria  = datetime.utcnow() - timedelta(minutes=minutos_bateria)

            cursor = db.cursor()
            cursor.execute(
                f"SELECT "
                f"  b.mac, "
                f"  b.nombre       AS beacon_nombre, "
                f"  e.equipo_unidad, "
                f"  e.numero_inventario, "
                f"  a.nombre       AS area_nombre, "
                f"  a.piso, "
                f"  p.ultima_vez, "
                f"  p.estado, "
                f"  CASE "
                f"    WHEN p.ultima_vez < ? THEN 'Bateria posiblemente descargada' "
                f"    ELSE 'Sin senal' "
                f"  END AS tipo_alerta "
                f"FROM {cls.T_POS} p "
                f"JOIN {cls.T_BEACONS} b ON b.id = p.beacon_id "
                f"JOIN {cls.T_AREAS}   a ON a.id = p.area_id "
                f"LEFT JOIN {cls.T_INV} e ON e.beacon_id = b.id "
                f"WHERE p.estado = 'Sin senal' AND b.activo = 1 "
                f"ORDER BY p.ultima_vez ASC",
                (limite_bateria,)
            )
            rows = cursor.fetchall()
            return [
                {
                    "mac":               r[0],
                    "beacon_nombre":     r[1] or "",
                    "equipo_nombre":     r[2] or "Sin asignar",
                    "numero_inventario": r[3] or "",
                    "area_nombre":       r[4],
                    "piso":              r[5],
                    "ultima_vez":        r[6].isoformat() if r[6] else None,
                    "estado":            r[7],
                    "tipo_alerta":       r[8],
                }
                for r in rows
            ]

        except Exception as e:
            current_app.logger.error(f"[ModelBLE.get_alertas_activas] {e}")
            return []

        finally:
            if cursor:
                cursor.close()

    @classmethod
    def get_resumen_dashboard(cls, db) -> dict:
        """
        Contadores para las tres tarjetas del dashboard principal.
        Siempre retorna un dict con valores en 0 si hay error
        para que el template nunca reciba None.
        """
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT "
                f"  SUM(CASE WHEN p.estado = 'Localizado'       THEN 1 ELSE 0 END), "
                f"  SUM(CASE WHEN p.estado = 'Sin senal'        THEN 1 ELSE 0 END), "
                f"  SUM(CASE WHEN p.estado = 'En mantenimiento' THEN 1 ELSE 0 END) "
                f"FROM {cls.T_POS} p "
                f"JOIN {cls.T_BEACONS} b ON b.id = p.beacon_id "
                f"WHERE b.activo = 1"
            )
            row = cursor.fetchone()
            return {
                "localizados":   row[0] or 0,
                "sin_senal":     row[1] or 0,
                "mantenimiento": row[2] or 0,
                "total_alertas": row[1] or 0,
            }

        except Exception as e:
            current_app.logger.error(f"[ModelBLE.get_resumen_dashboard] {e}")
            return {
                "localizados": 0, "sin_senal": 0,
                "mantenimiento": 0, "total_alertas": 0,
            }

        finally:
            if cursor:
                cursor.close()

    # ── ADMIN: ÁREAS ─────────────────────────────────────────────────────────────

    @classmethod
    def registrar_area(cls, db, nombre, piso, esp32_id):
        """Crea un área nueva. Retorna el id generado o None si falla."""
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute("""
                INSERT INTO ble_areas (nombre, piso, esp32_id, activa)
                OUTPUT INSERTED.id
                VALUES (?, ?, ?, 1)
            """, (nombre, int(piso), esp32_id))
            row = cursor.fetchone()
            db.commit()
            return row[0] if row else None
        except Exception as e:
            db.rollback()
            raise e
        finally:
            if cursor: cursor.close()

    @classmethod
    def actualizar_area(cls, db, area_id, nombre, piso, esp32_id):
        """Edita nombre, piso y esp32_id de un área. Retorna True si se modificó algo."""
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute("""
                UPDATE ble_areas
                SET nombre   = ?,
                    piso     = ?,
                    esp32_id = ?
                WHERE id = ?
            """, (nombre, int(piso), esp32_id, area_id))
            db.commit()
            return cursor.rowcount > 0
        except Exception as e:
            db.rollback()
            raise e
        finally:
            if cursor: cursor.close()

    @classmethod
    def desactivar_area(cls, db, area_id):
        """Soft-delete: pone activa=0. Retorna True si se modificó algo."""
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute("""
                UPDATE ble_areas SET activa = 0 WHERE id = ?
            """, (area_id,))
            db.commit()
            return cursor.rowcount > 0
        except Exception as e:
            db.rollback()
            raise e
        finally:
            if cursor: cursor.close()

    @classmethod
    def activar_area(cls, db, area_id):
        """Reactiva un área previamente desactivada."""
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute("""
                UPDATE ble_areas SET activa = 1 WHERE id = ?
            """, (area_id,))
            db.commit()
            return cursor.rowcount > 0
        except Exception as e:
            db.rollback()
            raise e
        finally:
            if cursor: cursor.close()

    @classmethod
    def get_area_por_id(cls, db, area_id):
        """Retorna un dict con los datos del área o None si no existe."""
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute("""
                SELECT id, nombre, piso, esp32_id, activa
                FROM ble_areas
                WHERE id = ?
            """, (area_id,))
            row = cursor.fetchone()
            if not row: return None
            cols = [c[0] for c in cursor.description]
            return dict(zip(cols, row))
        except Exception as e:
            raise e
        finally:
            if cursor: cursor.close()

    @classmethod
    def esp32_id_existe(cls, db, esp32_id, excluir_id=None):
        """Valida unicidad de esp32_id. excluir_id evita falso positivo al editar."""
        cursor = None
        try:
            cursor = db.cursor()
            if excluir_id:
                cursor.execute("""
                    SELECT COUNT(1) FROM ble_areas
                    WHERE esp32_id = ? AND id != ?
                """, (esp32_id, excluir_id))
            else:
                cursor.execute("""
                    SELECT COUNT(1) FROM ble_areas WHERE esp32_id = ?
                """, (esp32_id,))
            return cursor.fetchone()[0] > 0
        finally:
            if cursor: cursor.close()

    # ── ADMIN: BEACONS ────────────────────────────────────────────────────────────

    @classmethod
    def registrar_beacon(cls, db, mac, nombre=None):
        """Registra un beacon nuevo por MAC. Retorna id o None si falla."""
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute("""
                INSERT INTO ble_beacons (mac, nombre, activo)
                OUTPUT INSERTED.id
                VALUES (?, ?, 1)
            """, (mac.upper(), nombre))
            row = cursor.fetchone()
            db.commit()
            return row[0] if row else None
        except Exception as e:
            db.rollback()
            raise e
        finally:
            if cursor: cursor.close()

    @classmethod
    def actualizar_beacon(cls, db, beacon_id, nombre):
        """Edita la etiqueta amigable del beacon."""
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute("""
                UPDATE ble_beacons SET nombre = ? WHERE id = ?
            """, (nombre, beacon_id))
            db.commit()
            return cursor.rowcount > 0
        except Exception as e:
            db.rollback()
            raise e
        finally:
            if cursor: cursor.close()

    @classmethod
    def desactivar_beacon(cls, db, beacon_id):
        """Soft-delete: pone activo=0 y limpia asignaciones."""
        cursor = None
        try:
            cursor = db.cursor()
            # Limpiar FK en InventarioEquipos
            cursor.execute("""
                UPDATE InventarioEquipos
                SET beacon_id = NULL
                WHERE beacon_id = ?
            """, (beacon_id,))
            # Desactivar beacon
            cursor.execute("""
                UPDATE ble_beacons SET activo = 0, equipo_id = NULL
                WHERE id = ?
            """, (beacon_id,))
            db.commit()
            return cursor.rowcount > 0
        except Exception as e:
            db.rollback()
            raise e
        finally:
            if cursor: cursor.close()

    @classmethod
    def asignar_beacon_equipo(cls, db, beacon_id, equipo_id):
        """
        Vincula beacon ↔ equipo (relación bidireccional).
        Si equipo_id es None, desvincula ambos lados.
        """
        cursor = None
        try:
            cursor = db.cursor()
            if equipo_id:
                # Limpiar asignación previa del equipo destino (si tenía otro beacon)
                cursor.execute("""
                    UPDATE ble_beacons SET equipo_id = NULL
                    WHERE equipo_id = ? AND id != ?
                """, (equipo_id, beacon_id))
                cursor.execute("""
                    UPDATE InventarioEquipos SET beacon_id = NULL
                    WHERE beacon_id = ? AND id != ?
                """, (beacon_id, equipo_id))
                # Asignar en ambas tablas
                cursor.execute("""
                    UPDATE ble_beacons SET equipo_id = ? WHERE id = ?
                """, (equipo_id, beacon_id))
                cursor.execute("""
                    UPDATE InventarioEquipos SET beacon_id = ? WHERE id = ?
                """, (beacon_id, equipo_id))
            else:
                # Desasignar
                cursor.execute("""
                    SELECT equipo_id FROM ble_beacons WHERE id = ?
                """, (beacon_id,))
                row = cursor.fetchone()
                if row and row[0]:
                    cursor.execute("""
                        UPDATE InventarioEquipos SET beacon_id = NULL WHERE id = ?
                    """, (row[0],))
                cursor.execute("""
                    UPDATE ble_beacons SET equipo_id = NULL WHERE id = ?
                """, (beacon_id,))
            db.commit()
            return True
        except Exception as e:
            db.rollback()
            raise e
        finally:
            if cursor: cursor.close()
    @classmethod
    def toggle_beacon(cls, db, beacon_id):
        """
        Togglea activo/inactivo.
        Al desactivar: limpia asignaciones.
        Al activar: solo cambia la bandera, conserva vínculos.
        Retorna el nuevo valor de activo (0 o 1), o None si no existe.
        """
        cursor = None
        try:
            cursor = db.cursor()

            # Leer estado actual
            cursor.execute(
                "SELECT activo FROM ble_beacons WHERE id = ?", (beacon_id,)
            )
            row = cursor.fetchone()
            if row is None:
                return None

            activo_actual = row[0]
            nuevo_activo  = 0 if activo_actual else 1

            if nuevo_activo == 0:
                # Desactivar: limpiar asignaciones en ambas tablas
                cursor.execute("""
                    UPDATE InventarioEquipos
                    SET beacon_id = NULL
                    WHERE beacon_id = ?
                """, (beacon_id,))
                cursor.execute("""
                    UPDATE ble_beacons
                    SET activo = 0, equipo_id = NULL
                    WHERE id = ?
                """, (beacon_id,))
            else:
                # Reactivar: solo encender, conservar equipo_id intacto
                cursor.execute("""
                    UPDATE ble_beacons
                    SET activo = 1
                    WHERE id = ?
                """, (beacon_id,))

            db.commit()
            return nuevo_activo

        except Exception as e:
            db.rollback()
            raise e
        finally:
            if cursor: cursor.close()

    @classmethod
    def mac_existe(cls, db, mac, excluir_id=None):
        """Valida unicidad de MAC. excluir_id para edición."""
        cursor = None
        try:
            cursor = db.cursor()
            if excluir_id:
                cursor.execute("""
                    SELECT COUNT(1) FROM ble_beacons
                    WHERE mac = ? AND id != ?
                """, (mac.upper(), excluir_id))
            else:
                cursor.execute("""
                    SELECT COUNT(1) FROM ble_beacons WHERE mac = ?
                """, (mac.upper(),))
            return cursor.fetchone()[0] > 0
        finally:
            if cursor: cursor.close()

    @classmethod
    def get_beacon_por_id(cls, db, beacon_id):
        """Retorna dict del beacon con datos del equipo asignado o None."""
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute("""
                SELECT b.id, b.mac, b.nombre, b.equipo_id, b.bateria_pct, b.activo,
                    e.equipo_unidad AS equipo_nombre,
                    e.numero_inventario
                FROM ble_beacons b
                LEFT JOIN InventarioEquipos e ON e.id = b.equipo_id
                WHERE b.id = ?
            """, (beacon_id,))
            row = cursor.fetchone()
            if not row: return None
            cols = [c[0] for c in cursor.description]
            return dict(zip(cols, row))
        finally:
            if cursor: cursor.close()
            # ══════════════════════════════════════════════════════════════
    #  REGLAS DE ALERTA
    # ══════════════════════════════════════════════════════════════
    @classmethod
    def get_todas_las_reglas(cls, db) -> list[dict]:
        """Lista completa de reglas (activas e inactivas) para el panel admin."""
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT id, nombre, tipo, umbral_valor, activa, creado_en "
                f"FROM {cls.T_REGLAS} "
                f"ORDER BY tipo, id"
            )
            rows = cursor.fetchall()
            return [
                {
                    "id":           r[0],
                    "nombre":       r[1],
                    "tipo":         r[2],
                    "umbral_valor": r[3],
                    "activa":       bool(r[4]),
                    "creado_en":    r[5].isoformat() if r[5] else None,
                }
                for r in rows
            ]
        except Exception as e:
            current_app.logger.error(f"[ModelBLE.get_todas_las_reglas] {e}")
            return []
        finally:
            if cursor: cursor.close()

    @classmethod
    def get_regla_activa_por_tipo(cls, db, tipo: str) -> int | None:
        """
        Retorna el umbral_valor de la primera regla activa de ese tipo.
        Usado por marcar_sin_senal() y get_alertas_activas() en lugar
        de las constantes hardcodeadas.
        Retorna None si no hay regla activa para ese tipo.
        """
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT TOP 1 umbral_valor "
                f"FROM {cls.T_REGLAS} "
                f"WHERE tipo = ? AND activa = 1 "
                f"ORDER BY id",
                (tipo,)
            )
            row = cursor.fetchone()
            return row[0] if row else None
        except Exception as e:
            current_app.logger.error(
                f"[ModelBLE.get_regla_activa_por_tipo] tipo={tipo} | {e}"
            )
            return None
        finally:
            if cursor: cursor.close()

    @classmethod
    def crear_regla(cls, db, nombre: str, tipo: str,
                    umbral_valor: int) -> int | None:
        """Crea una regla nueva. Retorna el id generado o None si falla."""
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"INSERT INTO {cls.T_REGLAS} (nombre, tipo, umbral_valor) "
                f"OUTPUT INSERTED.id "
                f"VALUES (?, ?, ?)",
                (nombre, tipo, umbral_valor)
            )
            new_id = cursor.fetchone()[0]
            db.commit()
            return new_id
        except Exception as e:
            current_app.logger.error(f"[ModelBLE.crear_regla] {e}")
            db.rollback()
            return None
        finally:
            if cursor: cursor.close()

    @classmethod
    def actualizar_regla(cls, db, regla_id: int, nombre: str,
                        umbral_valor: int) -> bool:
        """
        Edita nombre y umbral de una regla existente.
        El tipo NO se puede cambiar (define qué controla la regla).
        """
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"UPDATE {cls.T_REGLAS} "
                f"SET nombre = ?, umbral_valor = ? "
                f"WHERE id = ?",
                (nombre, umbral_valor, regla_id)
            )
            db.commit()
            return cursor.rowcount > 0
        except Exception as e:
            current_app.logger.error(
                f"[ModelBLE.actualizar_regla] id={regla_id} | {e}"
            )
            db.rollback()
            return False
        finally:
            if cursor: cursor.close()

    @classmethod
    def toggle_regla(cls, db, regla_id: int) -> bool | None:
        """
        Activa o desactiva una regla.
        Retorna el nuevo estado (True=activa, False=inactiva)
        o None si la regla no existe.
        """
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT activa FROM {cls.T_REGLAS} WHERE id = ?",
                (regla_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            nuevo = 0 if row[0] else 1
            cursor.execute(
                f"UPDATE {cls.T_REGLAS} SET activa = ? WHERE id = ?",
                (nuevo, regla_id)
            )
            db.commit()
            return bool(nuevo)
        except Exception as e:
            current_app.logger.error(
                f"[ModelBLE.toggle_regla] id={regla_id} | {e}"
            )
            db.rollback()
            return None
        finally:
            if cursor: cursor.close()

    @classmethod
    def eliminar_regla(cls, db, regla_id: int) -> bool:
        """
        Elimina una regla permanentemente.
        Solo se permite si NO es una de las 3 reglas base (id <= 3).
        """
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"DELETE FROM {cls.T_REGLAS} WHERE id = ? AND id > 3",
                (regla_id,)
            )
            db.commit()
            return cursor.rowcount > 0
        except Exception as e:
            current_app.logger.error(
                f"[ModelBLE.eliminar_regla] id={regla_id} | {e}"
            )
            db.rollback()
            return False
        finally:
            if cursor: cursor.close()

    @classmethod
    def purgar_lecturas_antiguas(cls, db, dias: int = 30) -> int:
        """
        Elimina registros de ble_lecturas con más de `dias` días de antigüedad.
        Retorna el número de filas eliminadas (útil para el log del scheduler).
        Se ejecuta vía APScheduler — nunca desde una ruta HTTP.
        """
        cursor = None
        try:
            limite = datetime.utcnow() - timedelta(days=dias)
            cursor = db.cursor()
            cursor.execute(
                f"DELETE FROM {cls.T_LECTURAS} "
                f"WHERE timestamp < ?",
                (limite,)
            )
            eliminados = cursor.rowcount
            db.commit()
            return eliminados

        except Exception as e:
            current_app.logger.error(
                f"[ModelBLE.purgar_lecturas_antiguas] dias={dias} | {e}"
            )
            db.rollback()
            return 0

        finally:
            if cursor:
                cursor.close()