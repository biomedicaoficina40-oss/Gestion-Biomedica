# routes/ble_routes.py
# Sistema de Localizacion BLE — Hospital Galenia
# Sigue exactamente el patron de admin_routes.py:
#   - db = None antes del try
#   - try / except / finally: if db: db.close()
#   - current_app.logger para errores internos
#   - flash() para mensajes al usuario
#   - Nunca expone detalles tecnicos al cliente en produccion

from flask import (
    Blueprint, request, jsonify,
    render_template, redirect, url_for, flash, current_app
)
from database.db import get_connection
from models.ModelBLE import ModelBLE
from models.entities.decorators import (
    requiere_rol,
    ROL_USUARIO, ROL_BIOMEDICO, ROL_ADMIN,
)


ble_bp = Blueprint('ble', __name__)


# ══════════════════════════════════════════════════════════════
#  PINES DEL VISOR 3D
#  Indexados por NOMBRE de area de ble_areas, no por id: los ids no son
#  portables entre la base de pruebas y la de produccion, los nombres si.
#
#  Las coordenadas son dato de autoria del modelo pruebaweb.glb, no dato de
#  negocio: se capturan con el boton "Modo colocar pin" del propio visor y se
#  pegan aqui. Un area de ble_areas que no aparezca en este diccionario
#  simplemente no se dibuja (el visor la reporta como "sin pin colocado").
#
#  'perimetro' es opcional y solo sirve para encuadrar la camara al cargar.
# ══════════════════════════════════════════════════════════════

AREAS_3D = {
    'UCIN': {
        'descripcion': 'Unidad de Cuidados Intensivos Neonatales',
        'x': -1.47, 'y': 2.95, 'z': -0.11,
        'perimetro': [
            {'x':  -9.76, 'y': 0.00, 'z': -7.00},
            {'x':  -9.98, 'y': 0.00, 'z': -3.00},
            {'x': -10.00, 'y': 0.00, 'z':  2.00},
            {'x': -10.00, 'y': 0.00, 'z':  6.00},
            {'x':   8.00, 'y': 0.00, 'z': -6.52},
            {'x':   8.41, 'y': 0.00, 'z': -2.00},
            {'x':   8.00, 'y': 0.00, 'z':  3.98},
            {'x':   7.00, 'y': 0.00, 'z': -6.83},
            {'x':   2.00, 'y': 0.00, 'z': -7.11},
            {'x':  -2.00, 'y': 0.00, 'z': -6.82},
            {'x':  -5.00, 'y': 0.00, 'z': -6.54},
            {'x':  -8.29, 'y': 0.00, 'z': -7.00},
            {'x':  -7.85, 'y': 0.00, 'z':  7.00},
            {'x':  -4.17, 'y': 0.00, 'z':  6.00},
            {'x':   2.73, 'y': 0.00, 'z':  7.00},
            {'x':   7.13, 'y': 0.00, 'z':  7.00},
        ],
    },
}


# ══════════════════════════════════════════════════════════════
#  API — ESP32 → SERVIDOR
#  Estas rutas NO llevan control de rol (los ESP32 no tienen sesion).
#  La seguridad la provee el header X-BLE-Token.
# ══════════════════════════════════════════════════════════════

@ble_bp.route('/api/ble/ping', methods=['GET'])
def ping():
    """
    El ESP32 llama a este endpoint antes de enviar lecturas
    para confirmar conectividad y token valido.
    No necesita conexion a BD.
    """
    token = request.headers.get("X-BLE-Token", "")
    if not ModelBLE.validar_token(token):
        current_app.logger.warning(
            f"[BLE/ping] Token invalido desde IP {request.remote_addr}"
        )
        return jsonify({"status": "error", "mensaje": "Token invalido"}), 401

    return jsonify({"status": "ok", "mensaje": "Servidor BLE activo"}), 200


@ble_bp.route('/api/ble/lecturas', methods=['POST'])

