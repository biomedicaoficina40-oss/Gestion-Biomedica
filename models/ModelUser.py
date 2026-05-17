from .entities.User import User
import re
from datetime import datetime

class ModelUser():

    @classmethod
    def login(cls, db, user):
        cursor = None
        try:
            cursor = db.cursor()
            sql = """
                SELECT 
                    u.IDusuario,
                    u.NombreUsuario,
                    u.Password,
                    u.Apellido,
                    u.Email,
                    u.Permiso,
                    u.Imagen,
                    u.FechaCreacion,
                    u.Estado
                FROM dbo.usuario u
                WHERE u.Email = ? AND u.Estado = 1
            """
            cursor.execute(sql, (user.email,))
            row = cursor.fetchone()

            if row is not None:
                if User.check_password(row[2], user.password):
                    return User(
                        IDusuario=row[0],
                        NombreUsuario=row[1],
                        password=row[2],
                        Apellido=row[3],
                        email=row[4],
                        Permiso=row[5],
                        Imagen=row[6],
                        FechaCreacion=row[7],
                        Estado=row[8]
                    )
            return None

        except Exception as ex:
            print(f"Error en login: {str(ex)}")
            raise Exception(ex)
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def get_by_id(cls, db, IDusuario):
        cursor = None
        try:
            cursor = db.cursor()
            sql = """
                SELECT 
                    IDusuario,
                    NombreUsuario,
                    Password,
                    Apellido,
                    Email,
                    Permiso,
                    Imagen,
                    FechaCreacion,
                    Estado
                FROM dbo.usuario
                WHERE IDusuario = ?
            """
            cursor.execute(sql, (IDusuario,))
            row = cursor.fetchone()

            if row is not None:
                return User(
                    IDusuario=row[0],
                    NombreUsuario=row[1],
                    password=row[2],
                    Apellido=row[3],
                    email=row[4],
                    Permiso=row[5],
                    Imagen=row[6],
                    FechaCreacion=row[7],
                    Estado=row[8]
                )
            return None

        except Exception as ex:
            print(f"Error en get_by_id: {str(ex)}")
            raise Exception(ex)
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def check_email_exists(cls, db, email):
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute("SELECT COUNT(*) FROM dbo.usuario WHERE Email = ?", (email,))
            return cursor.fetchone()[0] > 0
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def check_username_exists(cls, db, nombre):
        cursor = None
        try:
            cursor = db.cursor()
            cursor.execute("SELECT COUNT(*) FROM dbo.usuario WHERE NombreUsuario = ?", (nombre,))
            return cursor.fetchone()[0] > 0
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def register(cls, db, user_data):
        cursor = None
        try:
            # Validaciones
            if not cls._validate_password(user_data['password']):
                return False, "La contraseña no cumple requisitos"

            if not cls._validate_email(user_data['email']):
                return False, "Correo inválido"

            if cls.check_email_exists(db, user_data['email']):
                return False, "Correo ya registrado"

            if cls.check_username_exists(db, user_data['nombre']):
                return False, "Usuario ya existe"

            hashed_password = User.hash_password(user_data['password'])

            cursor = db.cursor()
            sql = """
                INSERT INTO dbo.usuario
                    (NombreUsuario, Password, Apellido, Email, Permiso, FechaCreacion, Estado)
                VALUES (?, ?, ?, ?, 'Visitante', ?, 1)
            """

            cursor.execute(sql, (
                user_data['nombre'],
                hashed_password,
                user_data['apellido'],
                user_data['email'],
                datetime.now()
            ))

            db.commit()
            return True, "Usuario registrado correctamente"

        except Exception as ex:
            db.rollback()
            return False, f"Error: {str(ex)}"
        finally:
            if cursor:
                cursor.close()

    @staticmethod
    def _validate_password(password):
        return bool(re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$', password))

    @staticmethod
    def _validate_email(email):
        return bool(re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email))