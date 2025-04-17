from .entities.User import User
import re

class ModelUser():
    @classmethod
    def login(self, db, user):
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
                    u.Imagen,
                    COALESCE(cp.CarritoID, NULL) AS CarritoID
                FROM 
                    dbo.usuario u
                LEFT JOIN 
                    dbo.CarritoPedidos cp 
                ON 
                    u.IDusuario = cp.IDusuario
                WHERE 
                    u.Email = ?
                """

            
            cursor.execute(sql, (user.email,))
            row = cursor.fetchone()

            if row != None:
                user = User(row[0], row[1], User.check_password(row[2], user.password), row[3],row[4],row[5],row[6],row[7],row[8],row[9],row[10])

                return user
            else:
                return None
        except Exception as ex:
            print(f"Error en login: {str(ex)}")  
            raise Exception(ex)
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def get_by_id(self, db, IDusuario):
        cursor = None
        try:
            cursor = db.cursor()
            sql = """SELECT IDusuario, NombreUsuario, Password, Apellido, Carrera, Telefono, Rol, Email, Permiso 
                    FROM dbo.usuario WHERE IDusuario = ?"""
            cursor.execute(sql, (IDusuario,))
            row = cursor.fetchone()
            if row != None:
                return User(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8])
            else:
                return None
        except Exception as ex:
            print(f"Error en get_by_id: {str(ex)}")  # Para depuración
            raise Exception(ex)
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def check_email_exists(self, db, email):
        cursor = None
        try:
            cursor = db.cursor()
            sql = "SELECT COUNT(*) FROM dbo.usuario WHERE Email = ?"
            cursor.execute(sql, (email,))
            count = cursor.fetchone()[0]
            return count > 0
        except Exception as ex:
            raise Exception(ex)
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def check_username_exists(self, db, nombre, apellido):
        cursor = None
        try:
            cursor = db.cursor()
            nombre_usuario = f"{nombre}{apellido}"  # Combinación simple de nombre y apellido
            sql = "SELECT COUNT(*) FROM dbo.usuario WHERE NombreUsuario = ?"
            cursor.execute(sql, (nombre_usuario,))
            count = cursor.fetchone()[0]
            return count > 0
        except Exception as ex:
            raise Exception(ex)
        finally:
            if cursor:
                cursor.close()

    @classmethod
    def register(self, db, user_data):
        cursor = None
        try:
            # Validaciones
            if not self._validate_password(user_data['password']):
                return False, "La contraseña debe tener al menos 8 caracteres, una mayúscula, una minúscula y un número"



            if not self._validate_email(user_data['email']):
                return False, "Formato de correo electrónico inválido"

            if not self._validate_phone(user_data['telefono']):
                return False, "Formato de teléfono inválido"

            if self.check_email_exists(db, user_data['email']):
                return False, "El correo electrónico ya está registrado"

            nombre_usuario = f"{user_data['nombre']}{user_data['apellido']}"
            if self.check_username_exists(db, user_data['nombre'], user_data['apellido']):
                return False, "Ya existe un usuario con ese nombre y apellido"

            cursor = db.cursor()
            sql = """
                    INSERT INTO dbo.usuario (NombreUsuario, Password, Apellido, 
                    Carrera, Telefono, Rol, Email, Permiso) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'Visitante')
                    """  # Ocho marcadores de parámetros

            cursor.execute(sql, (
                user_data['nombre'],
                user_data['password'], # Usar la contraseña hasheada
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
        # Al menos 8 caracteres, una mayúscula, una minúscula y un número
        return bool(re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$', password))

    @staticmethod
    def _validate_email(email):
        # Validación básica de email
        return bool(re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email))

    @staticmethod
    def _validate_phone(phone):
        # Validación básica de teléfono (10 dígitos)
        return bool(re.match(r'^\d{10}$', phone))