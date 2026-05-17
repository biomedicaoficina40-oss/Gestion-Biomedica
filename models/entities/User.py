from werkzeug.security import check_password_hash, generate_password_hash
from flask_login import UserMixin


class User(UserMixin):

    def __init__(
        self,
        IDusuario,
        NombreUsuario,
        password,
        Apellido="",
        email="",
        Permiso="",
        Imagen=None,
        FechaCreacion=None,
        Estado=None
    ) -> None:

        self.IDusuario = IDusuario
        self.NombreUsuario = NombreUsuario
        self.password = password
        self.Apellido = Apellido
        self.email = email
        self.Permiso = Permiso
        self.Imagen = Imagen
        self.FechaCreacion = FechaCreacion
        self.Estado = Estado

    @classmethod
    def check_password(cls, hashed_password, password):
        return check_password_hash(hashed_password, password)

    @classmethod
    def hash_password(cls, password):
        return generate_password_hash(password)

    def get_id(self):
        return self.IDusuario



        