def recibir_lecturas():
    """
    Endpoint principal del sistema BLE.
    Recibe el JSON del ESP32, valida, persiste y actualiza posicion.

    JSON esperado:
    {
        "esp32_id": "esp32-piso1-urgencias",
        "beacons": [
            {"mac": "AA:BB:CC:DD:EE:01", "rssi": -62},
            ...
        ]
    }

    Flujo de validacion (falla rapido en cada paso):
    1. Token de autenticacion
    2. Estructura del JSON
    3. esp32_id registrado en ble_areas
    4. Por cada beacon: MAC registrada + RSSI sobre el minimo
    """
    # ── 1. Token ──────────────────────────────────────────────
    token = request.headers.get("X-BLE-Token", "")
    if not ModelBLE.validar_token(token):
        current_app.logger.warning(
            f"[BLE/lecturas] Token invalido desde IP {request.remote_addr}"
        )
        return jsonify({"status": "error", "mensaje": "Token invalido"}), 401

    # ── 2. Parsear JSON ───────────────────────────────────────
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "mensaje": "JSON invalido o vacio"}), 400

    esp32_id = (data.get("esp32_id") or "").strip()
    beacons  = data.get("beacons") or []

    if not esp32_id:
        return jsonify({"status": "error", "mensaje": "esp32_id requerido"}), 400

    if not isinstance(beacons, list):
        return jsonify({"status": "error", "mensaje": "beacons debe ser lista"}), 400

    # ── 3. Conexion y validacion de ESP32 ─────────────────────
    db = None
    try:
        db = get_connection()

        area = ModelBLE.get_area_por_esp32(db, esp32_id)
        if not area:
            current_app.logger.warning(
                f"[BLE/lecturas] ESP32 no registrado: {esp32_id} "
                f"| IP {request.remote_addr}"
            )
            return jsonify({
                "status":  "error",
                "mensaje": f"ESP32 '{esp32_id}' no registrado o inactivo"
            }), 403

        area_id = area["id"]

        # ── 4. Procesar beacons ───────────────────────────────
        procesados        = 0
        ignorados_rssi    = 0
        macs_desconocidas = 0
        auto_registradas  = 0

        for b in beacons:
            mac  = (b.get("mac") or "").upper().strip()
            rssi = b.get("rssi")

            # Datos minimos presentes
            if not mac or rssi is None:
                ignorados_rssi += 1
                continue

            # Filtro RSSI — mismo umbral que el firmware
            if rssi < ModelBLE.RSSI_MIN:
                ignorados_rssi += 1
                continue

            # MAC debe estar registrada
            beacon = ModelBLE.get_beacon_por_mac(db, mac)
            if not beacon:
                nombre_auto = f"AUTO-{mac.replace(':', '')[-6:]}"  # ej: AUTO-EEFF01
                nuevo_id = ModelBLE.registrar_beacon_auto(db, mac, nombre_auto)
                if not nuevo_id:
                    macs_desconocidas += 1
                    continue
                current_app.logger.info(
                    f"[BLE/lecturas] MAC nueva auto-registrada: {mac} → id={nuevo_id}"
                )
                # Recargar para continuar el flujo normal
                beacon = ModelBLE.get_beacon_por_mac(db, mac)
                if not beacon:
                    macs_desconocidas += 1
                    continue
                auto_registradas += 1

            beacon_id = beacon["id"]

            # Guardar en historial
            ok_lectura = ModelBLE.insertar_lectura(db, beacon_id, area_id, rssi)
            if not ok_lectura:
                # El modelo ya logueo el error; continuamos con los demas
                continue

            # Actualizar posicion actual
            ok_pos = ModelBLE.upsert_posicion_actual(db, beacon_id, area_id, rssi)
            if not ok_pos:
                current_app.logger.warning(
                    f"[BLE/lecturas] Falló upsert_posicion_actual "
                    f"beacon_id={beacon_id} area_id={area_id} rssi={rssi}"
                )
                # No hacemos continue: la lectura histórica ya quedó guardada,
                # solo falló la actualización de posición actual.

            procesados += 1

        # ── 5. Marcar Sin senal ───────────────────────────────
        sin_senal = ModelBLE.marcar_sin_senal(db)

        if sin_senal > 0:
            current_app.logger.info(
                f"[BLE/lecturas] {sin_senal} beacon(s) marcados Sin senal"
            )

        return jsonify({
            "status":             "ok",
            "area":               area["nombre"],
            "procesados":         procesados,
            "ignorados_rssi":     ignorados_rssi,
            "macs_desconocidas":  macs_desconocidas,
            "auto_registradas":   auto_registradas,   # ← nuevo
            "marcados_sin_senal": sin_senal,
        }), 200

    except Exception as ex:
        current_app.logger.error(
            f"[BLE/lecturas] Error inesperado esp32_id={esp32_id} | {ex}"
        )
        return jsonify({"status": "error", "mensaje": "Error interno del servidor"}), 500

    finally:
        if db:
            db.close()


# ══════════════════════════════════════════════════════════════
#  API — PANEL WEB (AJAX / polling)
#  Estas rutas SI requieren sesion activa.
# ══════════════════════════════════════════════════════════════

