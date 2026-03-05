from .entities.User import User
import re


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
                    u.Carrera, 
                    u.Telefono, 
                    u.Rol, 
                    u.Email, 
                    u.Permiso, 
                    u.Imagen
                    
                FROM dbo.usuario u
                WHERE u.Email = ? 
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
                        Carrera=row[4],
                        Telefono=row[5],
                        Rol=row[6],
                        email=row[7],
                        Permiso=row[8],
                        Imagen=row[9]
                        
                    )
                else:
                    return None
            else:
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
                SELECT IDusuario, NombreUsuario, Password, Apellido, 
                       Carrera, Telefono, Rol, Email, Permiso, Imagen
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
                    Carrera=row[4],
                    Telefono=row[5],
                    Rol=row[6],
                    email=row[7],
                    Permiso=row[8],
                    Imagen=row[9]
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
        except Exception as ex:
            raise Exception(ex)
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def check_username_exists(cls, db, nombre, apellido):
        cursor = None
        try:
            cursor = db.cursor()
            nombre_usuario = f"{nombre}{apellido}"
            cursor.execute("SELECT COUNT(*) FROM dbo.usuario WHERE NombreUsuario = ?", (nombre_usuario,))
            return cursor.fetchone()[0] > 0
        except Exception as ex:
            raise Exception(ex)
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def register(cls, db, user_data):
        cursor = None
        try:
            # Validaciones
            if not cls._validate_password(user_data['password']):
                return False, "La contraseña debe tener al menos 8 caracteres, una mayúscula, una minúscula y un número"

            if not cls._validate_email(user_data['email']):
                return False, "Formato de correo electrónico inválido"

            if not cls._validate_phone(user_data['telefono']):
                return False, "Formato de teléfono inválido"

            if cls.check_email_exists(db, user_data['email']):
                return False, "El correo electrónico ya está registrado"

            if cls.check_username_exists(db, user_data['nombre'], user_data['apellido']):
                return False, "Ya existe un usuario con ese nombre y apellido"

            # Hashear contraseña antes de guardar
            hashed_password = User.hash_password(user_data['password'])

            cursor = db.cursor()
            sql = """
                INSERT INTO dbo.usuario 
                    (NombreUsuario, Password, Apellido, Carrera, Telefono, Rol, Email, Permiso) 
                VALUES (?, ?, ?, ?, ?, ?, ?, 'Visitante')
            """
            cursor.execute(sql, (
                user_data['nombre'],
                hashed_password,        # ✅ Contraseña hasheada
                user_data['apellido'],
                user_data['carrera'],
                user_data['telefono'],
                user_data['rol'],
                user_data['email']
            ))
            db.commit()
            return True, "Usuario registrado exitosamente"

        except Exception as ex:
            db.rollback()
            return False, f"Error al registrar usuario: {str(ex)}"
        finally:
            if cursor:
                cursor.close()

    @staticmethod
    def _validate_password(password):
        return bool(re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$', password))

    @staticmethod
    def _validate_email(email):
        return bool(re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email))

    @staticmethod
    def _validate_phone(phone):
        return bool(re.match(r'^\d{10}$', phone))