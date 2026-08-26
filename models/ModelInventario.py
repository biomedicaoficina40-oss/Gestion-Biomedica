import os
import uuid
from datetime import datetime
from PIL import Image
from werkzeug.utils import secure_filename
import io

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

    # Prioridad de estado: Operativo primero, Fuera de Servicio al final.
    # Cualquier estado desconocido/vacío cae después de los tres conocidos.
    ORDEN_ESTADO = """
        CASE estado
            WHEN 'Operativo'         THEN 0
            WHEN 'Mantenimiento'     THEN 1
            WHEN 'Fuera de Servicio' THEN 2
            ELSE 3
        END
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
                       page=1, per_page=15, agrupar_estado=True):
        """
        Lista paginada con búsqueda, filtros y ordenamiento.

        agrupar_estado=True (default) antepone SIEMPRE el orden por estado:
        Operativo → Mantenimiento → Fuera de Servicio, y dentro de cada grupo
        se aplica el 'sort' elegido por el usuario. Aplica igual en búsquedas
        y filtros. Con agrupar_estado=False se respeta solo el 'sort'.

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

        dir_sql = "ASC" if direction.lower() == "asc" else "DESC"
        prio    = " ".join(cls.ORDEN_ESTADO.split())

        # Criterios en orden: [grupo estado] → [columna elegida] → desempate.
        criterios = []

        if sort == 'estado':
            # Ordenar por estado = ordenar por prioridad (no alfabéticamente).
            criterios.append(f"{prio} {dir_sql}")
        else:
            if agrupar_estado:
                criterios.append(f"{prio} ASC")
            if sort in SORTABLE:
                criterios.append(f"{sort} {dir_sql}")

        # numero_inventario siempre al final: desempate estable para paginar.
        if sort != 'numero_inventario':
            criterios.append("numero_inventario ASC")

        order_sql = "ORDER BY " + ", ".join(criterios)

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
    def get_equipos_nfc(cls, db):
        """
        Equipos con chip NFC (tiene_nfc = 1) junto con su checklist de
        información: imagen, guía rápida, manual, ficha técnica,
        capacitación y registro de mantenimiento.

        Usado por el Panel NFC (admin.panel_nfc) — el panel de control
        para saber qué equipos con chip ya tienen su información cargada
        y cuáles faltan, con enlaces directos para completarla.

        Devuelve una lista de dicts, cada uno con las columnas base del
        equipo más:
            tiene_imagen, tiene_guia, tiene_manual, tiene_ficha,
            tiene_capacitacion  (bool)
            mant_id                (int|None — existe registro de mantenimiento)
            proximo_mantenimiento  (date|None)
            estado_mant            ('al_dia'|'proximo'|'vencido'|'sin_registro')
            items_completos, total_items  (int) — para el resumen de completitud
        """
        query = """
            SELECT
                e.id, e.equipo_unidad, e.marca, e.modelo, e.numero_serie,
                e.numero_inventario, e.departamento, e.area, e.estado, e.imagen,
                m.id AS mant_id, m.proximo_mantenimiento,
                CASE WHEN EXISTS (
                    SELECT 1 FROM HospitalGalenia.dbo.EquipoRecursos er
                    INNER JOIN HospitalGalenia.dbo.Recursos r ON r.id = er.recurso_id
                    WHERE er.equipo_id = e.id AND r.categoria = 'guia_rapida'
                ) THEN 1 ELSE 0 END AS tiene_guia,
                CASE WHEN EXISTS (
                    SELECT 1 FROM HospitalGalenia.dbo.EquipoRecursos er
                    INNER JOIN HospitalGalenia.dbo.Recursos r ON r.id = er.recurso_id
                    WHERE er.equipo_id = e.id
                      AND r.categoria IN ('manual_servicio', 'manual_usuario')
                ) THEN 1 ELSE 0 END AS tiene_manual,
                CASE WHEN EXISTS (
                    SELECT 1 FROM HospitalGalenia.dbo.EquipoRecursos er
                    INNER JOIN HospitalGalenia.dbo.Recursos r ON r.id = er.recurso_id
                    WHERE er.equipo_id = e.id AND r.categoria = 'ficha_tecnica'
                ) THEN 1 ELSE 0 END AS tiene_ficha,
                CASE WHEN EXISTS (
                    SELECT 1 FROM HospitalGalenia.dbo.EquipoRecursos er
                    INNER JOIN HospitalGalenia.dbo.Recursos r ON r.id = er.recurso_id
                    WHERE er.equipo_id = e.id AND r.categoria = 'capacitacion'
                ) THEN 1 ELSE 0 END AS tiene_capacitacion
            FROM HospitalGalenia.dbo.InventarioEquipos e
            LEFT JOIN HospitalGalenia.dbo.MantenimientosEquipos m ON m.equipo_id = e.id
            WHERE e.tiene_nfc = 1
            ORDER BY e.numero_inventario ASC
        """
        try:
            cursor = db.cursor()
            cursor.execute(query)
            rows    = cursor.fetchall()
            columns = [col[0] for col in cursor.description]
            cursor.close()
        except Exception as e:
            print(f"Error get_equipos_nfc: {e}")
            return []

        hoy      = datetime.now().date()
        equipos  = []
        for row in rows:
            eq = dict(zip(columns, row))

            eq['tiene_imagen'] = bool(eq.get('imagen'))
            for k in ('tiene_guia', 'tiene_manual', 'tiene_ficha', 'tiene_capacitacion'):
                eq[k] = bool(eq.get(k))

            # Estado de mantenimiento — misma escala que ModelMantenimientos
            proximo = eq.get('proximo_mantenimiento')
            if proximo is None:
                eq['estado_mant'] = 'sin_registro'
            else:
                p = proximo.date() if isinstance(proximo, datetime) else proximo
                delta = (p - hoy).days
                eq['estado_mant'] = 'vencido' if delta < 0 else ('proximo' if delta <= 30 else 'al_dia')

            for k, v in eq.items():
                if v is None:
                    eq[k] = ''

            checklist = (
                eq['tiene_imagen'], eq['tiene_guia'], eq['tiene_manual'],
                eq['tiene_ficha'], eq['tiene_capacitacion'],
                eq['estado_mant'] != 'sin_registro',
            )
            eq['items_completos'] = sum(checklist)
            eq['total_items']     = len(checklist)

            equipos.append(eq)

        return equipos

    @classmethod
    def get_marcas(cls, db):
        return cls._distinct(db, 'marca')

    @classmethod
    def get_departamentos(cls, db):
        return cls._distinct(db, 'departamento')
    @classmethod
    def get_areas(cls, db):
        return cls._distinct(db, 'area')

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
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT numero_inventario FROM {cls.TABLE} "
                f"WHERE numero_inventario LIKE ?",
                (f"{prefijo}%",)
            )
            rows = cursor.fetchall()
            cursor.close()

            numeros = []
            for row in rows:
                sufijo = row[0][len(prefijo):]
                if sufijo.isdigit():
                    numeros.append(int(sufijo))

            siguiente = (max(numeros) + 1) if numeros else 1
            digits = 4 if prefijo == 'EQ-ME' else 3
            return f"{prefijo}{str(siguiente).zfill(digits)}"

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

            # Obtener modelo del equipo actual
            cursor.execute(f"SELECT modelo FROM {cls.TABLE} WHERE id = ?", (id,))
            row = cursor.fetchone()
            if not row:
                return False
            modelo = row[0]

            # Sin modelo no hay grupo al que propagar: solo este equipo.
            if modelo and modelo.strip():
                cursor.execute(
                    f"UPDATE {cls.TABLE} SET imagen = ? WHERE modelo = ?",
                    (filename, modelo)
                )
            else:
                cursor.execute(
                    f"UPDATE {cls.TABLE} SET imagen = ? WHERE id = ?",
                    (filename, id)
                )
            db.commit()
            cursor.close()
            return True
        except Exception as e:
            print(f"Error actualizar_imagen [{id}]: {e}")
            db.rollback()
            return False

    @classmethod
    def buscar_imagen_por_modelo(cls, db, modelo):
        """
        Busca una imagen ya existente entre equipos con el mismo modelo.
        Se usa al dar de alta un equipo nuevo para no pedir resubir la
        imagen si ya hay una registrada para ese modelo.
        Devuelve la ruta relativa (columna 'imagen') o None.
        """
        if not modelo or not modelo.strip():
            return None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT TOP 1 imagen FROM {cls.TABLE} "
                f"WHERE modelo = ? AND imagen IS NOT NULL AND imagen <> '' "
                f"ORDER BY id",
                (modelo,)
            )
            row = cursor.fetchone()
            cursor.close()
            return row[0] if row else None
        except Exception as e:
            print(f"Error buscar_imagen_por_modelo [{modelo}]: {e}")
            return None
        
    @classmethod
    def guardar_imagen(cls, imagen_file, flag='equipos', max_size_mb=2,
                    allowed_extensions=None, output_size=(800, 800),
                    quality_inicial=85, calidad_minima=40):
        """
        Guarda y comprime una imagen automáticamente.
        
        - Comprime primero, valida después (ya no falla por fotos de celular).
        - Reduce calidad iterativamente si el resultado aún excede max_size_mb.
        - quality_inicial: calidad JPEG de inicio (85 es buen balance).
        - calidad_minima: piso de calidad antes de levantar error real.
        """
        if allowed_extensions is None:
            allowed_extensions = ['.jpg', '.jpeg', '.png', '.webp']

        if not imagen_file:
            raise ValueError("No se proporcionó ninguna imagen")

        # ── 1. Validar extensión (rápido, antes de leer el archivo) ──────────
        file_ext = os.path.splitext(imagen_file.filename)[1].lower()
        if file_ext not in allowed_extensions:
            raise ValueError(f"Extensión no permitida. Use: {', '.join(allowed_extensions)}")

        # ── 2. Validar que sea imagen real ───────────────────────────────────
        try:
            img = Image.open(imagen_file)
            img.verify()
            imagen_file.seek(0)
            img = Image.open(imagen_file)
        except Exception:
            raise ValueError("El archivo no es una imagen válida")

        # ── 3. Preparar imagen (conversión de modo, redimensionado) ──────────
        if img.mode in ('RGBA', 'LA'):
            bg = Image.new('RGB', img.size, 'white')
            bg.paste(img, mask=img.split()[-1])
            img = bg
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # Redimensionar solo si excede output_size (preserva proporción)
        img.thumbnail(output_size, Image.Resampling.LANCZOS)

        # ── 4. Comprimir iterativamente hasta cumplir el límite ──────────────
        max_bytes = max_size_mb * 1024 * 1024
        quality = quality_inicial
        buffer = io.BytesIO()

        while quality >= calidad_minima:
            buffer.seek(0)
            buffer.truncate()
            img.save(buffer, 'JPEG', quality=quality, optimize=True)
            if buffer.tell() <= max_bytes:
                break
            quality -= 10
        else:
            # Si con calidad mínima sigue siendo demasiado grande,
            # reducir también las dimensiones a la mitad y reintentar una vez
            img = img.resize(
                (img.width // 2, img.height // 2),
                Image.Resampling.LANCZOS
            )
            buffer.seek(0)
            buffer.truncate()
            img.save(buffer, 'JPEG', quality=calidad_minima, optimize=True)
            if buffer.tell() > max_bytes:
                raise ValueError(
                    f"La imagen no pudo comprimirse por debajo de {max_size_mb}MB. "
                    "Use una imagen con menos detalle o menor resolución."
                )

        # ── 5. Guardar a disco ───────────────────────────────────────────────
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_id = uuid.uuid4().hex[:8]
        filename  = secure_filename(f"{timestamp}_{unique_id}.jpg")

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
            raise ValueError(f"Error al guardar la imagen: {e}")

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