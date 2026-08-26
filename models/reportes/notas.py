"""
Anotaciones del técnico durante el trabajo.

Es lo que convierte un correctivo en un antecedente útil: "la tarjeta X venía
con el conector invertido de fábrica", "hay que aflojar los cuatro tornillos de
atrás antes de levantar la tapa o se rompe la bisagra".

Distinta de ReporteBitacora a propósito:

  - **Bitácora** la escribe el sistema, nadie la edita, y responde "quién liberó
    esto y cuándo" frente a un auditor.
  - **Notas** las escribe la persona, se pueden corregir, y responden "qué pasó
    con este equipo".

Mezclarlas volvería editable un registro de auditoría, que es justo lo que no
debe ser.

`incluir_en_pdf` viene APAGADO por omisión, al revés que en los adjuntos: la
mayoría de las notas son de trabajo interno y no tienen por qué salir en un
documento que firma el responsable del área.
"""

from flask import current_app

MAX_NOTAS = 100
MAX_TEXTO = 4000


class ModelNotas:
    TABLE = "HospitalGalenia.dbo.ReporteNotas"

    @classmethod
    def get_por_reporte(cls, db, reporte_id, solo_pdf=False):
        """Notas en orden cronológico, con el nombre de quien las escribió."""
        cursor = None
        try:
            cursor = db.cursor()
            sql = (
                f"SELECT n.id, n.reporte_id, n.texto, n.usuario_id, n.fecha, "
                f"       n.incluir_en_pdf, u.NombreUsuario, u.Apellido "
                f"FROM {cls.TABLE} n "
                f"LEFT JOIN HospitalGalenia.dbo.usuario u ON u.IDusuario = n.usuario_id "
                f"WHERE n.reporte_id = ?")
            if solo_pdf:
                sql += " AND n.incluir_en_pdf = 1"
            sql += " ORDER BY n.fecha, n.id"

            cursor.execute(sql, (reporte_id,))
            columnas = [c[0] for c in cursor.description]
            notas = [dict(zip(columnas, f)) for f in cursor.fetchall()]

            for nota in notas:
                nombre = ' '.join(filter(None, [nota.get('NombreUsuario'),
                                                nota.get('Apellido')]))
                nota['autor'] = nombre.strip() or 'Sistema'
            return notas

        except Exception as e:
            current_app.logger.error(
                f"[ModelNotas.get_por_reporte] reporte={reporte_id} | {e}")
            return []
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def crear(cls, db, reporte_id, texto, usuario_id=None, incluir_en_pdf=False):
        """Agrega una anotación. Devuelve (ok, mensaje_o_id)."""
        texto = (texto or '').strip()
        if not texto:
            return False, "La anotación no puede ir vacía"
        if len(texto) > MAX_TEXTO:
            texto = texto[:MAX_TEXTO]

        cursor = None
        try:
            cursor = db.cursor()

            cursor.execute(
                f"SELECT COUNT(*) FROM {cls.TABLE} WHERE reporte_id = ?",
                (reporte_id,))
            if (cursor.fetchone()[0] or 0) >= MAX_NOTAS:
                return False, f"Un reporte admite hasta {MAX_NOTAS} anotaciones"

            cursor.execute(
                f"INSERT INTO {cls.TABLE} "
                f"(reporte_id, texto, usuario_id, incluir_en_pdf) "
                f"OUTPUT INSERTED.id VALUES (?, ?, ?, ?)",
                (reporte_id, texto, usuario_id, 1 if incluir_en_pdf else 0))
            nuevo_id = cursor.fetchone()[0]
            db.commit()
            return True, nuevo_id

        except Exception as e:
            current_app.logger.error(f"[ModelNotas.crear] reporte={reporte_id} | {e}")
            try:
                db.rollback()
            except Exception:
                pass
            return False, "No se pudo guardar la anotación"
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def actualizar(cls, db, nota_id, texto=None, incluir_en_pdf=None):
        campos, valores = [], []
        if texto is not None:
            limpio = (texto or '').strip()
            if not limpio:
                return False
            campos.append("texto = ?")
            valores.append(limpio[:MAX_TEXTO])
        if incluir_en_pdf is not None:
            campos.append("incluir_en_pdf = ?")
            valores.append(1 if incluir_en_pdf else 0)
        if not campos:
            return True

        cursor = None
        try:
            cursor = db.cursor()
            valores.append(nota_id)
            cursor.execute(
                f"UPDATE {cls.TABLE} SET {', '.join(campos)} WHERE id = ?",
                tuple(valores))
            db.commit()
            return True
        except Exception as e:
            current_app.logger.error(f"[ModelNotas.actualizar] id={nota_id} | {e}")
            try:
                db.rollback()
            except Exception:
                pass
            return False
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def eliminar(cls, db, nota_id):
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(f"DELETE FROM {cls.TABLE} WHERE id = ?", (nota_id,))
            borrado = cursor.rowcount > 0
            db.commit()
            return borrado
        except Exception as e:
            current_app.logger.error(f"[ModelNotas.eliminar] id={nota_id} | {e}")
            try:
                db.rollback()
            except Exception:
                pass
            return False
        finally:
            if cursor:
                cursor.close()
