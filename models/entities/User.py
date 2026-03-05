from werkzeug.security import check_password_hash, generate_password_hash
from flask_login import UserMixin


class User(UserMixin):

    def __init__(self, IDusuario, NombreUsuario, password, Apellido="", Carrera="", Telefono="", Rol="", email="", Permiso="",Imagen='') -> None:
        self.IDusuario = IDusuario       
        self.NombreUsuario = NombreUsuario
        self.password = password
        self.Apellido = Apellido
        self.Carrera = Carrera
        self.Telefono = Telefono
        self.Rol = Rol
        self.email = email
        self.Permiso = Permiso
        self.Imagen = Imagen
        
        
    @classmethod
    def check_password(self, hashed_password, password):
        return check_password_hash(hashed_password, password)

    @classmethod
    def hash_password(self, password):
        return generate_password_hash(password)
    
    def get_id(self):
        return self.IDusuario
# Ejemplo de uso
#print(generate_password_hash("Mauricio"))
