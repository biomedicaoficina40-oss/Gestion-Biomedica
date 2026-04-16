import os
import uuid
from datetime import datetime
from PIL import Image
from werkzeug.utils import secure_filename

class ModelInventario:
    """
    Métodos para la gestión de inventario desde el panel ADMIN.
    Usados por el blueprint 'admin'.
    """

    TABLE = "HospitalGalenia.dbo.InventarioEquipos"

    # ── Columnas SELECT reutilizables ─────────────────────────
    COLS = """
        id, area, equipo_unidad, marca, modelo,
        numero_serie, numero_inventario, fecha_fabricacion,
        propiedad, estado, fecha_adquisicion, fecha_fin_garantia,
        departamento, imagen, observaciones
    """

    # ─────────────────────────────────────────────────────────
    #  LECTURA
    # ─────────────────────────────────────────────────────────

    @classmethod
    def get_by_id(cls, db, id):
        """
        Obtiene un equipo por PK (id entero).
        Deja las fechas como None para que los cálculos del template funcionen.
        """
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT {cls.COLS} FROM {cls.TABLE} WHERE id = ?", (id,)
            )
            row = cursor.fetchone()
            if row is None:
                return None

            columns = [col[0] for col in cursor.description]
            equipo  = dict(zip(columns, row))

            # Solo convertir a '' los campos string, NO las fechas
            fechas = {'fecha_fabricacion', 'fecha_adquisicion', 'fecha_fin_garantia'}
            for key, value in equipo.items():
                if value is None and key not in fechas:
                    equipo[key] = ''

            cursor.close()
            return equipo

        except Exception as e:
            print(f"Error get_by_id [{id}]: {e}")
            return None

    @classmethod
    def get_inventario(cls, db, q='', depto='', estado='', marca='',
                       propiedad='', sort='', direction='asc',
                       page=1, per_page=15):
        """
        Lista paginada con búsqueda, filtros y ordenamiento.
        Devuelve (lista_equipos, total_registros).
        """
        SORTABLE = {
            'numero_inventario', 'numero_serie', 'equipo_unidad',
            'marca', 'departamento', 'estado'
        }

        params = []
        wheres = []

        if q:
            term = f"%{q.lower()}%"
            wheres.append("""(
                LOWER(numero_inventario) LIKE ? OR
                LOWER(numero_serie)      LIKE ? OR
                LOWER(equipo_unidad)     LIKE ? OR
                LOWER(marca)             LIKE ? OR
                LOWER(modelo)            LIKE ? OR
                LOWER(departamento)      LIKE ?
            )""")
            params.extend([term] * 6)

        if depto:     wheres.append("departamento = ?"); params.append(depto)
        if estado:    wheres.append("estado = ?");       params.append(estado)
        if marca:     wheres.append("marca = ?");        params.append(marca)
        if propiedad: wheres.append("propiedad = ?");    params.append(propiedad)

        where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""

        cursor = db.cursor()
        cursor.execute(
            f"SELECT COUNT(*) FROM {cls.TABLE} {where_sql}", params
        )
        total = cursor.fetchone()[0]

        dir_sql   = "ASC" if direction.lower() == "asc" else "DESC"
        order_sql = f"ORDER BY {sort} {dir_sql}" if sort in SORTABLE \
                    else "ORDER BY numero_inventario ASC"

        offset = (page - 1) * per_page
        cursor.execute(
            f"SELECT {cls.COLS} FROM {cls.TABLE} "
            f"{where_sql} {order_sql} "
            f"OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
            params + [offset, per_page]
        )
        rows    = cursor.fetchall()
        columns = [col[0] for col in cursor.description]

        equipos = []
        for row in rows:
            eq = dict(zip(columns, row))
            for k, v in eq.items():
                if v is None:
                    eq[k] = ''
            equipos.append(eq)

        cursor.close()
        return equipos, total

    @classmethod
    def get_stats(cls, db):
        """Conteo por estado para el widget del inventario."""
        cursor = db.cursor()
        cursor.execute(f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN estado = 'Operativo'         THEN 1 ELSE 0 END),
                SUM(CASE WHEN estado = 'Mantenimiento'     THEN 1 ELSE 0 END),
                SUM(CASE WHEN estado = 'Fuera de Servicio' THEN 1 ELSE 0 END)
            FROM {cls.TABLE}
        """)
        row = cursor.fetchone()
        cursor.close()
        return {
            'total':             row[0] or 0,
            'operativos':        row[1] or 0,
            'mantenimiento':     row[2] or 0,
            'fuera_de_servicio': row[3] or 0,
        }

    @classmethod
    def get_marcas(cls, db):
        return cls._distinct(db, 'marca')

    @classmethod
    def get_departamentos(cls, db):
        return cls._distinct(db, 'departamento')

    @classmethod
    def get_propiedades(cls, db):
        return cls._distinct(db, 'propiedad')

    @staticmethod
    def _distinct(db, campo):
        cursor = db.cursor()
        cursor.execute(
            f"SELECT DISTINCT {campo} FROM HospitalGalenia.dbo.InventarioEquipos "
            f"WHERE {campo} IS NOT NULL AND {campo} <> '' ORDER BY {campo}"
        )
        rows = cursor.fetchall()
        cursor.close()
        return [r[0] for r in rows]

    # ─────────────────────────────────────────────────────────
    #  ESCRITURA  (implementar cuando corresponda)
    # ─────────────────────────────────────────────────────────

    @classmethod
    def generar_numero_inventario(cls, db, prefijo):
        """
        Genera el siguiente número de inventario para el prefijo dado.
        Primero agota 3 dígitos (001-999), luego pasa a 4 (0001-9999).
        Lógica MAX+1 sin rellenar huecos.
        """
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT numero_inventario FROM {cls.TABLE} "
                f"WHERE numero_inventario LIKE ?",
                (f"{prefijo}%",)
            )
            rows = cursor.fetchall()
            cursor.close()

            tres_digitos  = []
            cuatro_digitos = []

            for row in rows:
                sufijo = row[0][len(prefijo):]
                if not sufijo.isdigit():
                    continue
                n      = int(sufijo)
                digits = len(sufijo)
                if digits == 3:
                    tres_digitos.append(n)
                elif digits == 4:
                    cuatro_digitos.append(n)

            # Si aún no se agotaron los de 3 dígitos
            if not tres_digitos or max(tres_digitos) < 999:
                siguiente = (max(tres_digitos) + 1) if tres_digitos else 1
                return f"{prefijo}{str(siguiente).zfill(3)}"
            else:
                # Ya llegamos a 999, pasamos a 4 dígitos
                siguiente = (max(cuatro_digitos) + 1) if cuatro_digitos else 1
                return f"{prefijo}{str(siguiente).zfill(4)}"

        except Exception as e:
            print(f"Error generar_numero_inventario [{prefijo}]: {e}")
            return None

    @classmethod
    def crear(cls, db, datos):
        """
        INSERT de equipo nuevo.
        datos = dict con todos los campos del formulario agregar_equipo.
        Devuelve el equipo_id recién creado, o None si falla.
        """
        fechas = ('fecha_adquisicion', 'fecha_fabricacion', 'fecha_fin_garantia')
        for f in fechas:
            if datos.get(f) == '':
                datos[f] = None

        try:
            cursor = db.cursor()
            cursor.execute(f"""
                INSERT INTO {cls.TABLE} (
                    equipo_unidad, marca, modelo, numero_serie,
                    numero_inventario, area, departamento, estado,
                    propiedad, observaciones, fecha_adquisicion,
                    fecha_fabricacion, fecha_fin_garantia, imagen
                )
                OUTPUT INSERTED.id
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datos.get('equipo_unidad'),
                datos.get('marca'),
                datos.get('modelo'),
                datos.get('numero_serie'),
                datos.get('numero_inventario'),
                datos.get('area'),
                datos.get('departamento'),
                datos.get('estado'),
                datos.get('propiedad'),
                datos.get('observaciones'),
                datos.get('fecha_adquisicion'),
                datos.get('fecha_fabricacion'),
                datos.get('fecha_fin_garantia'),
                datos.get('imagen')
            ))
            equipo_id = cursor.fetchone()[0]
            db.commit()
            cursor.close()
            return equipo_id

        except Exception as e:
            print(f"Error crear equipo: {e}")
            db.rollback()
            return None

    @classmethod
    def actualizar(cls, db, id, datos):
        fechas = ('fecha_adquisicion', 'fecha_fabricacion', 'fecha_fin_garantia')
        for f in fechas:
            if datos.get(f) == '':
                datos[f] = None

        try:
            cursor = db.cursor()
            cursor.execute(f"""
                UPDATE {cls.TABLE} SET
                    equipo_unidad      = ?,
                    marca              = ?,
                    modelo             = ?,
                    numero_serie       = ?,
                    numero_inventario  = ?,
                    area               = ?,
                    departamento       = ?,
                    estado             = ?,
                    propiedad          = ?,
                    observaciones      = ?,
                    fecha_adquisicion  = ?,
                    fecha_fabricacion  = ?,
                    fecha_fin_garantia = ?
                WHERE id = ?
            """, (
                datos.get('equipo_unidad'),
                datos.get('marca'),
                datos.get('modelo'),
                datos.get('numero_serie'),
                datos.get('numero_inventario'),
                datos.get('area'),
                datos.get('departamento'),
                datos.get('estado'),
                datos.get('propiedad'),
                datos.get('observaciones'),
                datos.get('fecha_adquisicion'),
                datos.get('fecha_fabricacion'),
                datos.get('fecha_fin_garantia'),
                id
            ))
            db.commit()
            cursor.close()
            return True
        except Exception as e:
            print(f"Error actualizar [{id}]: {e}")
            db.rollback()
            return False

    @classmethod
    def eliminar(cls, db, id):
        """
        TODO: DELETE del equipo.
        Llamar DESPUÉS de eliminar archivo de imagen físico.
        """
        raise NotImplementedError

    @classmethod
    def actualizar_imagen(cls, db, id, filename):
        try:
            cursor = db.cursor()

            # Obtener marca y modelo del equipo actual
            cursor.execute(f"SELECT marca, modelo FROM {cls.TABLE} WHERE id = ?", (id,))
            row = cursor.fetchone()
            if not row:
                return False
            marca, modelo = row

            # Actualizar todos los equipos con la misma marca y modelo
            cursor.execute(
                f"UPDATE {cls.TABLE} SET imagen = ? WHERE marca = ? AND modelo = ?",
                (filename, marca, modelo)
            )
            db.commit()
            cursor.close()
            return True
        except Exception as e:
            print(f"Error actualizar_imagen [{id}]: {e}")
            db.rollback()
            return False
        
    @classmethod
    def guardar_imagen(cls, imagen_file, flag='equipos', max_size_mb=2,
                    allowed_extensions=None, output_size=(800, 800)):
        if allowed_extensions is None:
            allowed_extensions = ['.jpg', '.jpeg', '.png', '.webp']

        if not imagen_file:
            raise ValueError("No se proporcionó ninguna imagen")

        # Validar tamaño
        imagen_file.seek(0, 2)          # ir al final
        size = imagen_file.tell()
        imagen_file.seek(0)             # resetear
        if size > max_size_mb * 1024 * 1024:
            raise ValueError(f"El archivo excede {max_size_mb}MB")

        # Validar extensión
        file_ext = os.path.splitext(imagen_file.filename)[1].lower()
        if file_ext not in allowed_extensions:
            raise ValueError(f"Extensión no permitida. Use: {', '.join(allowed_extensions)}")

        # Validar que sea imagen real
        try:
            img = Image.open(imagen_file)
            img.verify()
            imagen_file.seek(0)
            img = Image.open(imagen_file)
        except Exception:
            raise ValueError("El archivo no es una imagen válida")

        # Nombre único
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_id = uuid.uuid4().hex[:8]
        filename  = secure_filename(f"{timestamp}_{unique_id}.jpg")

        # Ruta destino: static/uploads/equipos/
        base_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'static', 'uploads', flag)
        )
        os.makedirs(base_path, exist_ok=True)
        filepath = os.path.join(base_path, filename)

        # Procesar y guardar
        try:
            if img.mode in ('RGBA', 'LA'):
                bg = Image.new('RGB', img.size, 'white')
                bg.paste(img, mask=img.split()[-1])
                img = bg
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            img.thumbnail(output_size, Image.Resampling.LANCZOS)
            img.save(filepath, 'JPEG', quality=85, optimize=True)

            # Devuelve la ruta relativa para guardar en BD
            return os.path.join(flag, filename).replace('\\', '/')

        except Exception as e:
            if os.path.exists(filepath):
                os.remove(filepath)
            raise ValueError(f"Error al procesar la imagen: {e}")

@classmethod
def eliminar_archivo_fisico(cls, ruta_relativa):
    """
    Borra una imagen física del disco.
    ruta_relativa viene de la columna 'imagen' en la BD.
    Ej: 'equipos/20250401_abc123.jpg'
    """
    if not ruta_relativa:
        return
    try:
        path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'static', 'uploads', ruta_relativa)
        )
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        print(f"Error eliminar_archivo_fisico [{ruta_relativa}]: {e}")