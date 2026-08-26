from .entities.User import User


# Hash descartable de una contraseña aleatoria. Cuando el correo no existe se
# verifica contra este valor para que la respuesta tarde lo mismo que un
# intento con correo válido; sin esto, la diferencia de tiempo permite
# averiguar qué correos están dados de alta.
_HASH_SENUELO = User.hash_password('$senuelo-sin-uso$')


class ModelUser():
    """
    Acceso a `dbo.usuario` para el circuito de autenticación.
    Recibe siempre la conexión por parámetro: quien la abre, la cierra.
    """

    # Columnas que se cargan en el objeto de sesión. El hash de la contraseña
    # se consulta aparte y nunca sale de este módulo.
    _CAMPOS = """
        IDusuario,
        NombreUsuario,
        Apellido,
        Email,
        Permiso,
        Imagen,
        FechaCreacion,
        Estado
    """

    @staticmethod
    def _construir(row):
        return User(
            IDusuario     = row[0],
            NombreUsuario = row[1],
            Apellido      = row[2],
            email         = row[3],
            Permiso       = row[4],
            Imagen        = row[5],
            FechaCreacion = row[6],
            Estado        = row[7],
        )

    @classmethod
    def login(cls, db, email, password):
        """
        Verifica credenciales y devuelve el User autenticado, o None.

        Solo considera cuentas activas (Estado = 1). No distingue entre
        'correo inexistente' y 'contraseña incorrecta'.
        """
        if db is None:
            raise RuntimeError('Sin conexión a la base de datos')

        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"""
                SELECT {cls._CAMPOS}, Password
                FROM dbo.usuario
                WHERE Email = ? AND Estado = 1
                """,
                (email,)
            )
            row = cursor.fetchone()

            if row is None:
                # Gasto deliberado de tiempo para igualar ambos caminos.
                User.check_password(_HASH_SENUELO, password)
                return None

            hash_guardado = row[8]
            if not User.check_password(hash_guardado, password):
                return None

            return cls._construir(row)

        finally:
            if cursor:
                cursor.close()

    @classmethod
    def get_by_id(cls, db, IDusuario):
        """
        Reconstruye el usuario de la sesión en cada request (user_loader).

        Filtra por Estado = 1 a propósito: así, al desactivar una cuenta desde
        el panel de usuarios, la sesión abierta de esa persona deja de resolver
        y queda fuera en la siguiente petición, sin esperar a que cierre el
        navegador.
        """
        if db is None:
            raise RuntimeError('Sin conexión a la base de datos')

        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute(
                f"""
                SELECT {cls._CAMPOS}
                FROM dbo.usuario
                WHERE IDusuario = ? AND Estado = 1
                """,
                (IDusuario,)
            )
            row = cursor.fetchone()
            return cls._construir(row) if row is not None else None

        finally:
            if cursor:
                cursor.close()
