from datetime import datetime


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
    def crear(cls, db, datos):
        """
        TODO: INSERT de equipo nuevo.
        datos = dict con todos los campos del formulario agregar_equipo.
        Devuelve el id del registro creado.
        """
        raise NotImplementedError

    @classmethod
    def actualizar(cls, db, id, datos):
        """
        TODO: UPDATE de equipo existente.
        datos = dict con campos editables (los del form de ver_equipo_admin).
        """
        raise NotImplementedError

    @classmethod
    def eliminar(cls, db, id):
        """
        TODO: DELETE del equipo.
        Llamar DESPUÉS de eliminar archivo de imagen físico.
        """
        raise NotImplementedError

    @classmethod
    def actualizar_imagen(cls, db, id, filename):
        """
        TODO: UPDATE solo del campo imagen.
        filename = nombre del archivo guardado en /static/uploads/
        Pasar None para borrar la imagen.
        """
        raise NotImplementedError