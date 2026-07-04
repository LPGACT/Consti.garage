# sheets_common.py — Lo que comparten bot.py y el dashboard.
#
# No importa nada de bot.py a propósito: bot.py configura Telegram/Gemini y
# abre el cliente de gspread a nivel de módulo apenas se importa, y el
# dashboard no necesita (ni debe) arrastrar esos side-effects solo para
# reusar format_pesos o el nombre de una hoja.

import os
import re
import datetime
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

ING_BRUTOS_PCT = 0.025  # 2.5%

HEADER_ROW = ['Fecha', 'Cochera', 'Nombre', 'Monto', 'Ing. Brutos (2.5%)', 'Tipo de Pago']
GASTOS_HEADER_ROW = ['Fecha', 'Categoría', 'Monto', 'Descripción']

PADRON_SHEET_TITLE = 'PADRON'
OBJETIVO_SHEET_TITLE = 'RENDICION_OBJETIVO_BASE'

MESES_ORDEN = [
    'ENERO', 'FEBRERO', 'MARZO', 'ABRIL', 'MAYO', 'JUNIO',
    'JULIO', 'AGOSTO', 'SEPTIEMBRE', 'OCTUBRE', 'NOVIEMBRE', 'DICIEMBRE'
]

_TITLE_RE = re.compile(r'^([A-ZÁÉÍÓÚÑ]+)\s+(\d{4})$')


def build_gspread_client() -> gspread.Client:
    import json
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
    creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
    if creds_json:
        creds = Credentials.from_service_account_info(
            json.loads(creds_json), scopes=SCOPES
        )
    else:
        creds_path = os.path.join(os.path.expanduser('~'), 'secrets', 'credentials.json')
        creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    return gspread.authorize(creds)


def format_pesos(amount: float) -> str:
    """Formatea en pesos argentinos: $140.000,00"""
    s = f"{amount:,.2f}"                                     # "140,000.00"
    return "$" + s.replace(',', 'X').replace('.', ',').replace('X', '.')


def mes_sheet_title(mes: str, year: Optional[int] = None) -> str:
    """Título de la hoja de ingresos de un mes, con año incluido (ej. 'JULIO 2026').
    El año se agrega automáticamente (año actual) para que dos mismos meses en
    años distintos no terminen escribiendo en la misma hoja."""
    year = year or datetime.date.today().year
    return f"{mes.strip().upper()} {year}"


def gastos_sheet_title(mes: str, year: Optional[int] = None) -> str:
    return f"{mes_sheet_title(mes, year)} - GASTOS"


def parse_mes_sheet_title(title: str) -> Optional[tuple]:
    """Si el título es una hoja de ingresos con año (ej. 'JULIO 2026'),
    devuelve (mes, año). Si no matchea (hojas '... - GASTOS', 'PADRON',
    o meses viejos sin año todavía no migrados), devuelve None."""
    match = _TITLE_RE.match(title.strip())
    if not match or match.group(1) not in MESES_ORDEN:
        return None
    return match.group(1), int(match.group(2))
