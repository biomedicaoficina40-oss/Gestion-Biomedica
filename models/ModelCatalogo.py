from datetime import datetime


class ModelEquipos:
    """
    Métodos para la parte PÚBLICA del catálogo.
    Usados por el blueprint 'equipos' (vistas del personal clínico).
    """

    @classmethod
    def obtener_equipo(cls, db, numero_inventario):
        """
        Obtiene un equipo por número de inventario.
        Usado en: DetalleEquipo (vista pública)
        """
        query = """
            SELECT
            id, equipo_unidad, marca, modelo,
            numero_serie, numero_inventario, fecha_fabricacion,
            propiedad, estado, fecha_adquisicion, fecha_fin_garantia,
            departamento, imagen, observaciones, tiene_nfc
        FROM HospitalGalenia.dbo.InventarioEquipos
        WHERE numero_inventario = ?
        """
        try:
            cursor = db.cursor()
            cursor.execute(query, (numero_inventario,))
            row = cursor.fetchone()

            if row is None:
                return None

            columns = [col[0] for col in cursor.description]
            equipo  = dict(zip(columns, row))

            for key, value in equipo.items():
                if value is None:
                    equipo[key] = ''

            cursor.close()
            return equipo

        except Exception as e:
            print(f"Error obtener_equipo [{numero_inventario}]: {e}")
            return None

    @classmethod
    def buscar_equipos(cls, db, query):
        """
        Búsqueda inteligente multi-palabra. Retorna lista de dicts.
        Usado en: BuscarEquipos y Autocomplete (vista pública)
        """
        try:
            cursor = db.cursor()
            query_normalizado = cls._normalizar_texto(query)
            palabras = query_normalizado.split()

            condiciones = []
            parametros  = []
            campos = [
                'area', 'numero_inventario', 'numero_serie',
                'marca', 'modelo', 'departamento', 'equipo_unidad'
            ]

            for palabra in palabras:
                conds = []
                for campo in campos:
                    conds.append(
                        f"LOWER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE("
                        f"{campo},'á','a'),'é','e'),'í','i'),'ó','o'),'ú','u')) LIKE ?"
                    )
                    parametros.append(f"%{palabra}%")
                condiciones.append(f"({' OR '.join(conds)})")

            where = ' AND '.join(condiciones) if condiciones else "1=1"
            sql   = f"""
                SELECT numero_inventario, numero_serie, equipo_unidad,
                       marca, modelo, departamento, estado, imagen
                FROM InventarioEquipos
                WHERE {where}
                ORDER BY equipo_unidad
            """

            cursor.execute(sql, parametros)
            rows    = cursor.fetchall()
            columns = [col[0] for col in cursor.description]
            resultados = [dict(zip(columns, row)) for row in rows]

            # Fallback: OR entre palabras si no hay resultados
            if not resultados and len(palabras) > 1:
                where = ' OR '.join(condiciones)
                sql   = f"""
                    SELECT numero_inventario, numero_serie, equipo_unidad,
                           marca, modelo, departamento, estado, imagen
                    FROM InventarioEquipos
                    WHERE {where}
                    ORDER BY equipo_unidad
                """
                cursor.execute(sql, parametros)
                rows = cursor.fetchall()
                resultados = [dict(zip(columns, row)) for row in rows]

            cursor.close()
            return resultados

        except Exception as e:
            raise Exception(e)

    # ── Helpers ───────────────────────────────────────────────
    @staticmethod
    def _normalizar_texto(texto):
        if not texto:
            return ""
        reemplazos = {
            'á':'a','é':'e','í':'i','ó':'o','ú':'u',
            'Á':'a','É':'e','Í':'i','Ó':'o','Ú':'u',
            'ñ':'n','Ñ':'n'
        }
        texto = texto.lower()
        for k, v in reemplazos.items():
            texto = texto.replace(k, v)
        return ' '.join(texto.split())
    @classmethod
    def toggle_nfc(cls, db, numero_inventario):
        """
        Invierte el estado NFC del equipo (0→1, 1→0).
        Retorna el nuevo valor (True/False) o None si falla.
        """
        query = """
            UPDATE HospitalGalenia.dbo.InventarioEquipos
            SET tiene_nfc = CASE WHEN tiene_nfc = 1 THEN 0 ELSE 1 END
            WHERE numero_inventario = ?;

            SELECT tiene_nfc
            FROM HospitalGalenia.dbo.InventarioEquipos
            WHERE numero_inventario = ?;
        """
        try:
            cursor = db.cursor()
            cursor.execute(query, (numero_inventario, numero_inventario))
            cursor.nextset()           # salta al SELECT
            row = cursor.fetchone()
            db.commit()
            cursor.close()
            return bool(row[0]) if row else None
        except Exception as e:
            print(f"Error toggle_nfc [{numero_inventario}]: {e}")
            db.rollback()
            return None
        
    @classmethod
    def get_categorias(cls, db):
        """
        Agrupa equipos por tipo usando keywords.
        Solo retorna categorías con 2 o más equipos.
        Usado en: vista inicial del Catálogo.
        """
        # Definición de categorías: (label_display, keyword_sql, icono_fa)
        categorias_def = [
            ("Bomba de Infusión",           "BOMBA",                    "fa-tint"),
            ("Cama",                         "CAMA",                     "fa-bed"),
            ("Monitor",                      "MONITOR",                  "fa-heartbeat"),
            ("Camilla",                      "CAMILLA",                  "fa-ambulance"),
            ("Báscula",                      "BASCULA",                  "fa-weight"),
            ("Desfibrilador",               "DESFIBRILADOR",            "fa-bolt"),
            ("Máquina de Anestesia",        "ANESTESIA",                "fa-wind"),
            ("Lámpara Quirúrgica",          "LAMPARA QUIRURGICA",       "fa-lightbulb"),
            ("Cuna de Calor Radiante",      "CUNA DE CALOR",            "fa-fire"),
            ("Detector Signos Vitales",     "DETECTOR",                 "fa-stethoscope"),
            ("Estuche de Diagnóstico",      "ESTUCHE",                  "fa-briefcase-medical"),
            ("Mesa Quirúrgica",             "MESA QUIRURGICA",          "fa-table"),
            ("Glucómetro",                  "GLUCOMETRO",               "fa-syringe"),
            ("Sist. Inyección Contraste",   "INYECCION CONTRASTE",      "fa-project-diagram"),
            ("Ventilador",                  "VENTILADOR",               "fa-lungs"),
            ("Doppler",                     "DOPPLER",                  "fa-wave-square"),
            ("Vaporizador Sevoflurano",     "VAPORIZADOR",              "fa-flask"),
            ("Aspirador",                   "ASPIRADOR",                "fa-pump-medical"),
            ("Calentador Térmico",          "CALENTADOR",               "fa-thermometer-half"),
            ("Cuna Híbrida",               "CUNA HIBRIDA",             "fa-baby"),
            ("Electrocardiógrafo",         "ELECTROCARDIOGRAFO",       "fa-procedures"),
            ("Electrocauterio",            "ELECTROCAUTERIO",          "fa-plug"),
            ("Negatoscopio",               "NEGATOSCOPIO",             "fa-image"),
            ("Perfusor",                   "PERFUSOR",                 "fa-compress-arrows-alt"),
            ("Centrifuga",                 "CENTRIFUGA",               "fa-circle-notch"),
            ("Autoclave",                  "AUTOCLAVE",                "fa-shield-alt"),
            ("Incubadora",                 "INCUBADORA",               "fa-baby-carriage"),
            ("Ultrasonido",                "ULTRASONIDO",              "fa-satellite-dish"),
            ("Tomografía",                 "TOMOGRAFIA",               "fa-x-ray"),
            ("Tococardiógrafo",           "TOCOCARDIOGRAFO",          "fa-heartbeat"),
            ("Microscopio",               "MICROSCOPIO",              "fa-microscope"),
            ("Insuflador",                "INSUFLADOR",               "fa-compress"),
            ("Generador",                 "GENERADOR",                "fa-bolt"),
            ("Ligasure",                  "LIGASURE",                 "fa-cut"),
        ]

        try:
            cursor   = db.cursor()
            resultado = []

            for label, keyword, icono in categorias_def:
                # Normaliza el keyword para la comparación
                keyword_norm = keyword.lower()
                # Construye la condición con normalización de acentos
                condicion = (
                    f"LOWER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE("
                    f"equipo_unidad,'á','a'),'é','e'),'í','i'),'ó','o'),'ú','u')) "
                    f"LIKE ?"
                )
                sql = f"SELECT COUNT(*) FROM InventarioEquipos WHERE {condicion}"
                cursor.execute(sql, (f"%{keyword_norm}%",))
                count = cursor.fetchone()[0]

                if count >= 2:
                    resultado.append({
                        "label":   label,
                        "keyword": keyword,
                        "icono":   icono,
                        "count":   count
                    })

            cursor.close()
            return resultado

        except Exception as e:
            print(f"Error get_categorias: {e}")
            return []