@ble_bp.route('/api/ble/posicion-actual', methods=['GET'])
@requiere_rol(ROL_USUARIO)
def api_posicion_actual():
    """
    Todos los equipos con su ubicacion actual.
    Llamado por el panel cada 10 segundos via fetch().
    """
    db = None
    try:
        db = get_connection()
        datos = ModelBLE.get_posicion_actual_todos(db)
        return jsonify(datos), 200

    except Exception as ex:
        current_app.logger.error(f"[BLE/api_posicion_actual] {ex}")
        return jsonify({"error": "Error al obtener posicion"}), 500

    finally:
        if db:
            db.close()


@ble_bp.route('/api/ble/area/<int:area_id>/equipos', methods=['GET'])
@requiere_rol(ROL_USUARIO)
def api_equipos_por_area(area_id):
    """Equipos presentes en un area especifica ahora mismo."""
    db = None
    try:
        db = get_connection()
        datos = ModelBLE.get_posicion_actual_por_area(db, area_id)
        return jsonify(datos), 200

    except Exception as ex:
        current_app.logger.error(
            f"[BLE/api_equipos_por_area] area_id={area_id} | {ex}"
        )
        return jsonify({"error": "Error al obtener equipos del area"}), 500

    finally:
        if db:
            db.close()


@ble_bp.route('/api/ble/vista3d/datos', methods=['GET'])
@requiere_rol(ROL_USUARIO)
def api_vista3d_datos():
    """
    Equipos localizados ahora mismo, agrupados por area, para el visor 3D.

    Devuelve TODAS las areas con actividad, no solo las que tienen pin: el
    visor pinta las que encuentra en AREAS_3D y lista el resto como pendientes
    de colocar. Asi, agregar un area nueva es pegar sus coordenadas y ya.
    """
    db = None
    try:
        db = get_connection()
        areas = ModelBLE.get_areas_con_equipos(db)
        return jsonify({"ok": True, "areas": areas}), 200

    except Exception as ex:
        current_app.logger.error(f"[BLE/api_vista3d_datos] {ex}")
        return jsonify({"ok": False, "error": "Error al obtener datos del visor"}), 500

    finally:
        if db:
            db.close()


@ble_bp.route('/api/ble/equipo/<int:equipo_id>/historial', methods=['GET'])
@requiere_rol(ROL_USUARIO)
def api_historial_equipo(equipo_id):
    """
    Movimientos del equipo en las ultimas N horas.
    Parametro opcional: ?horas=24 (default 24, maximo 168 = 7 dias).
    """
    db = None
    try:
        horas = request.args.get("horas", 24, type=int)
        horas = min(max(horas, 1), 168)   # clamping: 1h minimo, 7 dias maximo

        db = get_connection()
        datos = ModelBLE.get_historial_equipo(db, equipo_id, horas)
        return jsonify(datos), 200

    except Exception as ex:
        current_app.logger.error(
            f"[BLE/api_historial_equipo] equipo_id={equipo_id} | {ex}"
        )
        return jsonify({"error": "Error al obtener historial"}), 500

    finally:
        if db:
            db.close()


@ble_bp.route('/api/ble/alertas', methods=['GET'])
@requiere_rol(ROL_USUARIO)
def api_alertas():
    """Alertas activas: beacons sin senal o con bateria posiblemente descargada."""
    db = None
    try:
        db = get_connection()
        datos = ModelBLE.get_alertas_activas(db)
        return jsonify(datos), 200

    except Exception as ex:
        current_app.logger.error(f"[BLE/api_alertas] {ex}")
        return jsonify({"error": "Error al obtener alertas"}), 500

    finally:
        if db:
            db.close()


@ble_bp.route('/api/ble/dashboard/resumen', methods=['GET'])
@requiere_rol(ROL_USUARIO)
def api_resumen_dashboard():
    """Contadores para las tarjetas del dashboard."""
    db = None
    try:
        db = get_connection()
        datos = ModelBLE.get_resumen_dashboard(db)
        return jsonify(datos), 200

    except Exception as ex:
        current_app.logger.error(f"[BLE/api_resumen_dashboard] {ex}")
        return jsonify({"error": "Error al obtener resumen"}), 500

    finally:
        if db:
            db.close()


@ble_bp.route('/api/ble/areas', methods=['GET'])
@requiere_rol(ROL_USUARIO)
def get_areas():
    """Lista todas las areas activas. Usada por area.html para poblar el selector."""
    db = None
    try:
        db = get_connection()                        # CORREGIDO: era get_db()
        areas = ModelBLE.get_todas_las_areas(db)
        return jsonify(areas), 200

    except Exception as ex:
        current_app.logger.error(f"[BLE/get_areas] {ex}")
        return jsonify([]), 500

    finally:
        if db:
            db.close()


