from datetime import date, datetime


class ModelMantenimientos:
    """
    Modelo para el módulo provisional de mantenimientos de equipos.
    Un registro por equipo (UNIQUE equipo_id).
    El estado se calcula en tiempo real, no se persiste en BD.
    """

    # Misma escala que _calcular_estado, pero en SQL — para poder filtrar
    # y paginar en la base de datos en vez de traer todo el inventario y
    # filtrar en Python (eso fue lo que hacía lenta la carga del dashboard
    # con las 500+ filas de InventarioEquipos).
    ESTADO_MANT_SQL = """
        CASE
            WHEN m.proximo_mantenimiento IS NULL THEN 'sin_registro'
            WHEN CAST(m.proximo_mantenimiento AS DATE) < CAST(GETDATE() AS DATE) THEN 'vencido'
            WHEN DATEDIFF(DAY, CAST(GETDATE() AS DATE), CAST(m.proximo_mantenimiento AS DATE)) <= 30 THEN 'proximo'
            ELSE 'al_dia'
        END
    """

    # ── Utilidades internas ────────────────────────────────────────────────

    @staticmethod
    def _calcular_estado(proximo_mantenimiento):
        """
        Calcula el estado del mantenimiento en base a la fecha próxima.
        Retorna: 'vencido' | 'proximo' | 'al_dia' | 'sin_registro'
        """
        if proximo_mantenimiento is None:
            return 'sin_registro'

        # Aceptar tanto date como datetime
        if isinstance(proximo_mantenimiento, datetime):
            proximo = proximo_mantenimiento.date()
        else:
            proximo = proximo_mantenimiento

        delta = (proximo - date.today()).days

        if delta < 0:
            return 'vencido'
        elif delta <= 30:
            return 'proximo'
        else:
            return 'al_dia'

    @staticmethod
    def _row_to_dict(cursor, row):
        """Convierte una fila del cursor a dict, reemplazando None por ''."""
        if row is None:
            return None
        columns = [col[0] for col in cursor.description]
        result  = dict(zip(columns, row))
        for key, value in result.items():
            if value is None:
                result[key] = ''
        return result

    @staticmethod
    def _enriquecer(mant):
        """
        Agrega campos calculados al dict de mantenimiento.
        - estado: al_dia / proximo / vencido / sin_registro
        - dias_para_vencer: int (negativo si ya venció)
        """
        if mant is None:
            return None

        proximo = mant.get('proximo_mantenimiento') or None
        mant['estado'] = ModelMantenimientos._calcular_estado(proximo)

        if proximo and isinstance(proximo, (date, datetime)):
            p = proximo.date() if isinstance(proximo, datetime) else proximo
            mant['dias_para_vencer'] = (p - date.today()).days
        else:
            mant['dias_para_vencer'] = None

        return mant

    # ── Lectura ────────────────────────────────────────────────────────────

    @classmethod
    def obtener_por_equipo(cls, db, equipo_id):
        """
        Obtiene el registro de mantenimiento de un equipo.
        Retorna dict enriquecido con 'estado' y 'dias_para_vencer', o None.
        Usado en: DetalleEquipo (tarjeta de mantenimiento)
        """
        query = """
            SELECT
                m.id,
                m.equipo_id,
                m.tipo_mantenimiento,
                m.frecuencia_meses,
                m.ultimo_mantenimiento,
                m.proximo_mantenimiento,
                m.responsable,
                m.notas,
                m.creado_en,
                m.actualizado_en
            FROM HospitalGalenia.dbo.MantenimientosEquipos m
            WHERE m.equipo_id = ?
        """
        try:
            cursor = db.cursor()
            cursor.execute(query, (equipo_id,))
            row  = cursor.fetchone()
            mant = cls._row_to_dict(cursor, row)
            cursor.close()
            return cls._enriquecer(mant)

        except Exception as e:
            print(f"Error obtener_por_equipo [{equipo_id}]: {e}")
            return None

    @classmethod
    def obtener_todos(cls, db, filtro_estado=None, filtro_departamento=None,
                       page=1, per_page=15):
        """
        Lista paginada de equipos con su estado de mantenimiento.
        Incluye equipos SIN registro (LEFT JOIN) para el dashboard completo.

        Filtra y pagina en SQL (antes traía las ~530 filas de
        InventarioEquipos completas en cada carga y filtraba en Python,
        lo que hacía pesada la página frente al resto del sitio, que sí
        pagina).

        Parámetros opcionales:
            filtro_estado:       'al_dia' | 'proximo' | 'vencido' | 'sin_registro'
            filtro_departamento: string del departamento
        Usado en: Dashboard de mantenimientos
        Devuelve (lista_equipos, total_registros).
        """
        base = """
            FROM HospitalGalenia.dbo.InventarioEquipos e
            LEFT JOIN HospitalGalenia.dbo.MantenimientosEquipos m
                ON e.id = m.equipo_id
            WHERE 1 = 1
        """
        params = []

        if filtro_departamento:
            base   += " AND e.departamento = ?"
            params.append(filtro_departamento)

        if filtro_estado:
            base   += f" AND {cls.ESTADO_MANT_SQL} = ?"
            params.append(filtro_estado)

        try:
            cursor = db.cursor()

            cursor.execute(f"SELECT COUNT(*) {base}", params)
            total = cursor.fetchone()[0]

            offset = (page - 1) * per_page
            cursor.execute(f"""
                SELECT
                    e.id            AS equipo_id,
                    e.equipo_unidad,
                    e.marca,
                    e.modelo,
                    e.numero_inventario,
                    e.departamento,
                    e.area,
                    e.estado        AS estado_equipo,
                    m.id            AS mant_id,
                    m.tipo_mantenimiento,
                    m.frecuencia_meses,
                    m.ultimo_mantenimiento,
                    m.proximo_mantenimiento,
                    m.responsable,
                    m.notas,
                    m.actualizado_en,
                    {cls.ESTADO_MANT_SQL} AS estado_mant
                {base}
                ORDER BY m.proximo_mantenimiento ASC, e.equipo_unidad ASC
                OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
            """, params + [offset, per_page])

            rows    = cursor.fetchall()
            columns = [col[0] for col in cursor.description]
            cursor.close()

            resultados = []
            for row in rows:
                item = dict(zip(columns, row))

                proximo = item.get('proximo_mantenimiento')
                if proximo and isinstance(proximo, (date, datetime)):
                    p = proximo.date() if isinstance(proximo, datetime) else proximo
                    item['dias_para_vencer'] = (p - date.today()).days
                else:
                    item['dias_para_vencer'] = None

                for key, val in item.items():
                    if val is None:
                        item[key] = ''

                resultados.append(item)

            return resultados, total

        except Exception as e:
            print(f"Error obtener_todos: {e}")
            return [], 0

    @classmethod
    def obtener_stats(cls, db, filtro_departamento=None):
        """
        Conteo por estado de mantenimiento — independiente del filtro de
        estado actual, para que los contadores del dashboard (los que se
        usan como filtro rápido) siempre muestren el total real de cada
        categoría y no solo lo que quedó visible tras filtrar.
        Respeta el filtro de departamento si se pasa.
        """
        where = "WHERE 1 = 1"
        params = []
        if filtro_departamento:
            where  += " AND e.departamento = ?"
            params.append(filtro_departamento)

        query = f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN estado_mant = 'al_dia'       THEN 1 ELSE 0 END),
                SUM(CASE WHEN estado_mant = 'proximo'      THEN 1 ELSE 0 END),
                SUM(CASE WHEN estado_mant = 'vencido'      THEN 1 ELSE 0 END),
                SUM(CASE WHEN estado_mant = 'sin_registro' THEN 1 ELSE 0 END)
            FROM (
                SELECT {cls.ESTADO_MANT_SQL} AS estado_mant
                FROM HospitalGalenia.dbo.InventarioEquipos e
                LEFT JOIN HospitalGalenia.dbo.MantenimientosEquipos m
                    ON e.id = m.equipo_id
                {where}
            ) t
        """
        try:
            cursor = db.cursor()
            cursor.execute(query, params)
            row = cursor.fetchone()
            cursor.close()
            return {
                'total':        row[0] or 0,
                'al_dia':       row[1] or 0,
                'proximo':      row[2] or 0,
                'vencido':      row[3] or 0,
                'sin_registro': row[4] or 0,
            }
        except Exception as e:
            print(f"Error obtener_stats: {e}")
            return {'total': 0, 'al_dia': 0, 'proximo': 0, 'vencido': 0, 'sin_registro': 0}

    @classmethod
    def obtener_departamentos(cls, db):
        """
        Lista de departamentos únicos para el filtro del dashboard.
        """
        query = """
            SELECT DISTINCT departamento
            FROM HospitalGalenia.dbo.InventarioEquipos
            WHERE departamento IS NOT NULL AND departamento != ''
            ORDER BY departamento
        """
        try:
            cursor = db.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
            cursor.close()
            return [row[0] for row in rows]

        except Exception as e:
            print(f"Error obtener_departamentos: {e}")
            return []

    # ── Escritura ──────────────────────────────────────────────────────────

    @classmethod
    def guardar(cls, db, equipo_id, datos):
        """
        Inserta o actualiza (UPSERT) el registro de mantenimiento de un equipo.
        'datos' es un dict con:
            - tipo_mantenimiento
            - frecuencia_meses
            - ultimo_mantenimiento  (string 'YYYY-MM-DD' o None)
            - proximo_mantenimiento (string 'YYYY-MM-DD' o None)
            - responsable
            - notas
        Retorna True si fue exitoso, False si hubo error.
        """
        # Calcular próximo automáticamente si no se provee
        proximo = datos.get('proximo_mantenimiento') or None
        ultimo  = datos.get('ultimo_mantenimiento')  or None

        if not proximo and ultimo and datos.get('frecuencia_meses'):
            try:
                from dateutil.relativedelta import relativedelta
                fecha_ultimo = datetime.strptime(ultimo, '%Y-%m-%d').date()
                fecha_proximo = fecha_ultimo + relativedelta(
                    months=int(datos['frecuencia_meses'])
                )
                proximo = fecha_proximo.strftime('%Y-%m-%d')
            except Exception:
                proximo = None

        query = """
            MERGE HospitalGalenia.dbo.MantenimientosEquipos AS target
            USING (SELECT ? AS equipo_id) AS source
                ON target.equipo_id = source.equipo_id
            WHEN MATCHED THEN
                UPDATE SET
                    tipo_mantenimiento    = ?,
                    frecuencia_meses      = ?,
                    ultimo_mantenimiento  = ?,
                    proximo_mantenimiento = ?,
                    responsable           = ?,
                    notas                 = ?,
                    actualizado_en        = GETDATE()
            WHEN NOT MATCHED THEN
                INSERT (
                    equipo_id, tipo_mantenimiento, frecuencia_meses,
                    ultimo_mantenimiento, proximo_mantenimiento,
                    responsable, notas
                )
                VALUES (?, ?, ?, ?, ?, ?, ?);
        """
        try:
            cursor = db.cursor()
            cursor.execute(query, (
                # USING source
                equipo_id,
                # UPDATE
                datos.get('tipo_mantenimiento', 'Preventivo'),
                int(datos.get('frecuencia_meses', 6)),
                ultimo  or None,
                proximo or None,
                datos.get('responsable', '') or None,
                datos.get('notas', '')       or None,
                # INSERT
                equipo_id,
                datos.get('tipo_mantenimiento', 'Preventivo'),
                int(datos.get('frecuencia_meses', 6)),
                ultimo  or None,
                proximo or None,
                datos.get('responsable', '') or None,
                datos.get('notas', '')       or None,
            ))
            db.commit()
            cursor.close()
            return True

        except Exception as e:
            print(f"Error guardar mantenimiento [{equipo_id}]: {e}")
            db.rollback()
            return False

    @classmethod
    def eliminar(cls, db, equipo_id):
        """
        Elimina el registro de mantenimiento de un equipo.
        Usado en: editar (botón 'Limpiar registro') — opcional.
        """
        query = """
            DELETE FROM HospitalGalenia.dbo.MantenimientosEquipos
            WHERE equipo_id = ?
        """
        try:
            cursor = db.cursor()
            cursor.execute(query, (equipo_id,))
            db.commit()
            cursor.close()
            return True

        except Exception as e:
            print(f"Error eliminar mantenimiento [{equipo_id}]: {e}")
            db.rollback()
            return False