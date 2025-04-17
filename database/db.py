import pyodbc

def get_connection():
    try:
        db = pyodbc.connect(
            'DRIVER={SQL Server};'
            'SERVER=EQUIPO2\SQLEXPRESS;'
            'DATABASE=sistema_de_prestamo;'
            'Trusted_Connection=yes;'
        )
        print("Conexión exitosa")
        return db
    except Exception as ex:
        print(f"Error de conexión: {ex}")
        return None