# ══════════════════════════════════════════════════════════════
#  VISTAS HTML — Fase 2 completada
# ══════════════════════════════════════════════════════════════

@ble_bp.route('/localizacion')
@requiere_rol(ROL_USUARIO)
def dashboard():
    """Dashboard principal del modulo BLE."""
    db = None
    try:
        db = get_connection()
        resumen = ModelBLE.get_resumen_dashboard(db)
        alertas = ModelBLE.get_alertas_activas(db)
        return render_template(
            'ble/dashboard.html',
            resumen=resumen,
            alertas=alertas
        )

    except Exception as ex:
        current_app.logger.error(f"[BLE/dashboard] {ex}")
        flash("Error al cargar el panel de localizacion.", "error")
        return redirect(url_for('equipos.Catalogo'))

    finally:
        if db:
            db.close()


@ble_bp.route('/localizacion/buscar')
@requiere_rol(ROL_USUARIO)
def buscar():
    """
    Buscador de equipos por nombre, serie o numero de inventario.
    Los datos se cargan via /api/ble/posicion-actual (fetch del cliente).
    No necesita pasar datos desde el servidor.
    """
    return render_template('ble/buscar.html')


@ble_bp.route('/localizacion/area/<int:area_id>')
@requiere_rol(ROL_USUARIO)
def ver_area(area_id):
    """
    Vista de equipos presentes en un area especifica.
    Pasa area_id y la lista de areas al template para el selector.
    Los equipos se cargan via /api/ble/area/<id>/equipos (polling 10s).
    """
    db = None
    try:
        db = get_connection()
        areas = ModelBLE.get_todas_las_areas(db)    # para el selector de area
        return render_template(
            'ble/area.html',
            area_id=area_id,
            areas=areas
        )

    except Exception as ex:
        current_app.logger.error(f"[BLE/ver_area] area_id={area_id} | {ex}")
        flash("Error al cargar el area.", "error")
        return redirect(url_for('ble.dashboard'))

    finally:
        if db:
            db.close()


@ble_bp.route('/localizacion/equipo/<int:equipo_id>')
@requiere_rol(ROL_USUARIO)
def ver_equipo(equipo_id):
    """
    Detalle e historial de movimiento de un equipo.
    La posicion actual y el historial se cargan via API (polling + fetch).
    """
    return render_template('ble/equipo.html', equipo_id=equipo_id)


@ble_bp.route('/localizacion/alertas')
@requiere_rol(ROL_USUARIO)
def ver_alertas():
    """
    Lista de alertas activas del sistema BLE.
    Los datos se cargan via /api/ble/alertas (polling 15s).
    """
    return render_template('ble/alertas.html')


# ═══════════════════════════════════════════════════════════════════
#  CONFIGURACIÓN DE LOCALIZACIÓN — Biomédico o superior
#
#  Áreas, beacons y reglas de alerta son configuración operativa del
#  servicio de biomedicina, no administración del sistema. La única
#  excepción es la purga de lecturas, que sigue siendo del Administrador.
#
#  El control va en el decorador de cada ruta, no dentro del cuerpo, para
#  que la matriz completa de permisos se pueda auditar recorriendo url_map.
# ═══════════════════════════════════════════════════════════════════

# ── Vista principal admin (renderiza tabs Áreas + Beacons) ──────────

@ble_bp.route('/localizacion/admin')
@requiere_rol(ROL_BIOMEDICO)
def admin_panel():
    return render_template('ble/admin/admin.html')


# ── Formulario crear área ───────────────────────────────────────────

@ble_bp.route('/localizacion/admin/areas/nueva', methods=['GET'])
@requiere_rol(ROL_BIOMEDICO)
def admin_area_nueva():
    return render_template('ble/admin/area_form.html', area=None)


# ── Formulario editar área ──────────────────────────────────────────

@ble_bp.route('/localizacion/admin/areas/<int:area_id>/editar', methods=['GET'])
@requiere_rol(ROL_BIOMEDICO)
def admin_area_editar(area_id):
    db = None
    try:
        db = get_connection()
        area = ModelBLE.get_area_por_id(db, area_id)
        if not area:
            return render_template('ble/admin/admin.html'), 404
        return render_template('ble/admin/area_form.html', area=area)
    except Exception as e:
        current_app.logger.error(f'[BLE/admin_area_editar] {e}')
        return render_template('ble/admin/admin.html'), 500
    finally:
        if db: db.close()


