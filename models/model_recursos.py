import os
import uuid
from datetime import datetime
from werkzeug.utils import secure_filename


class ModelRecursos:
    """
    Métodos para gestión de Recursos y su vinculación a equipos.
    Usados por el blueprint 'admin' (subida) y 'equipos' (lectura).
    """

    TABLE_RECURSOS       = "HospitalGalenia.dbo.Recursos"
    TABLE_EQUIPO_REC     = "HospitalGalenia.dbo.EquipoRecursos"
    TABLE_INVENTARIO     = "HospitalGalenia.dbo.InventarioEquipos"

    # Extensiones permitidas por tipo — validación en Flask, no en BD
    TIPOS_PERMITIDOS = {
        'pdf':    ['.pdf'],
        'imagen': ['.jpg', '.jpeg', '.png', '.webp', '.gif'],
        'video':  ['.mp4', '.mov', '.avi'],
        'excel':  ['.xlsx', '.xls'],
        'word':   ['.docx', '.doc'],
        'link':   [],        # no tiene archivo físico
        'otro':   ['.zip', '.rar', '.pptx', '.svg']
    }

    CATEGORIAS_VALIDAS = [
        'guia_rapida', 'manual_servicio', 'manual_usuario', 'ficha_tecnica', 'capacitacion', 'otro'
    ]

    # ─────────────────────────────────────────────────────────
    #  LECTURA
    # ─────────────────────────────────────────────────────────

    @classmethod
    def get_recursos_por_equipo(cls, db, equipo_id, categoria=None):
        """
        Devuelve todos los recursos vinculados a un equipo.
        Si se pasa categoria filtra por ella (ej: 'guia_rapida').
        Usado en: guias_rapidas.html y futuras vistas de recursos.
        """
        try:
            cursor = db.cursor()

            params = [equipo_id]
            cat_sql = ""
            if categoria:
                cat_sql = "AND r.categoria = ?"
                params.append(categoria)

            cursor.execute(f"""
                SELECT
                    r.id, r.nombre, r.tipo, r.categoria,
                    r.archivo, r.descripcion, r.fecha_subida, r.subido_por
                FROM {cls.TABLE_RECURSOS} r
                INNER JOIN {cls.TABLE_EQUIPO_REC} er ON er.recurso_id = r.id
                WHERE er.equipo_id = ? {cat_sql}
                ORDER BY r.fecha_subida DESC
            """, params)

            rows    = cursor.fetchall()
            columns = [col[0] for col in cursor.description]
            cursor.close()

            return [dict(zip(columns, row)) for row in rows]

        except Exception as e:
            print(f"Error get_recursos_por_equipo [{equipo_id}]: {e}")
            return []

    @classmethod
    def get_equipos_vinculados(cls, db, recurso_id):
        """
        Devuelve todos los equipos vinculados a un recurso.
        Útil para mostrar cuántos equipos recibirán el recurso al subirlo.
        """
        try:
            cursor = db.cursor()
            cursor.execute(f"""
                SELECT
                    i.id, i.equipo_unidad, i.marca, i.modelo,
                    i.numero_inventario, i.departamento
                FROM {cls.TABLE_INVENTARIO} i
                INNER JOIN {cls.TABLE_EQUIPO_REC} er ON er.equipo_id = i.id
                WHERE er.recurso_id = ?
                ORDER BY i.numero_inventario
            """, (recurso_id,))

            rows    = cursor.fetchall()
            columns = [col[0] for col in cursor.description]
            cursor.close()

            return [dict(zip(columns, row)) for row in rows]

        except Exception as e:
            print(f"Error get_equipos_vinculados [{recurso_id}]: {e}")
            return []

    @classmethod
    def contar_equipos_coincidentes(cls, db, marca, modelo):
        """
        Cuántos equipos comparten marca + modelo.
        Se usa en el formulario para mostrar el aviso antes de subir.
        Ej: 'Este recurso se vinculará a 8 equipos BeneFusion EVP'
        """
        try:
            cursor = db.cursor()
            cursor.execute(f"""
                SELECT COUNT(*)
                FROM {cls.TABLE_INVENTARIO}
                WHERE marca = ? AND modelo = ?
            """, (marca, modelo))
            total = cursor.fetchone()[0]
            cursor.close()
            return total
        except Exception as e:
            print(f"Error contar_equipos_coincidentes: {e}")
            return 0

    @classmethod
    def get_by_id(cls, db, recurso_id):
        """Obtiene un recurso por su PK."""
        try:
            cursor = db.cursor()
            cursor.execute(f"""
                SELECT id, nombre, tipo, categoria, archivo,
                       descripcion, fecha_subida, subido_por
                FROM {cls.TABLE_RECURSOS}
                WHERE id = ?
            """, (recurso_id,))
            row = cursor.fetchone()
            if not row:
                return None
            columns = [col[0] for col in cursor.description]
            cursor.close()
            return dict(zip(columns, row))
        except Exception as e:
            print(f"Error get_by_id recurso [{recurso_id}]: {e}")
            return None

    # ─────────────────────────────────────────────────────────
    #  ESCRITURA
    # ─────────────────────────────────────────────────────────

    @classmethod
    def crear_recurso(cls, db, datos, equipo_origen_id):
        """
        Inserta el recurso y lo vincula automáticamente a todos
        los equipos que coincidan en marca + modelo del equipo origen.

        datos = {
            'nombre':      str,
            'tipo':        str,
            'categoria':   str,
            'archivo':     str,   ← ruta relativa o URL
            'descripcion': str,
            'subido_por':  str
        }

        Devuelve (ok: bool, recurso_id: int | None, equipos_vinculados: int)
        """
        try:
            cursor = db.cursor()

            # 1 — Obtener marca y modelo del equipo origen
            cursor.execute(f"""
                SELECT marca, modelo
                FROM {cls.TABLE_INVENTARIO}
                WHERE id = ?
            """, (equipo_origen_id,))
            row = cursor.fetchone()
            if not row:
                return False, None, 0
            marca, modelo = row

            # 2 — Insertar en Recursos
            cursor.execute(f"""
                INSERT INTO {cls.TABLE_RECURSOS}
                    (nombre, tipo, categoria, archivo, descripcion, subido_por)
                OUTPUT INSERTED.id
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                datos.get('nombre'),
                datos.get('tipo'),
                datos.get('categoria'),
                datos.get('archivo'),
                datos.get('descripcion', ''),
                datos.get('subido_por', '')
            ))
            recurso_id = cursor.fetchone()[0]

            # 3 — Buscar todos los equipos con misma marca + modelo
            cursor.execute(f"""
                SELECT id FROM {cls.TABLE_INVENTARIO}
                WHERE marca = ? AND modelo = ?
            """, (marca, modelo))
            equipos = [r[0] for r in cursor.fetchall()]

            # 4 — Insertar en EquipoRecursos por cada equipo encontrado
            for eq_id in equipos:
                cursor.execute(f"""
                    INSERT INTO {cls.TABLE_EQUIPO_REC} (equipo_id, recurso_id)
                    VALUES (?, ?)
                """, (eq_id, recurso_id))

            db.commit()
            cursor.close()
            return True, recurso_id, len(equipos)

        except Exception as e:
            print(f"Error crear_recurso: {e}")
            db.rollback()
            return False, None, 0

    @classmethod
    def eliminar_recurso(cls, db, recurso_id):
        """
        Elimina el recurso. Las filas de EquipoRecursos
        se eliminan solas por el CASCADE definido en la BD.
        El archivo físico lo maneja la ruta en Flask.
        Devuelve la ruta del archivo para que Flask lo borre del disco.
        """
        try:
            cursor = db.cursor()

            # Guardar la ruta antes de borrar
            cursor.execute(f"""
                SELECT archivo, tipo FROM {cls.TABLE_RECURSOS} WHERE id = ?
            """, (recurso_id,))
            row = cursor.fetchone()
            archivo = row[0] if row else None
            tipo    = row[1] if row else None

            cursor.execute(f"""
                DELETE FROM {cls.TABLE_RECURSOS} WHERE id = ?
            """, (recurso_id,))

            db.commit()
            cursor.close()

            # Devuelve la ruta solo si es archivo físico (no link)
            return True, archivo if tipo != 'link' else None

        except Exception as e:
            print(f"Error eliminar_recurso [{recurso_id}]: {e}")
            db.rollback()
            return False, None

    # ─────────────────────────────────────────────────────────
    #  MANEJO DE ARCHIVO FÍSICO
    # ─────────────────────────────────────────────────────────

    @classmethod
    def guardar_archivo(cls, archivo_file, categoria, tipo):
        """
        Guarda el archivo en /static/recursos/<categoria>/
        Devuelve la ruta relativa para guardar en BD.
        Ej: 'recursos/guia_rapida/20250401_abc123.pdf'
        """
        if not archivo_file:
            raise ValueError("No se proporcionó ningún archivo")

        # Validar extensión contra el tipo declarado
        ext = os.path.splitext(archivo_file.filename)[1].lower()
        permitidas = cls.TIPOS_PERMITIDOS.get(tipo, [])
        if permitidas and ext not in permitidas:
            raise ValueError(
                f"Extensión '{ext}' no válida para tipo '{tipo}'. "
                f"Permitidas: {', '.join(permitidas)}"
            )

        # Validar tamaño (máx 20MB para PDFs y videos)
        archivo_file.seek(0, 2)
        size = archivo_file.tell()
        archivo_file.seek(0)
        if size > 100 * 1024 * 1024:
            raise ValueError("El archivo excede 100MB")

        # Nombre único
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_id = uuid.uuid4().hex[:8]
        filename  = secure_filename(f"{timestamp}_{unique_id}{ext}")

        # Subcarpeta por categoría
        base_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'static', 'recursos', categoria)
        )
        os.makedirs(base_path, exist_ok=True)

        archivo_file.save(os.path.join(base_path, filename))

        # Ruta relativa para la BD
        return f"recursos/{categoria}/{filename}"

    @classmethod
    def eliminar_archivo_fisico(cls, ruta_relativa):
        """
        Borra el archivo físico del disco.
        ruta_relativa viene de la columna 'archivo' en la BD.
        """
        if not ruta_relativa:
            return
        try:
            path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), '..', 'static', ruta_relativa)
            )
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            print(f"Error eliminar_archivo_fisico [{ruta_relativa}]: {e}")

    # ─────────────────────────────────────────────────────────
    #  VALIDACIÓN
    # ─────────────────────────────────────────────────────────

    @classmethod
    def validar_datos(cls, datos, tiene_archivo):
        """
        Valida los datos del formulario antes de procesar.
        Devuelve (ok: bool, mensaje: str)
        """
        if not datos.get('nombre', '').strip():
            return False, "El nombre del recurso es obligatorio"

        if datos.get('tipo') not in cls.TIPOS_PERMITIDOS:
            return False, f"Tipo no válido: {datos.get('tipo')}"

        if datos.get('categoria') not in cls.CATEGORIAS_VALIDAS:
            return False, f"Categoría no válida: {datos.get('categoria')}"

        if datos.get('tipo') == 'link':
            if not datos.get('archivo', '').strip():
                return False, "Debes proporcionar una URL para tipo 'link'"
        else:
            if not tiene_archivo:
                return False, "Debes seleccionar un archivo"

        return True, ""