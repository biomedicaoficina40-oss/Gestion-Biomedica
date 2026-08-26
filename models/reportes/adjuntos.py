"""
Fotos y archivos de un reporte.

Generaliza lo que ModelInventario.guardar_imagen hace para la foto del equipo, y
le agrega tres cosas que ahí no hacían falta y aquí sí:

  1. **Tres derivados por foto** en vez de uno. Un JPEG de celular de 8 MP metido
     tal cual en un PDF con WeasyPrint 52.5 lo vuelve inviable: se maqueta cuatro
     veces y cada pasada vuelve a decodificar la imagen.

  2. **Corrección de orientación.** Los celulares no rotan el archivo: guardan la
     foto horizontal y anotan en EXIF cómo debe verse. Pillow abre los píxeles
     crudos, así que sin exif_transpose() una foto tomada en vertical sale
     acostada en el PDF. La foto del equipo nunca lo notó porque casi siempre se
     toma en horizontal; las de evidencia se toman con el teléfono en la mano.

  3. **Borrado explícito de EXIF.** Los teléfonos incrustan coordenadas GPS. Un
     reporte que se comparte fuera del hospital no tiene por qué llevar la
     ubicación exacta de dónde se tomó cada foto.

Los archivos viven en disco bajo static/uploads/reportes/adjuntos/<reporte_id>/;
en la base de datos solo va la ruta relativa, el hash y a qué etapa pertenece.
"""

import hashlib
import io
import os
import uuid
from datetime import datetime

from flask import current_app
from PIL import Image, ImageOps
from werkzeug.utils import secure_filename

# Clases de adjunto. Las cuatro primeras son fotos; las dos últimas, archivos.
# 'foto_estado' es la de entrada/salida: una sola etapa (no hay antes/durante/
# después en un movimiento), en cantidad indefinida — un lote que sale en masa
# puede necesitar documentar varias piezas.
CLASES_FOTO = ('foto_antes', 'foto_durante', 'foto_despues', 'foto_estado')
CLASES_ARCHIVO = ('documento', 'requisicion')
CLASES = CLASES_FOTO + CLASES_ARCHIVO

ETIQUETAS = {
    'foto_antes':   'Antes',
    'foto_durante': 'Durante',
    'foto_despues': 'Después',
    'foto_estado':  'Estado',
    'documento':    'Documento',
    'requisicion':  'Requisición',
}

# Qué se imprime en el anexo del PDF por omisión.
#
# Las fotos del proceso quedan APAGADAS: son las más numerosas y las que menos
# le dicen a quien lee el documento formal, pero son justo las que le sirven al
# técnico que abra ese equipo dentro de seis meses. Su lugar es el expediente,
# no el papel. Cada una puede encenderse a mano si merece imprimirse.
INCLUIR_POR_OMISION = {
    'foto_antes':   True,
    'foto_durante': False,
    'foto_despues': True,
    'foto_estado':  True,
    'documento':    False,
    'requisicion':  False,
}

EXTENSIONES_IMAGEN = ('.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif')
EXTENSIONES_ARCHIVO = ('.pdf', '.jpg', '.jpeg', '.png', '.webp',
                       '.doc', '.docx', '.xls', '.xlsx')

# Derivados: (sufijo, lado mayor en px, calidad JPEG)
DERIVADOS = (
    ('',       1200, 82),   # 'web': el que se ve en el módulo
    ('_thumb',  300, 78),   # listados y galería
    ('_pdf',    900, 80),   # el que entra al anexo
)

MAX_MB_ORIGEN = 25      # lo que acepta subir; después se comprime
MAX_ADJUNTOS = 40       # por reporte y clase