# ── API: crear área ─────────────────────────────────────────────────

@ble_bp.route('/api/ble/admin/areas', methods=['POST'])
@requiere_rol(ROL_BIOMEDICO)
def api_area_crear():
    db = None
    try:
        data    = request.get_json(force=True) or {}
        nombre  = (data.get('nombre') or '').strip()
        piso    = data.get('piso')
        esp32_id = (data.get('esp32_id') or '').strip()

        if not nombre or not piso or not esp32_id:
            return jsonify({'error': 'nombre, piso y esp32_id son obligatorios'}), 400

        db = get_connection()

        if ModelBLE.esp32_id_existe(db, esp32_id):
            return jsonify({'error': f'El esp32_id "{esp32_id}" ya está registrado'}), 409

        nuevo_id = ModelBLE.registrar_area(db, nombre, piso, esp32_id)
        if not nuevo_id:
            return jsonify({'error': 'Error al crear el área'}), 500

        current_app.logger.info(f'[BLE/admin] Área creada id={nuevo_id} esp32_id={esp32_id}')
        return jsonify({'ok': True, 'id': nuevo_id}), 201

    except Exception as e:
        current_app.logger.error(f'[BLE/api_area_crear] {e}')
        return jsonify({'error': 'Error interno'}), 500
    finally:
        if db: db.close()


# ── API: editar área ────────────────────────────────────────────────

@ble_bp.route('/api/ble/admin/areas/<int:area_id>', methods=['PUT'])
@requiere_rol(ROL_BIOMEDICO)
def api_area_editar(area_id):
    db = None
    try:
        data     = request.get_json(force=True) or {}
        nombre   = (data.get('nombre') or '').strip()
        piso     = data.get('piso')
        esp32_id = (data.get('esp32_id') or '').strip()

        if not nombre or not piso or not esp32_id:
            return jsonify({'error': 'nombre, piso y esp32_id son obligatorios'}), 400

        db = get_connection()

        if ModelBLE.esp32_id_existe(db, esp32_id, excluir_id=area_id):
            return jsonify({'error': f'El esp32_id "{esp32_id}" ya está en uso'}), 409

        ok = ModelBLE.actualizar_area(db, area_id, nombre, piso, esp32_id)
        if not ok:
            return jsonify({'error': 'Área no encontrada'}), 404

        current_app.logger.info(f'[BLE/admin] Área actualizada id={area_id}')
        return jsonify({'ok': True})

    except Exception as e:
        current_app.logger.error(f'[BLE/api_area_editar] {e}')
        return jsonify({'error': 'Error interno'}), 500
    finally:
        if db: db.close()


# ── API: desactivar / activar área (toggle) ─────────────────────────

@ble_bp.route('/api/ble/admin/areas/<int:area_id>', methods=['DELETE'])
@requiere_rol(ROL_BIOMEDICO)
def api_area_desactivar(area_id):
    db = None
    try:
        db    = get_connection()
        area  = ModelBLE.get_area_por_id(db, area_id)
        if not area:
            return jsonify({'error': 'Área no encontrada'}), 404

        if area['activa']:
            ModelBLE.desactivar_area(db, area_id)
            nuevo_estado = 0
        else:
            ModelBLE.activar_area(db, area_id)
            nuevo_estado = 1

        current_app.logger.info(f'[BLE/admin] Área id={area_id} activa → {nuevo_estado}')
        return jsonify({'ok': True, 'activa': nuevo_estado})

    except Exception as e:
        current_app.logger.error(f'[BLE/api_area_desactivar] {e}')
        return jsonify({'error': 'Error interno'}), 500
    finally:
        if db: db.close()


# ── API: crear beacon ───────────────────────────────────────────────

