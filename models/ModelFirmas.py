import base64
import binascii
import io
import os
import re
import uuid
from datetime import datetime

from PIL import Image


class ModelFirmas:
    """
    Firmas de los reportes.

    Una firma es lo contrario del snapshot de Reportes.datos_json: se agrega
    después del alta y tiene ciclo de vida propio. Por eso vive en su propia
    tabla, con UNIQUE(reporte_id, rol) para que "una vez firmado ya no se
    cambia" sea una garantía del motor y no un if de la aplicación.

    El estado pendiente/firmado no se guarda: se deriva de qué filas existen.
    """

    TABLE = "HospitalGalenia.dbo.ReporteFirmas"

    # Roles del acta de alta, que fue el primer documento que firmó.
    ROL_ENTREGA = 'entrega'
    ROL_RECIBE  = 'recibe'
    ROLES_ALTA = (ROL_ENTREGA, ROL_RECIBE)

    # Roles de los tipos de reporte de la fase 2. Espejo del CK_ReporteFirmas_rol
    # que amplía 2026-08-19_reportes_nucleo.sql: si aquí falta uno, el modelo lo
    # rechaza antes de llegar a la base y el error dice "rol inválido" aunque el
    # motor lo aceptaría sin problema.
    ROL_REALIZO          = 'realizo'
    ROL_BIOMEDICO        = 'biomedico'
    ROL_RESPONSABLE_AREA = 'responsable_area'
    ROL_PROVEEDOR        = 'proveedor'
    ROL_AUTORIZA         = 'autoriza'

    ROLES = ROLES_ALTA + (ROL_REALIZO, ROL_BIOMEDICO, ROL_RESPONSABLE_AREA,
                          ROL_PROVEEDOR, ROL_AUTORIZA)

    ETIQUETAS_ROL = {
        ROL_ENTREGA:          'Entrega / Responsable',
        ROL_RECIBE:           'Recibe / Responsable de Área',
        ROL_REALIZO:          'Realizó el servicio',
        ROL_BIOMEDICO:        'Ingeniería Biomédica',
        ROL_RESPONSABLE_AREA: 'Responsable del área',
        ROL_PROVEEDOR:        'Proveedor',
        ROL_AUTORIZA:         'Autoriza',
    }

    # Los data URL del canvas siempre llegan como PNG; se acepta solo eso.
    _PATRON_DATA_URL = re.compile(r'^data:image/png;base64,(?P<datos>[A-Za-z0-9+/=\s]+)$')

    MAX_FIRMA_MB = 2

    # ─────────────────────────────────────────────────────────
    #  LECTURA
    # ─────────────────────────────────────────────────────────

    @classmethod
    def get_por_reporte(cls, db, reporte_id):
        """
        Devuelve {'entrega': {...}, 'recibe': {...}} con lo que ya esté firmado.
        Un rol sin firmar simplemente no aparece.
        """
        try:
            cursor = db.cursor()
            cursor.execute(f"""
                SELECT id, reporte_id, rol, nombre, cargo, imagen, usuario_id, fecha
                FROM {cls.TABLE}
                WHERE reporte_id = ?
            """, (reporte_id,))
            rows    = cursor.fetchall()
            columns = [col[0] for col in cursor.description]
            cursor.close()
            return {row[2]: dict(zip(columns, row)) for row in rows}
        except Exception as e:
            print(f"Error get_por_reporte firmas [{reporte_id}]: {e}")
            return {}

    @classmethod
    def esta_completo(cls, firmas):
        """True solo cuando están las dos firmas: el acta cuenta como firmada."""
        return all(rol in (firmas or {}) for rol in cls.ROLES)

    @classmethod
    def roles_pendientes(cls, firmas):
        """Roles que todavía faltan por firmar, en orden."""
        return [rol for rol in cls.ROLES if rol not in (firmas or {})]

    # ─────────────────────────────────────────────────────────
    #  ESCRITURA
    # ─────────────────────────────────────────────────────────

    @classmethod
    def crear(cls, db, reporte_id, rol, nombre, imagen_rel,
              cargo=None, usuario_id=None):
        """
        Registra una firma.

        Devuelve (ok: bool, mensaje: str). Rechaza si ese rol ya está firmado:
        una firma no se sustituye, ni siquiera por error de captura.
        """
        if rol not in cls.ROLES:
            return False, 'Rol de firma inválido.'
        if not (nombre or '').strip():
            return False, 'El nombre de quien firma es obligatorio.'
        if not imagen_rel:
            return False, 'Falta el trazo de la firma.'

        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT COUNT(*) FROM {cls.TABLE} WHERE reporte_id = ? AND rol = ?",
                (reporte_id, rol)
            )
            if cursor.fetchone()[0]:
                cursor.close()
                return False, 'Esa parte del reporte ya está firmada.'

            cursor.execute(f"""
                INSERT INTO {cls.TABLE}
                    (reporte_id, rol, nombre, cargo, imagen, usuario_id, fecha)
                VALUES (?, ?, ?, ?, ?, ?, GETDATE())
            """, (
                reporte_id,
                rol,
                nombre.strip()[:150],
                (cargo or '').strip()[:150] or None,
                imagen_rel,
                usuario_id,
            ))
            db.commit()
            cursor.close()
            return True, 'Firma registrada.'

        except Exception as e:
            # Si dos personas firman el mismo rol a la vez, el UNIQUE de la BD
            # es quien decide; aquí solo se traduce el error.
            print(f"Error crear firma [{reporte_id}/{rol}]: {e}")
            db.rollback()
            if 'UQ_ReporteFirmas_rol' in str(e):
                return False, 'Esa parte del reporte ya está firmada.'
            return False, 'No se pudo registrar la firma.'

    # ─────────────────────────────────────────────────────────
    #  ARCHIVO
    # ─────────────────────────────────────────────────────────

    @classmethod
    def guardar_firma_png(cls, data_url, flag='firmas'):
        """
        Guarda el trazo del canvas como PNG y devuelve la ruta relativa
        ('firmas/xxxx.png'), con la misma convención que
        ModelInventario.guardar_imagen.

        Se conserva PNG y no JPEG: un trazo de un píxel se deshace con
        compresión con pérdida. Se recorta el margen vacío para que la firma
        ocupe su recuadro del PDF sin depender de dónde se dibujó en el canvas.
        """
        if not data_url:
            raise ValueError("No se recibió ninguna firma")

        match = cls._PATRON_DATA_URL.match(data_url.strip())
        if not match:
            raise ValueError("El formato de la firma no es válido")

        try:
            crudo = base64.b64decode(match.group('datos'), validate=False)
        except (binascii.Error, ValueError):
            raise ValueError("El formato de la firma no es válido")

        if len(crudo) > cls.MAX_FIRMA_MB * 1024 * 1024:
            raise ValueError("La firma es demasiado grande")

        # Validar que sea un PNG real y no cualquier cosa en base64
        try:
            img = Image.open(io.BytesIO(crudo))
            img.verify()
            img = Image.open(io.BytesIO(crudo))
        except Exception:
            raise ValueError("El archivo de la firma no es una imagen válida")

        img = img.convert('RGBA')

        # Recortar el área realmente dibujada. getbbox() sobre el canal alfa
        # ignora lo transparente; si el pad llegara opaco, el bbox es la imagen
        # completa y no se recorta nada.
        caja = img.split()[-1].getbbox()
        if caja:
            margen = 6
            izq, arr, der, aba = caja
            img = img.crop((
                max(izq - margen, 0),
                max(arr - margen, 0),
                min(der + margen, img.width),
                min(aba + margen, img.height),
            ))

        if img.width < 2 or img.height < 2:
            raise ValueError("La firma está vacía")

        buffer = io.BytesIO()
        img.save(buffer, 'PNG', optimize=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename  = f"{timestamp}_{uuid.uuid4().hex[:8]}.png"

        base_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'static', 'uploads', flag)
        )
        os.makedirs(base_path, exist_ok=True)
        filepath = os.path.join(base_path, filename)

        try:
            with open(filepath, 'wb') as f:
                f.write(buffer.getvalue())
            return os.path.join(flag, filename).replace('\\', '/')
        except Exception as e:
            if os.path.exists(filepath):
                os.remove(filepath)
            raise ValueError(f"Error al guardar la firma: {e}")