class ModelAdjuntos:
    TABLE = "HospitalGalenia.dbo.ReporteAdjuntos"
    COLS = """ id, reporte_id, clase, archivo, archivo_thumb, archivo_pdf,
               nombre_original, descripcion, orden, sha256, incluir_en_pdf,
               subido_por, fecha """

    # ── Lectura ────────────────────────────────────────────────

    @classmethod
    def get_por_reporte(cls, db, reporte_id, clase=None, solo_pdf=False):
        """
        Adjuntos de un reporte, en el orden en que deben mostrarse.

        `solo_pdf` filtra los que van al anexo, que es lo que necesita el
        generador de PDF; el módulo en pantalla los quiere todos.
        """
        cursor = None
        try:
            cursor = db.cursor()
            sql = f"SELECT {cls.COLS} FROM {cls.TABLE} WHERE reporte_id = ?"
            params = [reporte_id]
            if clase:
                sql += " AND clase = ?"
                params.append(clase)
            if solo_pdf:
                sql += " AND incluir_en_pdf = 1"
            sql += " ORDER BY CASE clase WHEN 'foto_antes' THEN 1 " \
                   "WHEN 'foto_durante' THEN 2 WHEN 'foto_despues' THEN 3 " \
                   "ELSE 4 END, orden, id"

            cursor.execute(sql, tuple(params))
            columnas = [c[0] for c in cursor.description]
            return [dict(zip(columnas, fila)) for fila in cursor.fetchall()]
        except Exception as e:
            current_app.logger.error(
                f"[ModelAdjuntos.get_por_reporte] reporte={reporte_id} | {e}")
            return []
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def get_by_id(cls, db, adjunto_id):
        """
        Un adjunto suelto.

        Lo pide la subida por fetch: al terminar devuelve la fila completa para
        que la pantalla pinte la miniatura en su sitio en vez de recargar. En un
        teléfono, junto al equipo, recargar tras cada foto cuesta segundos y a
        veces la conexión del hospital ni siquiera lo permite.
        """
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT {cls.COLS} FROM {cls.TABLE} WHERE id = ?", (adjunto_id,))
            fila = cursor.fetchone()
            if not fila:
                return None
            columnas = [c[0] for c in cursor.description]
            return dict(zip(columnas, fila))
        except Exception as e:
            current_app.logger.error(
                f"[ModelAdjuntos.get_by_id] id={adjunto_id} | {e}")
            return None
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def agrupar_por_clase(cls, adjuntos):
        """Agrupa una lista ya leída, para que la plantilla no filtre en Jinja."""
        grupos = {clase: [] for clase in CLASES}
        for adjunto in adjuntos:
            grupos.setdefault(adjunto.get('clase'), []).append(adjunto)
        return grupos

    @classmethod
    def contar(cls, db, reporte_id, clase):
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT COUNT(*) FROM {cls.TABLE} WHERE reporte_id = ? AND clase = ?",
                (reporte_id, clase))
            return cursor.fetchone()[0] or 0
        except Exception as e:
            current_app.logger.error(f"[ModelAdjuntos.contar] {e}")
            return 0
        finally:
            if cursor:
                cursor.close()

    # ── Procesamiento de imagen ────────────────────────────────

    @classmethod
    def _carpeta(cls, reporte_id):
        """Carpeta absoluta del reporte, creada si hace falta."""
        base = os.path.abspath(os.path.join(
            os.path.dirname(__file__), '..', '..', 'static', 'uploads',
            'reportes', 'adjuntos', str(int(reporte_id))))
        os.makedirs(base, exist_ok=True)
        return base

    @classmethod
    def _ruta_relativa(cls, reporte_id, nombre):
        """Ruta tal como se guarda en la BD, siempre con '/'."""
        return f"reportes/adjuntos/{int(reporte_id)}/{nombre}"

    @classmethod
    def procesar_imagen(cls, archivo, reporte_id):
        """
        Genera los tres derivados de una foto y devuelve sus rutas relativas.

        Devuelve (rutas: dict, sha256: str) o levanta ValueError con un mensaje
        que se le puede enseñar al usuario tal cual.
        """
        if not archivo or not getattr(archivo, 'filename', ''):
            raise ValueError("No se recibió ninguna imagen")

        extension = os.path.splitext(archivo.filename)[1].lower()
        if extension not in EXTENSIONES_IMAGEN:
            raise ValueError(
                f"Formato no permitido. Use: {', '.join(EXTENSIONES_IMAGEN)}")

        crudo = archivo.read()
        if not crudo:
            raise ValueError("El archivo llegó vacío")
        if len(crudo) > MAX_MB_ORIGEN * 1024 * 1024:
            raise ValueError(f"La imagen supera {MAX_MB_ORIGEN} MB")

        # Validar por contenido y no por extensión: un .exe renombrado a .jpg
        # pasa el filtro de arriba pero muere aquí.
        try:
            Image.open(io.BytesIO(crudo)).verify()
            imagen = Image.open(io.BytesIO(crudo))
        except Exception:
            raise ValueError("El archivo no es una imagen válida")

        # Orientación ANTES de cualquier otra cosa: si se redimensiona primero,
        # el thumbnail sale con las proporciones cambiadas.
        try:
            imagen = ImageOps.exif_transpose(imagen)
        except Exception:
            pass    # sin EXIF o EXIF corrupto: se usa tal cual

        if imagen.mode in ('RGBA', 'LA', 'P'):
            fondo = Image.new('RGB', imagen.size, 'white')
            imagen = imagen.convert('RGBA')
            fondo.paste(imagen, mask=imagen.split()[-1])
            imagen = fondo
        elif imagen.mode != 'RGB':
            imagen = imagen.convert('RGB')

        sello = datetime.now().strftime('%Y%m%d_%H%M%S')
        base_nombre = secure_filename(f"{sello}_{uuid.uuid4().hex[:8]}")
        carpeta = cls._carpeta(reporte_id)

        rutas = {}
        digest = None
        escritos = []
        try:
            for sufijo, lado, calidad in DERIVADOS:
                copia = imagen.copy()
                copia.thumbnail((lado, lado), Image.Resampling.LANCZOS)

                buffer = io.BytesIO()
                # Sin `exif=`, Pillow no reescribe los metadatos: el derivado
                # sale limpio de GPS, modelo de teléfono y fecha de captura.
                copia.save(buffer, 'JPEG', quality=calidad, optimize=True)
                contenido = buffer.getvalue()

                nombre = f"{base_nombre}{sufijo}.jpg"
                destino = os.path.join(carpeta, nombre)
                with open(destino, 'wb') as salida:
                    salida.write(contenido)
                escritos.append(destino)

                rutas[sufijo or 'web'] = cls._ruta_relativa(reporte_id, nombre)
                if sufijo == '':
                    digest = hashlib.sha256(contenido).hexdigest()

            return rutas, digest

        except Exception as e:
            # Si un derivado falla se borran los que sí se escribieron, para no
            # dejar huérfanos que nadie va a limpiar.
            for ruta in escritos:
                try:
                    os.remove(ruta)
                except OSError:
                    pass
            raise ValueError(f"No se pudo procesar la imagen: {e}")

    @classmethod
    def procesar_archivo(cls, archivo, reporte_id):
        """
        Guarda un archivo que no es foto (requisición, cotización, manual).

        No se le generan derivados ni se le toca el contenido: un PDF de compras
        tiene que llegar idéntico a como lo emitió el sistema del hospital.
        """
        if not archivo or not getattr(archivo, 'filename', ''):
            raise ValueError("No se recibió ningún archivo")

        extension = os.path.splitext(archivo.filename)[1].lower()
        if extension not in EXTENSIONES_ARCHIVO:
            raise ValueError(
                f"Formato no permitido. Use: {', '.join(EXTENSIONES_ARCHIVO)}")

        crudo = archivo.read()
        if not crudo:
            raise ValueError("El archivo llegó vacío")
        if len(crudo) > MAX_MB_ORIGEN * 1024 * 1024:
            raise ValueError(f"El archivo supera {MAX_MB_ORIGEN} MB")

        sello = datetime.now().strftime('%Y%m%d_%H%M%S')
        nombre = secure_filename(f"{sello}_{uuid.uuid4().hex[:8]}{extension}")
        destino = os.path.join(cls._carpeta(reporte_id), nombre)
        with open(destino, 'wb') as salida:
            salida.write(crudo)

        return ({'web': cls._ruta_relativa(reporte_id, nombre)},
                hashlib.sha256(crudo).hexdigest())

    # ── Escritura ──────────────────────────────────────────────

    @classmethod
    def crear(cls, db, reporte_id, clase, archivo, descripcion=None,
              usuario_id=None):
        """
        Procesa y registra un adjunto. Devuelve (ok, mensaje_o_id).

        El archivo se escribe en disco ANTES del INSERT. Si el INSERT falla se
        borra lo escrito: es preferible perder una foto que el usuario puede
        volver a subir, a dejar archivos que ninguna fila referencia.
        """
        if clase not in CLASES:
            return False, f"Clase de adjunto no válida: {clase}"

        if cls.contar(db, reporte_id, clase) >= MAX_ADJUNTOS:
            return False, f"Ya hay {MAX_ADJUNTOS} archivos en «{ETIQUETAS[clase]}»"

        try:
            if clase in CLASES_FOTO:
                rutas, digest = cls.procesar_imagen(archivo, reporte_id)
            else:
                rutas, digest = cls.procesar_archivo(archivo, reporte_id)
        except ValueError as e:
            return False, str(e)

        cursor = None
        try:
            cursor = db.cursor()

            cursor.execute(
                f"SELECT ISNULL(MAX(orden), 0) + 1 FROM {cls.TABLE} "
                f"WHERE reporte_id = ? AND clase = ?",
                (reporte_id, clase))
            orden = cursor.fetchone()[0]

            cursor.execute(
                f"INSERT INTO {cls.TABLE} "
                f"(reporte_id, clase, archivo, archivo_thumb, archivo_pdf, "
                f" nombre_original, descripcion, orden, sha256, incluir_en_pdf, "
                f" subido_por) "
                f"OUTPUT INSERTED.id "
                f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (reporte_id, clase,
                 rutas.get('web'), rutas.get('_thumb'), rutas.get('_pdf'),
                 (archivo.filename or '')[:255],
                 (descripcion or '').strip()[:300] or None,
                 orden, digest,
                 1 if INCLUIR_POR_OMISION.get(clase, True) else 0,
                 usuario_id)
            )
            nuevo_id = cursor.fetchone()[0]
            db.commit()
            return True, nuevo_id

        except Exception as e:
            current_app.logger.error(
                f"[ModelAdjuntos.crear] reporte={reporte_id} clase={clase} | {e}")
            try:
                db.rollback()
            except Exception:
                pass
            cls._borrar_archivos(rutas)
            return False, "No se pudo registrar el archivo"
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def actualizar(cls, db, adjunto_id, descripcion=None, incluir_en_pdf=None):
        """Cambia el pie de foto o si la foto entra al anexo."""
        campos, valores = [], []
        if descripcion is not None:
            campos.append("descripcion = ?")
            valores.append((descripcion or '').strip()[:300] or None)
        if incluir_en_pdf is not None:
            campos.append("incluir_en_pdf = ?")
            valores.append(1 if incluir_en_pdf else 0)
        if not campos:
            return True

        cursor = None
        try:
            cursor = db.cursor()
            valores.append(adjunto_id)
            cursor.execute(
                f"UPDATE {cls.TABLE} SET {', '.join(campos)} WHERE id = ?",
                tuple(valores))
            db.commit()
            return True
        except Exception as e:
            current_app.logger.error(f"[ModelAdjuntos.actualizar] id={adjunto_id} | {e}")
            try:
                db.rollback()
            except Exception:
                pass
            return False
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def eliminar(cls, db, adjunto_id):
        """Borra la fila y sus archivos. Devuelve (ok, mensaje)."""
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT archivo, archivo_thumb, archivo_pdf FROM {cls.TABLE} "
                f"WHERE id = ?", (adjunto_id,))
            fila = cursor.fetchone()
            if not fila:
                return False, "El archivo ya no existe"

            cursor.execute(f"DELETE FROM {cls.TABLE} WHERE id = ?", (adjunto_id,))
            db.commit()

            # Los archivos se borran después del commit: si el DELETE hubiera
            # fallado, la fila seguiría apuntando a algo que sí existe.
            cls._borrar_archivos({'a': fila[0], 'b': fila[1], 'c': fila[2]})
            return True, "Archivo eliminado"

        except Exception as e:
            current_app.logger.error(f"[ModelAdjuntos.eliminar] id={adjunto_id} | {e}")
            try:
                db.rollback()
            except Exception:
                pass
            return False, "No se pudo eliminar el archivo"
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def _borrar_archivos(cls, rutas):
        """Borra del disco las rutas relativas que traiga el diccionario."""
        base = os.path.abspath(os.path.join(
            os.path.dirname(__file__), '..', '..', 'static', 'uploads'))
        for ruta in (rutas or {}).values():
            if not ruta:
                continue
            try:
                completa = os.path.join(base, *str(ruta).split('/'))
                if os.path.exists(completa):
                    os.remove(completa)
            except OSError as e:
                current_app.logger.warning(
                    f"[ModelAdjuntos] no se pudo borrar {ruta}: {e}")
