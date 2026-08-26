import re

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash


class User(UserMixin):
    """
    Usuario autenticado.

    Deliberadamente NO guarda el hash de la contraseña: este objeto vive en
    `current_user` y queda accesible desde cualquier plantilla, así que el
    hash no tiene por qué llegar hasta aquí. La verificación ocurre en
    ModelUser.login y termina ahí.
    """

    def __init__(
        self,
        IDusuario,
        NombreUsuario,
        Apellido="",
        email="",
        Permiso="",
        Imagen=None,
        FechaCreacion=None,
        Estado=None
    ) -> None:

        self.IDusuario = IDusuario
        self.NombreUsuario = NombreUsuario
        self.Apellido = Apellido
        self.email = email
        self.Permiso = Permiso
        self.Imagen = Imagen
        self.FechaCreacion = FechaCreacion
        self.Estado = Estado

    # ── Contraseñas ──────────────────────────────────────────────────
    # Único punto del proyecto donde se hashea o verifica una contraseña.

    @classmethod
    def check_password(cls, hashed_password, password):
        return check_password_hash(hashed_password, password)

    @classmethod
    def hash_password(cls, password):
        return generate_password_hash(password)

    # Requisitos mínimos: 8 caracteres, una minúscula, una mayúscula y un dígito.
    _REGLA_PASSWORD = re.compile(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$')

    MENSAJE_PASSWORD = (
        'La contraseña debe tener al menos 8 caracteres e incluir '
        'una mayúscula, una minúscula y un número.'
    )

    @classmethod
    def validar_password(cls, password):
        """True si la contraseña cumple la política mínima."""
        return bool(cls._REGLA_PASSWORD.match(password or ''))

    def get_id(self):
        return self.IDusuario
