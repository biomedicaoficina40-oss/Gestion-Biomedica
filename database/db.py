import pyodbc
import os

print(pyodbc.drivers())
def get_connection():
    try:
        server = os.getenv('DB_SERVER', 'LAPBIOMEDICA\SQLEXPRESS')
        database = os.getenv('DB_NAME', 'HospitalGalenia')
        username = os.getenv('DB_USER', 'flask_project')
        password = os.getenv('DB_PASSWORD', 'labbiomedica')
        driver = os.getenv('DB_DRIVER', '{ODBC Driver 17 for SQL Server}')
        
        conn = pyodbc.connect(
            f'DRIVER={driver};'
            f'SERVER={server};'
            f'DATABASE={database};'
            f'UID={username};'
            f'PWD={password};'
            f'Trusted_Connection=no;'
        )
        return conn
    except Exception as e:
        print(f"Error de conexión: {e}")
        return None