from database.db import get_connection
from werkzeug.security import generate_password_hash
from datetime import datetime


class ModelUsuarios:

    # ── Listar todos ──────────────────────────────────────────────
    @staticmethod
    def get_all():
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT IDusuario, NombreUsuario, Apellido, Email,
                   Permiso, Imagen, FechaCreacion, Estado
            FROM usuario
            ORDER BY NombreUsuario
        """)
        cols = [c[0] for c in cursor.description]
        rows = [dict(zip(cols, row)) for row in cursor.fetchall()]
        conn.close()
        return rows

    # ── Obtener uno por ID ────────────────────────────────────────
    @staticmethod
    def get_by_id(uid):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT IDusuario, NombreUsuario, Apellido, Email,
                   Permiso, Imagen, FechaCreacion, Estado
            FROM usuario
            WHERE IDusuario = ?
        """, uid)
        cols = [c[0] for c in cursor.description]
        row  = cursor.fetchone()
        conn.close()
        return dict(zip(cols, row)) if row else None

    # ── Crear ─────────────────────────────────────────────────────
    @staticmethod
    def crear(nombre, apellido, email, password, permiso):
        hashed = generate_password_hash(password)
        conn   = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO usuario (NombreUsuario, Apellido, Email, Password,
                                 Permiso, FechaCreacion, Estado)
            VALUES (?, ?, ?, ?, ?, GETDATE(), 1)
        """, nombre, apellido, email, hashed, permiso)
        conn.commit()
        conn.close()

    # ── Editar ────────────────────────────────────────────────────
    @staticmethod
    def editar(uid, nombre, apellido, email, permiso, estado, password=None):
        conn   = get_connection()
        cursor = conn.cursor()
        if password:
            hashed = generate_password_hash(password)
            cursor.execute("""
                UPDATE usuario
                SET NombreUsuario = ?, Apellido = ?, Email = ?,
                    Permiso = ?, Estado = ?, Password = ?
                WHERE IDusuario = ?
            """, nombre, apellido, email, permiso, estado, hashed, uid)
        else:
            cursor.execute("""
                UPDATE usuario
                SET NombreUsuario = ?, Apellido = ?, Email = ?,
                    Permiso = ?, Estado = ?
                WHERE IDusuario = ?
            """, nombre, apellido, email, permiso, estado, uid)
        conn.commit()
        conn.close()

    # ── Toggle Estado ─────────────────────────────────────────────
    @staticmethod
    def toggle_estado(uid):
        conn   = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE usuario
            SET Estado = CASE WHEN Estado = 1 THEN 0 ELSE 1 END
            WHERE IDusuario = ?
        """, uid)
        conn.commit()
        conn.close()

    # ── Verificar email duplicado ─────────────────────────────────
    @staticmethod
    def email_existe(email, exclude_uid=None):
        conn   = get_connection()
        cursor = conn.cursor()
        if exclude_uid:
            cursor.execute(
                "SELECT 1 FROM usuario WHERE Email = ? AND IDusuario <> ?",
                email, exclude_uid
            )
        else:
            cursor.execute("SELECT 1 FROM usuario WHERE Email = ?", email)
        exists = cursor.fetchone() is not None
        conn.close()
        return exists