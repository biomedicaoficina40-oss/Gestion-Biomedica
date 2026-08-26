"""
Detalle de los reportes de entrada y salida de equipo.

Los dos comparten tabla (`RepMovimiento`) y se distinguen por `sentido`: es
literalmente "un solo formato con selector Entrada/Salida", así que separar el
modelo en dos clases solo duplicaría cada consulta.

A diferencia del mantenimiento, un movimiento casi siempre es de un equipo
pero a veces es en masa (un lote que sale completo a servicio externo, por
ejemplo). `Reportes.equipo_id` sigue apuntando al primero de la lista —así
todo el código que ya asume un equipo por reporte (listado, ficha, dashboard)
sigue funcionando sin tocarlo—; `ReporteEquipos` es la lista completa.
"""

from flask import current_app

ENTRADA = 'E'
SALIDA = 'S'
SENTIDOS = (ENTRADA, SALIDA)

ETIQUETAS_SENTIDO = {
    ENTRADA: 'Entrada',
    SALIDA:  'Salida',
}

# Sentido que le corresponde a cada tipo de reporte — el mismo mapeo que usa
# ModelFolios.SERIE_POR_TIPO, pero en el otro sentido (perdón el juego de
# palabras): de tipo de Reportes a la columna `sentido` de RepMovimiento.
SENTIDO_POR_TIPO = {
    'entrada': ENTRADA,
    'salida':  SALIDA,
}

MAX_TEXTO = 4000
MAX_EQUIPOS = 60   # un lote real no pasa de unas cuantas decenas


