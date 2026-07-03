# dashboard/main.py — Backend del dashboard financiero (FastAPI).
#
# Deliberadamente NO importa bot.py: bot.py configura Telegram/Gemini y abre
# un cliente de gspread a nivel de módulo apenas se importa, y este backend
# no necesita (ni debe) arrastrar esos side-effects solo para leer Sheets.
# Ver sheets_common.py para lo que sí se comparte.

import datetime
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from sheets_common import build_gspread_client, format_pesos, mes_sheet_title, gastos_sheet_title
from dashboard.auth import require_auth, DASHBOARD_PASSWORD
from dashboard.cache import cached
from dashboard.metrics import calcular_serie_mensual, leer_gastos, estado_cocheras, listar_meses_ingresos
from dashboard.padron import leer_padron

load_dotenv(os.path.join(os.path.expanduser('~'), 'secrets', '.env'))

SHEETS_ID = os.getenv('GOOGLE_SHEETS_ID')
RENDICION_OBJETIVO_BASE = float(os.getenv('RENDICION_OBJETIVO_BASE', 9_800_000))
SERIE_CACHE_TTL = int(os.getenv('SERIE_CACHE_TTL_SECONDS', 120))
PADRON_CACHE_TTL = int(os.getenv('PADRON_CACHE_TTL_SECONDS', 300))

STATIC_DIR = Path(__file__).parent / 'static'

gc = build_gspread_client()

app = FastAPI(title="Consti.garage — Dashboard")

_CAMPOS_MONETARIOS = [
    'ingreso_bruto', 'ingreso_neto', 'total_transferencias', 'total_efectivo',
    'total_gastos', 'deuda_heredada', 'objetivo_rendicion', 'entregado_a_socios',
    'ganancia_mes',
]


def _spreadsheet():
    return gc.open_by_key(SHEETS_ID)


def _serie_mensual() -> dict:
    return cached(
        'serie_mensual', SERIE_CACHE_TTL,
        lambda: calcular_serie_mensual(_spreadsheet(), RENDICION_OBJETIVO_BASE)
    )


def _padron() -> dict:
    return cached('padron', PADRON_CACHE_TTL, lambda: leer_padron(gc, SHEETS_ID))


def _con_formato(metricas: dict) -> dict:
    resultado = {k: v for k, v in metricas.items() if not k.startswith('_')}
    for campo in _CAMPOS_MONETARIOS:
        resultado[f'{campo}_fmt'] = format_pesos(metricas[campo])
    return resultado


class LoginBody(BaseModel):
    password: str


@app.post('/api/login')
async def login(body: LoginBody):
    import hmac
    if not DASHBOARD_PASSWORD or not hmac.compare_digest(body.password, DASHBOARD_PASSWORD):
        raise HTTPException(status_code=401, detail="Contraseña inválida")
    return {'ok': True}


@app.get('/api/meses', dependencies=[Depends(require_auth)])
async def meses():
    return [
        {'mes': mes, 'anio': anio, 'titulo': titulo}
        for mes, anio, titulo in listar_meses_ingresos(_spreadsheet())
    ]


@app.get('/api/dashboard', dependencies=[Depends(require_auth)])
async def dashboard(mes: Optional[str] = None, anio: Optional[int] = None):
    hoy = datetime.date.today()
    mes = (mes or _nombre_mes_actual(hoy)).strip().upper()
    anio = anio or hoy.year
    titulo = mes_sheet_title(mes, anio)

    serie = _serie_mensual()
    metricas = serie.get(titulo)
    if metricas is None:
        raise HTTPException(status_code=404, detail=f"No hay datos para '{titulo}'.")

    respuesta = _con_formato(metricas)
    respuesta['cocheras'] = estado_cocheras(metricas['_ingresos_raw'], _padron())
    return respuesta


@app.get('/api/gastos', dependencies=[Depends(require_auth)])
async def gastos(mes: Optional[str] = None, anio: Optional[int] = None):
    hoy = datetime.date.today()
    mes = (mes or _nombre_mes_actual(hoy)).strip().upper()
    anio = anio or hoy.year
    titulo = gastos_sheet_title(mes, anio)

    filas = leer_gastos(_spreadsheet(), titulo)
    return [
        {**g, 'monto_fmt': format_pesos(g['monto'])}
        for g in filas
    ]


@app.get('/api/health')
async def health():
    return {'status': 'ok'}


_MESES_ES = [
    'ENERO', 'FEBRERO', 'MARZO', 'ABRIL', 'MAYO', 'JUNIO',
    'JULIO', 'AGOSTO', 'SEPTIEMBRE', 'OCTUBRE', 'NOVIEMBRE', 'DICIEMBRE'
]


def _nombre_mes_actual(fecha: datetime.date) -> str:
    return _MESES_ES[fecha.month - 1]


# ─── Estáticos (PWA) ────────────────────────────────────────────────────────
app.mount('/static', StaticFiles(directory=STATIC_DIR), name='static')


@app.get('/')
async def index():
    return FileResponse(STATIC_DIR / 'index.html')


@app.get('/manifest.json')
async def manifest():
    return FileResponse(STATIC_DIR / 'manifest.json')


@app.get('/sw.js')
async def service_worker():
    return FileResponse(STATIC_DIR / 'sw.js', media_type='application/javascript')
