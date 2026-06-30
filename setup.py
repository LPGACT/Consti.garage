# setup.py — Corré esto UNA SOLA VEZ para crear el Google Sheet
# Después de correrlo, copiá el GOOGLE_SHEETS_ID que te devuelve en tu .env

import os
import json
from datetime import datetime
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

load_dotenv()

# Drive API necesaria solo para crear el sheet (no para el bot en sí)
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

print("🅿️  Setup — Bot de Registro de Pagos\n")

# Cargar credenciales
creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
if creds_json:
    creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=SCOPES)
else:
    if not os.path.exists('credentials.json'):
        print("❌ No encontré credentials.json ni GOOGLE_CREDENTIALS_JSON en el .env")
        print("   Seguí el Paso 3 del README para crearlo.")
        exit(1)
    creds = Credentials.from_service_account_file('credentials.json', scopes=SCOPES)

gc = gspread.authorize(creds)

# Crear el sheet
year       = datetime.now().year
sheet_name = f"Pagos Estacionamiento {year}"

print(f"Creando sheet: '{sheet_name}'...")
spreadsheet = gc.create(sheet_name)

# Eliminar la hoja por defecto que crea Google ("Sheet1")
default_ws = spreadsheet.sheet1
spreadsheet.del_worksheet(default_ws)

# Compartir con el usuario
email = input("Ingresá tu email de Google para que puedas ver el sheet: ").strip()
spreadsheet.share(email, perm_type='user', role='writer')

print(f"\n✅ Sheet creado y compartido con {email}")
print(f"🔗 {spreadsheet.url}")
print(f"\n{'─'*55}")
print(f"Copiá esta línea en tu .env:")
print(f"\n  GOOGLE_SHEETS_ID={spreadsheet.id}")
print(f"{'─'*55}\n")
print("Las hojas mensuales (JUNIO, JULIO, etc.) se crean")
print("automáticamente la primera vez que registrás un pago.")