class ModelMovimiento:
    TABLE = "HospitalGalenia.dbo.RepMovimiento"
    TABLA_EQUIPOS = "HospitalGalenia.dbo.ReporteEquipos"

    # ── Ciclo de vida del detalle ────────────────────────────────

    @classmethod
    def crear(cls, db, reporte_id, sentido, movimiento_padre_id=None):
        """
        Crea el detalle vacío al abrir el reporte. Ver ModelMantenimiento.crear:
        misma razón para hacerlo de inmediato y no al primer guardado.
        """
        if sentido not in SENTIDOS:
            return False
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"INSERT INTO {cls.TABLE} (reporte_id, sentido, movimiento_padre_id) "
                f"VALUES (?, ?, ?)",
                (reporte_id, sentido, movimiento_padre_id))
            db.commit()
            return True
        except Exception as e:
            current_app.logger.error(
                f"[ModelMovimiento.crear] reporte={reporte_id} | {e}")
            try:
                db.rollback()
            except Exception:
                pass
            return False
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def get(cls, db, reporte_id):
        """
        Detalle de un movimiento, con el proveedor y el folio del padre ya
        resueltos a texto — igual que ModelMantenimiento.get resuelve los
        catálogos de falla: para que ni la pantalla ni el PDF necesiten una
        segunda consulta.
        """
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                "SELECT m.reporte_id, m.sentido, m.motivo, m.accesorios, "
                "       m.destino_externo, m.proveedor_id, "
                "       m.fecha_retorno_prevista, m.fecha_retorno_real, "
                "       m.movimiento_padre_id, "
                "       p.nombre AS proveedor_nombre, "
                "       padre.folio AS padre_folio "
                "FROM HospitalGalenia.dbo.RepMovimiento m "
                "LEFT JOIN HospitalGalenia.dbo.Cat_Proveedores p ON p.id = m.proveedor_id "
                "LEFT JOIN HospitalGalenia.dbo.Reportes padre "
                "       ON padre.id = m.movimiento_padre_id "
                "WHERE m.reporte_id = ?",
                (reporte_id,))
            fila = cursor.fetchone()
            if not fila:
                return None
            columnas = [c[0] for c in cursor.description]
            detalle = dict(zip(columnas, fila))
            detalle['sentido_txt'] = ETIQUETAS_SENTIDO.get(detalle.get('sentido'))
            return detalle
        except Exception as e:
            current_app.logger.error(
                f"[ModelMovimiento.get] reporte={reporte_id} | {e}")
            return None
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def guardar(cls, db, reporte_id, **campos):
        """UPDATE parcial — mismo patrón que ModelMantenimiento.guardar."""
        permitidos = {
            'motivo':                 str,
            'accesorios':             str,
            'destino_externo':        str,
            'proveedor_id':           int,
            'fecha_retorno_prevista': None,
            'fecha_retorno_real':     None,
            'movimiento_padre_id':    int,
        }

        asignaciones, valores = [], []
        for campo, tipo in permitidos.items():
            if campo not in campos:
                continue
            valor = campos[campo]
            if tipo is str and valor is not None:
                valor = str(valor).strip()[:MAX_TEXTO] or None
            elif tipo is int:
                valor = int(valor) if valor not in (None, '', '0') else None
            asignaciones.append(f"{campo} = ?")
            valores.append(valor)

        if not asignaciones:
            return True

        cursor = None
        try:
            cursor = db.cursor()
            valores.append(reporte_id)
            cursor.execute(
                f"UPDATE {cls.TABLE} SET {', '.join(asignaciones)} WHERE reporte_id = ?",
                tuple(valores))
            db.commit()
            return True
        except Exception as e:
            current_app.logger.error(
                f"[ModelMovimiento.guardar] reporte={reporte_id} | {e}")
            try:
                db.rollback()
            except Exception:
                pass
            return False
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def get_catalogos(cls, db):
        """Proveedores, áreas y técnicos activos — mismo shape que el de mantenimiento."""
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                "SELECT id, nombre FROM HospitalGalenia.dbo.Cat_Proveedores "
                "WHERE activo = 1 ORDER BY nombre")
            proveedores = [{'id': f[0], 'nombre': f[1]} for f in cursor.fetchall()]

            cursor.execute(
                "SELECT id, nombre FROM HospitalGalenia.dbo.Cat_Areas "
                "WHERE activa = 1 ORDER BY nombre")
            areas = [{'id': f[0], 'nombre': f[1]} for f in cursor.fetchall()]

            cursor.execute(
                "SELECT id, nombre FROM HospitalGalenia.dbo.Cat_Tecnicos "
                "WHERE activo = 1 ORDER BY nombre")
            tecnicos = [{'id': f[0], 'nombre': f[1]} for f in cursor.fetchall()]

            return {'proveedores': proveedores, 'areas': areas, 'tecnicos': tecnicos}
        except Exception as e:
            current_app.logger.error(f"[ModelMovimiento.get_catalogos] {e}")
            return {'proveedores': [], 'areas': [], 'tecnicos': []}
        finally:
            if cursor:
                cursor.close()

    # ── Equipos del movimiento (uno o varios) ────────────────────

    @classmethod
    def get_equipos(cls, db, reporte_id):
        """Equipos del movimiento, en el orden en que se agregaron."""
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                "SELECT re.id AS vinculo_id, e.id, e.equipo_unidad, e.marca, "
                "       e.modelo, e.numero_serie, e.numero_inventario, e.area, "
                "       e.imagen "
                "FROM HospitalGalenia.dbo.ReporteEquipos re "
                "JOIN HospitalGalenia.dbo.InventarioEquipos e ON e.id = re.equipo_id "
                "WHERE re.reporte_id = ? ORDER BY re.orden, re.id",
                (reporte_id,))
            columnas = [c[0] for c in cursor.description]
            return [dict(zip(columnas, f)) for f in cursor.fetchall()]
        except Exception as e:
            current_app.logger.error(
                f"[ModelMovimiento.get_equipos] reporte={reporte_id} | {e}")
            return []
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def agregar_equipo(cls, db, reporte_id, equipo_id):
        """
        Agrega un equipo al movimiento. Devuelve (ok, mensaje_o_None).

        Ignora en silencio si ya estaba (UNIQUE(reporte_id, equipo_id)): que
        alguien lo busque y lo toque dos veces no debe duplicar el renglón ni
        reportarse como error.
        """
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT COUNT(*) FROM {cls.TABLA_EQUIPOS} WHERE reporte_id = ?",
                (reporte_id,))
            total = cursor.fetchone()[0]
            if total >= MAX_EQUIPOS:
                return False, f"Máximo {MAX_EQUIPOS} equipos por movimiento"

            cursor.execute(
                f"SELECT 1 FROM {cls.TABLA_EQUIPOS} WHERE reporte_id = ? AND equipo_id = ?",
                (reporte_id, equipo_id))
            if cursor.fetchone():
                return True, None

            cursor.execute(
                f"INSERT INTO {cls.TABLA_EQUIPOS} (reporte_id, equipo_id, orden) "
                f"VALUES (?, ?, ?)",
                (reporte_id, equipo_id, total))
            db.commit()
            cls._sincronizar_equipo_principal(db, reporte_id)
            return True, None
        except Exception as e:
            current_app.logger.error(
                f"[ModelMovimiento.agregar_equipo] reporte={reporte_id} equipo={equipo_id} | {e}")
            try:
                db.rollback()
            except Exception:
                pass
            return False, "No se pudo agregar el equipo"
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def quitar_equipo(cls, db, reporte_id, equipo_id):
        """
        Quita un equipo del movimiento. No deja el reporte sin ninguno: un
        movimiento sin equipos no documenta nada, así que el último no se
        puede quitar (hay que cancelar el reporte en su lugar).
        """
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT COUNT(*) FROM {cls.TABLA_EQUIPOS} WHERE reporte_id = ?",
                (reporte_id,))
            if cursor.fetchone()[0] <= 1:
                return False, "Debe quedar al menos un equipo"

            cursor.execute(
                f"DELETE FROM {cls.TABLA_EQUIPOS} WHERE reporte_id = ? AND equipo_id = ?",
                (reporte_id, equipo_id))
            db.commit()
            cls._sincronizar_equipo_principal(db, reporte_id)
            return True, None
        except Exception as e:
            current_app.logger.error(
                f"[ModelMovimiento.quitar_equipo] reporte={reporte_id} equipo={equipo_id} | {e}")
            try:
                db.rollback()
            except Exception:
                pass
            return False, "No se pudo quitar el equipo"
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def _sincronizar_equipo_principal(cls, db, reporte_id):
        """
        `Reportes.equipo_id` refleja siempre el primero de la lista.

        Es lo que deja que el listado, la ficha del equipo y el dashboard
        sigan funcionando sin saber que un movimiento puede tener más de uno:
        para ellos, este reporte "es de" ese equipo, igual que un preventivo.
        """
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT TOP 1 equipo_id FROM {cls.TABLA_EQUIPOS} "
                f"WHERE reporte_id = ? ORDER BY orden, id",
                (reporte_id,))
            fila = cursor.fetchone()
            cursor.execute(
                "UPDATE HospitalGalenia.dbo.Reportes SET equipo_id = ? WHERE id = ?",
                (fila[0] if fila else None, reporte_id))
            db.commit()
        except Exception as e:
            current_app.logger.error(
                f"[ModelMovimiento._sincronizar_equipo_principal] reporte={reporte_id} | {e}")
            try:
                db.rollback()
            except Exception:
                pass
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def cerrar_salida(cls, db, salida_id, fecha_retorno=None):
        """
        Marca el retorno de una salida, cuando una entrada la referencia como
        padre. Ver `salidas_sin_retorno`: lo que de verdad la cierra para esa
        consulta es que exista la entrada con `movimiento_padre_id` apuntando
        aquí; esto solo deja la fecha de retorno real como dato consultable en
        el propio expediente de la salida, en vez de quedar en NULL para
        siempre aunque ya haya vuelto.
        """
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"UPDATE {cls.TABLE} SET fecha_retorno_real = ISNULL(?, GETDATE()) "
                f"WHERE reporte_id = ? AND fecha_retorno_real IS NULL",
                (fecha_retorno, salida_id))
            db.commit()
        except Exception as e:
            current_app.logger.error(
                f"[ModelMovimiento.cerrar_salida] salida={salida_id} | {e}")
            try:
                db.rollback()
            except Exception:
                pass
        finally:
            if cursor:
                cursor.close()

    # ── Qué está fuera ────────────────────────────────────────────

    @classmethod
    def salidas_sin_retorno(cls, db, equipo_id=None, limite=None):
        """
        Salidas que ningún movimiento posterior cerró (`movimiento_padre_id`).

        Es la pregunta "¿qué está fuera del hospital ahora mismo?" — y es la
        que evita que la localización BLE reporte como "no encontrado" un
        equipo cuya ausencia ya está documentada. Ese enganche con BLE no se
        construyó todavía; esta consulta es lo que lo haría posible.

        Con un lote (varias salidas del mismo movimiento_padre_id) esto
        contesta a nivel de REPORTE completo, no equipo por equipo: si tres
        equipos salen juntos y solo dos regresan, hace falta una segunda
        entrada para el resto — la primera salida seguiría "sin retorno"
        hasta que exista una entrada que la referencie, aunque dos de los tres
        equipos ya estén de vuelta. Documentado así a propósito: resolver el
        retorno parcial pieza por pieza no se pidió y complica el esquema sin
        necesidad hoy.
        """
        where = ["m.sentido = 'S'",
                "NOT EXISTS (SELECT 1 FROM HospitalGalenia.dbo.RepMovimiento h "
                "            WHERE h.movimiento_padre_id = m.reporte_id)"]
        params = []
        if equipo_id:
            where.append(
                "EXISTS (SELECT 1 FROM HospitalGalenia.dbo.ReporteEquipos re "
                "        WHERE re.reporte_id = m.reporte_id AND re.equipo_id = ?)")
            params.append(equipo_id)

        tope = f"TOP {int(limite)} " if limite else ""
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"SELECT {tope}r.id, r.folio, r.fecha, r.fecha_apertura, "
                f"       m.motivo, m.destino_externo, m.fecha_retorno_prevista "
                f"FROM HospitalGalenia.dbo.RepMovimiento m "
                f"JOIN HospitalGalenia.dbo.Reportes r ON r.id = m.reporte_id "
                f"WHERE {' AND '.join(where)} "
                f"ORDER BY r.fecha_apertura DESC",
                tuple(params))
            columnas = [c[0] for c in cursor.description]
            salidas = [dict(zip(columnas, f)) for f in cursor.fetchall()]
            for salida in salidas:
                salida['equipos'] = cls.get_equipos(db, salida['id'])
            return salidas
        except Exception as e:
            current_app.logger.error(f"[ModelMovimiento.salidas_sin_retorno] {e}")
            return []
        finally:
            if cursor:
                cursor.close()