@ble_bp.route('/api/ble/admin/beacons', methods=['POST'])
@requiere_rol(ROL_BIOMEDICO)
def api_beacon_crear():
    db = None
    try:
        data   = request.get_json(force=True) or {}
        mac    = (data.get('mac') or '').strip()
        nombre = (data.get('nombre') or '').strip() or None

        if not mac:
            return jsonify({'error': 'mac es obligatorio'}), 400

        # Validar formato MAC básico
        import re
        if not re.match(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$', mac):
            return jsonify({'error': 'Formato de MAC inválido (AA:BB:CC:DD:EE:FF)'}), 400

        db = get_connection()

        if ModelBLE.mac_existe(db, mac):
            return jsonify({'error': f'La MAC {mac.upper()} ya está registrada'}), 409

        nuevo_id = ModelBLE.registrar_beacon(db, mac, nombre)
        if not nuevo_id:
            return jsonify({'error': 'Error al registrar beacon'}), 500

        current_app.logger.info(f'[BLE/admin] Beacon creado id={nuevo_id} mac={mac.upper()}')
        return jsonify({'ok': True, 'id': nuevo_id}), 201

    except Exception as e:
        current_app.logger.error(f'[BLE/api_beacon_crear] {e}')
        return jsonify({'error': 'Error interno'}), 500
    finally:
        if db: db.close()


# ── API: editar nombre de beacon ────────────────────────────────────

@ble_bp.route('/api/ble/admin/beacons/<int:beacon_id>', methods=['PUT'])
@requiere_rol(ROL_BIOMEDICO)
def api_beacon_editar(beacon_id):
    db = None
    try:
        data   = request.get_json(force=True) or {}
        nombre = (data.get('nombre') or '').strip() or None

        db = get_connection()
        ok = ModelBLE.actualizar_beacon(db, beacon_id, nombre)
        if not ok:
            return jsonify({'error': 'Beacon no encontrado'}), 404

        return jsonify({'ok': True})

    except Exception as e:
        current_app.logger.error(f'[BLE/api_beacon_editar] {e}')
        return jsonify({'error': 'Error interno'}), 500
    finally:
        if db: db.close()


# ── API: asignar / desasignar beacon ↔ equipo ───────────────────────

@ble_bp.route('/api/ble/admin/beacons/<int:beacon_id>/asignar', methods=['PUT'])
@requiere_rol(ROL_BIOMEDICO)
def api_beacon_asignar(beacon_id):
    db = None
    try:
        data      = request.get_json(force=True) or {}
        equipo_id = data.get('equipo_id')  # None = desasignar

        db = get_connection()
        ok = ModelBLE.asignar_beacon_equipo(db, beacon_id, equipo_id)
        if not ok:
            return jsonify({'error': 'Error al asignar'}), 500

        accion = f'asignado a equipo {equipo_id}' if equipo_id else 'desasignado'
        current_app.logger.info(f'[BLE/admin] Beacon id={beacon_id} {accion}')
        return jsonify({'ok': True})

    except Exception as e:
        current_app.logger.error(f'[BLE/api_beacon_asignar] {e}')
        return jsonify({'error': 'Error interno'}), 500
    finally:
        if db: db.close()


# ── API: desactivar beacon ──────────────────────────────────────────

@ble_bp.route('/api/ble/admin/beacons/<int:beacon_id>', methods=['DELETE'])
@requiere_rol(ROL_BIOMEDICO)
def api_beacon_desactivar(beacon_id):
    db = None
    try:
        db = get_connection()
        nuevo_activo = ModelBLE.toggle_beacon(db, beacon_id)  # ← cambio aquí

        if nuevo_activo is None:
            return jsonify({'error': 'Beacon no encontrado'}), 404

        accion = 'activado' if nuevo_activo else 'desactivado'
        current_app.logger.info(f'[BLE/admin] Beacon id={beacon_id} {accion}')
        return jsonify({'ok': True, 'activo': nuevo_activo})  # ← devolver estado real

    except Exception as e:
        current_app.logger.error(f'[BLE/api_beacon_desactivar] {e}')
        return jsonify({'error': 'Error interno'}), 500
    finally:
        if db: db.close()

# ── API: todas las áreas para panel admin (activas + inactivas) ─────

@ble_bp.route('/api/ble/admin/areas', methods=['GET'])
@requiere_rol(ROL_BIOMEDICO)
def api_admin_areas_lista():
    db = None
    try:
        db = get_connection()
        cursor = db.cursor()
        cursor.execute("""
            SELECT a.id, a.nombre, a.piso, a.esp32_id, a.activa,
                   COUNT(p.beacon_id) AS equipos_ahora
              FROM ble_areas a
              LEFT JOIN ble_posicion_actual p ON p.area_id = a.id
             GROUP BY a.id, a.nombre, a.piso, a.esp32_id, a.activa
             ORDER BY a.piso, a.nombre
        """)
        cols = [c[0] for c in cursor.description]
        areas = [dict(zip(cols, row)) for row in cursor.fetchall()]
        cursor.close()
        return jsonify(areas)
    except Exception as e:
        current_app.logger.error(f'[BLE/api_admin_areas_lista] {e}')
        return jsonify([]), 500
    finally:
        if db: db.close()

# ── API: todos los beacons para panel admin (activos + inactivos) ───

@ble_bp.route('/api/ble/admin/beacons', methods=['GET'])
@requiere_rol(ROL_BIOMEDICO)
def api_admin_beacons_lista():
    db = None
    try:
        db = get_connection()
        cursor = db.cursor()
        cursor.execute("""
            SELECT b.id, b.mac, b.nombre, b.bateria_pct, b.activo,
                   b.equipo_id,
                   e.equipo_unidad  AS equipo_nombre,
                   e.numero_inventario
              FROM ble_beacons b
              LEFT JOIN InventarioEquipos e ON e.id = b.equipo_id
             ORDER BY b.activo DESC, b.id DESC
        """)
        cols = [c[0] for c in cursor.description]
        beacons = [dict(zip(cols, row)) for row in cursor.fetchall()]
        cursor.close()
        return jsonify(beacons)
    except Exception as e:
        current_app.logger.error(f'[BLE/api_admin_beacons_lista] {e}')
        return jsonify([]), 500
    finally:
        if db: db.close()

# ── API: buscar equipos para asignar beacon ─────────────────────────

@ble_bp.route('/api/ble/admin/equipos/buscar', methods=['GET'])
@requiere_rol(ROL_BIOMEDICO)
def api_equipos_buscar():
    db = None
    try:
        q = (request.args.get('q') or '').strip()
        if len(q) < 2:
            return jsonify([])

        db = get_connection()
        cursor = db.cursor()
        cursor.execute("""
                    SELECT TOP 30
                        e.id,
                        e.equipo_unidad      AS nombre,
                        e.numero_inventario,
                        e.beacon_id,
                        b.mac               AS beacon_mac,
                        b.nombre            AS beacon_nombre
                    FROM [HospitalGalenia].[dbo].[InventarioEquipos] e
                    LEFT JOIN ble_beacons b ON b.id = e.beacon_id
                    WHERE (e.equipo_unidad LIKE ? OR e.numero_inventario LIKE ?)
                    /* AND e.activo = 1 */ -- Descomenta solo si agregaste esta columna a la tabla
                    ORDER BY e.equipo_unidad;
        """, (f'%{q}%', f'%{q}%'))
        cols    = [c[0] for c in cursor.description]
        equipos = [dict(zip(cols, row)) for row in cursor.fetchall()]
        cursor.close()
        return jsonify(equipos)
    except Exception as e:
        current_app.logger.error(f'[BLE/api_equipos_buscar] {e}')
        return jsonify([]), 500
    finally:
        if db: db.close()

# ══════════════════════════════════════════════════════════════
#  ADMIN — REGLAS DE ALERTA
# ══════════════════════════════════════════════════════════════

@ble_bp.route('/localizacion/admin/reglas')
@requiere_rol(ROL_BIOMEDICO)
def admin_reglas():
    """Vista principal de reglas de alerta."""
    return render_template('ble/admin/reglas.html')


@ble_bp.route('/api/ble/admin/reglas', methods=['GET'])
@requiere_rol(ROL_BIOMEDICO)
def api_reglas_lista():
    """Todas las reglas — activas e inactivas."""
    db = None
    try:
        db = get_connection()
        reglas = ModelBLE.get_todas_las_reglas(db)
        return jsonify(reglas)
    except Exception as e:
        current_app.logger.error(f'[BLE/api_reglas_lista] {e}')
        return jsonify([]), 500
    finally:
        if db: db.close()


@ble_bp.route('/api/ble/admin/reglas', methods=['POST'])
@requiere_rol(ROL_BIOMEDICO)
def api_regla_crear():
    """Crea una regla nueva."""
    db = None
    try:
        data         = request.get_json(force=True) or {}
        nombre       = (data.get('nombre') or '').strip()
        tipo         = (data.get('tipo') or '').strip()
        umbral_valor = data.get('umbral_valor')

        if not nombre or not tipo or umbral_valor is None:
            return jsonify({'error': 'nombre, tipo y umbral_valor son obligatorios'}), 400

        if tipo not in ('sin_senal', 'bateria', 'rssi'):
            return jsonify({'error': 'tipo inválido'}), 400

        db     = get_connection()
        new_id = ModelBLE.crear_regla(db, nombre, tipo, int(umbral_valor))
        if not new_id:
            return jsonify({'error': 'Error al crear la regla'}), 500

        current_app.logger.info(
            f'[BLE/admin] Regla creada id={new_id} tipo={tipo}'
        )
        return jsonify({'ok': True, 'id': new_id}), 201

    except Exception as e:
        current_app.logger.error(f'[BLE/api_regla_crear] {e}')
        return jsonify({'error': 'Error interno'}), 500
    finally:
        if db: db.close()


@ble_bp.route('/api/ble/admin/reglas/<int:regla_id>', methods=['PUT'])
@requiere_rol(ROL_BIOMEDICO)
def api_regla_editar(regla_id):
    """Edita nombre y umbral de una regla."""
    db = None
    try:
        data         = request.get_json(force=True) or {}
        nombre       = (data.get('nombre') or '').strip()
        umbral_valor = data.get('umbral_valor')

        if not nombre or umbral_valor is None:
            return jsonify({'error': 'nombre y umbral_valor son obligatorios'}), 400

        db = get_connection()
        ok = ModelBLE.actualizar_regla(db, regla_id, nombre, int(umbral_valor))
        if not ok:
            return jsonify({'error': 'Regla no encontrada'}), 404

        current_app.logger.info(f'[BLE/admin] Regla id={regla_id} actualizada')
        return jsonify({'ok': True})

    except Exception as e:
        current_app.logger.error(f'[BLE/api_regla_editar] {e}')
        return jsonify({'error': 'Error interno'}), 500
    finally:
        if db: db.close()


@ble_bp.route('/api/ble/admin/reglas/<int:regla_id>/toggle', methods=['PUT'])
@requiere_rol(ROL_BIOMEDICO)
def api_regla_toggle(regla_id):
    """Activa o desactiva una regla."""
    db = None
    try:
        db         = get_connection()
        nuevo_estado = ModelBLE.toggle_regla(db, regla_id)
        if nuevo_estado is None:
            return jsonify({'error': 'Regla no encontrada'}), 404

        current_app.logger.info(
            f'[BLE/admin] Regla id={regla_id} activa → {nuevo_estado}'
        )
        return jsonify({'ok': True, 'activa': nuevo_estado})

    except Exception as e:
        current_app.logger.error(f'[BLE/api_regla_toggle] {e}')
        return jsonify({'error': 'Error interno'}), 500
    finally:
        if db: db.close()


@ble_bp.route('/api/ble/admin/reglas/<int:regla_id>', methods=['DELETE'])
@requiere_rol(ROL_BIOMEDICO)
def api_regla_eliminar(regla_id):
    """Elimina una regla (solo las no-base, id > 3)."""
    db = None
    try:
        db = get_connection()
        ok = ModelBLE.eliminar_regla(db, regla_id)
        if not ok:
            return jsonify({
                'error': 'No se puede eliminar — regla base o no existe'
            }), 400

        current_app.logger.info(f'[BLE/admin] Regla id={regla_id} eliminada')
        return jsonify({'ok': True})

    except Exception as e:
        current_app.logger.error(f'[BLE/api_regla_eliminar] {e}')
        return jsonify({'error': 'Error interno'}), 500
    finally:
        if db: db.close()

# ══════════════════════════════════════════════════════════════
#  DIAGNÓSTICO — solo Administrador
# ══════════════════════════════════════════════════════════════

@ble_bp.route('/api/ble/admin/purgar-lecturas', methods=['POST'])
@requiere_rol(ROL_ADMIN)
def api_purgar_lecturas_manual():
    """
    Disparo manual de la purga — para verificar en desarrollo.
    Misma lógica que el job del scheduler.
    Body opcional: { "dias": 30 }

    Reservado al Administrador: borra histórico de lecturas de forma
    irreversible, no es una tarea operativa del biomédico.
    """
    db = None
    try:
        data = request.get_json(silent=True) or {}
        dias = int(data.get('dias', 30))
        dias = min(max(dias, 1), 365)   # clamp: 1 día mínimo, 1 año máximo

        db         = get_connection()
        eliminados = ModelBLE.purgar_lecturas_antiguas(db, dias=dias)

        current_app.logger.info(
            f"[BLE/purga_manual] {eliminados} lecturas eliminadas "
            f"(antigüedad > {dias} días)"
        )
        return jsonify({
            'ok':        True,
            'eliminados': eliminados,
            'dias':       dias,
        })

    except Exception as e:
        current_app.logger.error(f'[BLE/api_purgar_lecturas_manual] {e}')
        return jsonify({'error': 'Error interno'}), 500
    finally:
        if db: db.close()       

@ble_bp.route('/localizacion/vista3d')
@requiere_rol(ROL_USUARIO)
def vista_3d():
    """
    Visor 3D del hospital con los equipos que la localizacion BLE reporta.

    Solo entrega las coordenadas de los pines; los equipos los pide el propio
    visor a /api/ble/vista3d/datos y los refresca cada 10 segundos.
    """
    return render_template('ble/vista3d.html', areas_3d=AREAS_3D)