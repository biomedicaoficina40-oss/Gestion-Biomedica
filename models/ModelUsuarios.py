from database.db import get_connection
from models.entities.User import User
from models.entities.decorators import ROL_ADMIN, ROLES_VALIDOS, rol_canonico


class ModelUsuarios:
    """
    Capa de acceso a datos para la tabla `usuario`.
    Nunca elimina registros — usa toggle de Estado (1/0).
    El hashing de contraseñas se delega a User.hash_password()
    para mantener una única fuente de verdad.

    Todos los métodos abren y cierran su propia conexión dentro de un
    try/finally: antes, cualquier error en la consulta dejaba la conexión
    colgada porque el close() venía después y nunca se alcanzaba.
    """

    # ── Helper interno ────────────────────────────────────────────
    @staticmethod
    def _conectar():
        conn = get_connection()
        if conn is None:
            raise RuntimeError('Sin conexión a la base de datos')
        return conn

    # ── Listar todos ──────────────────────────────────────────────
    @staticmethod
    def get_all():
        """Retorna todos los usuarios ordenados por nombre."""
        conn = ModelUsuarios._conectar()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT IDusuario, NombreUsuario, Apellido, Email,
                       Permiso, Imagen, FechaCreacion, Estado
                FROM usuario
                ORDER BY NombreUsuario
            """)
            cols = [c[0] for c in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]
        finally:
            conn.close()

    # ── Obtener uno por ID ────────────────────────────────────────
    @staticmethod
    def get_by_id(uid):
        """Retorna un dict con los datos del usuario o None si no existe."""
        conn = ModelUsuarios._conectar()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT IDusuario, NombreUsuario, Apellido, Email,
                       Permiso, Imagen, FechaCreacion, Estado
                FROM usuario
                WHERE IDusuario = ?
            """, uid)
            cols = [c[0] for c in cursor.description]
            row = cursor.fetchone()
            return dict(zip(cols, row)) if row else None
        finally:
            conn.close()

    # ── Crear ─────────────────────────────────────────────────────
    @staticmethod
    def crear(nombre, apellido, email, password, permiso):
        """
        Inserta un nuevo usuario activo.
        La contraseña se hashea aquí antes de persistir.

        Revalida rol y contraseña aunque la ruta ya lo haya hecho: es la
        última barrera antes de escribir en BD.
        """
        rol = rol_canonico(permiso)
        if rol is None:
            raise ValueError(f'Rol no válido. Debe ser uno de: {", ".join(ROLES_VALIDOS)}')
        if not User.validar_password(password):
            raise ValueError(User.MENSAJE_PASSWORD)

        hashed = User.hash_password(password)
        conn = ModelUsuarios._conectar()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO usuario
                    (NombreUsuario, Apellido, Email, Password,
                     Permiso, FechaCreacion, Estado)
                VALUES (?, ?, ?, ?, ?, GETDATE(), 1)
            """, nombre, apellido, email, hashed, rol)
            conn.commit()
        finally:
            conn.close()

    # ── Editar ────────────────────────────────────────────────────
    @staticmethod
    def editar(uid, nombre, apellido, email, permiso, estado, password=None):
        """
        Actualiza los datos de un usuario.
        Si `password` es None o vacío, no se modifica la contraseña.
        """
        rol = rol_canonico(permiso)
        if rol is None:
            raise ValueError(f'Rol no válido. Debe ser uno de: {", ".join(ROLES_VALIDOS)}')
        if password and not User.validar_password(password):
            raise ValueError(User.MENSAJE_PASSWORD)

        conn = ModelUsuarios._conectar()
        try:
            cursor = conn.cursor()
            if password:
                hashed = User.hash_password(password)
                cursor.execute("""
                    UPDATE usuario
                    SET NombreUsuario = ?,
                        Apellido      = ?,
                        Email         = ?,
                        Permiso       = ?,
                        Estado        = ?,
                        Password      = ?
                    WHERE IDusuario = ?
                """, nombre, apellido, email, rol, estado, hashed, uid)
            else:
                cursor.execute("""
                    UPDATE usuario
                    SET NombreUsuario = ?,
                        Apellido      = ?,
                        Email         = ?,
                        Permiso       = ?,
                        Estado        = ?
                    WHERE IDusuario = ?
                """, nombre, apellido, email, rol, estado, uid)
            conn.commit()
        finally:
            conn.close()

    # ── Toggle Estado (activo ↔ inactivo) ─────────────────────────
    @staticmethod
    def toggle_estado(uid):
        """
        Invierte el Estado del usuario (1→0 o 0→1).
        No elimina el registro ni sus relaciones.
        """
        conn = ModelUsuarios._conectar()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE usuario
                SET Estado = CASE WHEN Estado = 1 THEN 0 ELSE 1 END
                WHERE IDusuario = ?
            """, uid)
            conn.commit()
        finally:
            conn.close()

    # ── Verificar email duplicado ─────────────────────────────────
    @staticmethod
    def email_existe(email, exclude_uid=None):
        """
        Retorna True si el email ya está registrado.
        `exclude_uid` permite ignorar el propio registro al editar.
        """
        conn = ModelUsuarios._conectar()
        try:
            cursor = conn.cursor()
            if exclude_uid:
                cursor.execute(
                    "SELECT 1 FROM usuario WHERE Email = ? AND IDusuario <> ?",
                    email, exclude_uid
                )
            else:
                cursor.execute(
                    "SELECT 1 FROM usuario WHERE Email = ?",
                    email
                )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    # ── Salvaguarda: no dejar el sistema sin administradores ──────
    @staticmethod
    def contar_administradores_activos(excluir_uid=None):
        """
        Cuántos administradores activos hay. `excluir_uid` permite preguntar
        "¿cuántos quedarían si este deja de serlo?" antes de guardar.
        """
        conn = ModelUsuarios._conectar()
        try:
            cursor = conn.cursor()
            if excluir_uid:
                cursor.execute("""
                    SELECT COUNT(*) FROM usuario
                    WHERE Permiso = ? AND Estado = 1 AND IDusuario <> ?
                """, ROL_ADMIN, excluir_uid)
            else:
                cursor.execute("""
                    SELECT COUNT(*) FROM usuario
                    WHERE Permiso = ? AND Estado = 1
                """, ROL_ADMIN)
            return cursor.fetchone()[0]
        finally:
            conn.close()
