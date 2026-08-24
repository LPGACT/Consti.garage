# bot.py — Bot de registro de pagos para playa de estacionamiento
#
# Formatos de caption:
#   Sin ing. brutos:  Juan García, 5, JUNIO
#   Con ing. brutos:  Juan García, 5, JUNIO, IB

import os
import re
import json
import logging
import tempfile
import datetime
from typing import Optional
from dotenv import load_dotenv

import google.generativeai as genai
import gspread
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes
)
from PIL import Image

from sheets_common import (
    build_gspread_client, format_pesos, ING_BRUTOS_PCT, MESES_ORDEN,
    HEADER_ROW, GASTOS_HEADER_ROW, PADRON_SHEET_TITLE,
    mes_sheet_title, gastos_sheet_title,
)
from dashboard.padron import leer_padron
from dashboard.metrics import leer_ingresos, estado_cocheras

# En local, los secretos viven fuera de la carpeta del proyecto (no sincronizada
# por OneDrive/git). En Render no existe esa carpeta y load_dotenv() no hace nada,
# por lo que se usan las variables de entorno reales del servicio.
load_dotenv(os.path.join(os.path.expanduser('~'), 'secrets', '.env'))

# ─── Variables de entorno ─────────────────────────────────────────────────────
TELEGRAM_TOKEN  = os.getenv('TELEGRAM_TOKEN')
GEMINI_API_KEY  = os.getenv('GEMINI_API_KEY')
SHEETS_ID       = os.getenv('GOOGLE_SHEETS_ID')
ALLOWED_USER_ID = int(os.getenv('ALLOWED_USER_ID', 0))
WEBHOOK_URL     = os.getenv('WEBHOOK_URL', '')
WEBHOOK_SECRET  = os.getenv('WEBHOOK_SECRET', '')
PORT            = int(os.getenv('PORT', 8000))

# Precios para el reporte mensual de cocheras pendientes — actualizar cuando
# cambie el precio (no afecta ningún cálculo de plata ya cobrada, solo esta
# proyección de lo que falta cobrar).
PRECIO_AUTO  = float(os.getenv('PRECIO_AUTO', 150000))
PRECIO_MOTO  = float(os.getenv('PRECIO_MOTO', 95000))
PRECIO_DOBLE = float(os.getenv('PRECIO_DOBLE', 195000))


TZ_ARGENTINA = datetime.timezone(datetime.timedelta(hours=-3))


def hoy() -> str:
    """Fecha de hoy en formato DD/MM/YYYY (hora Argentina, no la del servidor).
    Render corre en UTC — sin este offset, cualquier carga entre las 21:00 y
    las 23:59 hora Argentina quedaba fechada al día siguiente en el Sheet."""
    return datetime.datetime.now(TZ_ARGENTINA).strftime('%d/%m/%Y')


# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format='%(asctime)s — %(levelname)s — %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Gemini ───────────────────────────────────────────────────────────────────
genai.configure(api_key=GEMINI_API_KEY)
gemini = genai.GenerativeModel('gemini-2.5-flash')

GEMINI_PROMPT = """Sos un asistente experto en comprobantes de pago argentinos.
Analizá este comprobante y extraé exactamente:
1. El monto total transferido. Los comprobantes argentinos usan punto para miles y coma para decimales
   (ejemplo: $140.000,00 = 140000.00). Devolvé siempre el número con punto decimal, sin separador de miles.
2. El tipo de pago: exactamente "Mercado Pago" si es de Mercado Pago, o "Transferencia" si es bancaria.
3. La fecha de la transacción en formato DD/MM/YYYY.

Respondé ÚNICAMENTE con JSON válido, sin markdown, sin texto adicional:
{"monto": 140000.00, "tipo_pago": "Transferencia", "fecha": "15/06/2025"}"""


def extract_from_comprobante(file_path: str, mime_type: str) -> dict:
    """Usa Gemini Flash para extraer monto, tipo y fecha del comprobante."""
    if mime_type == 'application/pdf':
        try:
            uploaded = genai.upload_file(file_path, mime_type='application/pdf')
        except Exception as e:
            # El error de subida de PDF de la librería de Gemini incluye la
            # API key en la URL (?key=...) — nunca se debe reenviar tal cual
            # al chat de Telegram. Se loguea completo acá (server-side, no
            # llega al usuario) y se reemplaza por un mensaje genérico.
            logger.error(f"Error subiendo PDF a Gemini: {e}")
            raise RuntimeError(
                "No pude subir el PDF a Gemini. Probá con una foto en su lugar, "
                "o reintentá en unos minutos."
            ) from None
        try:
            response = gemini.generate_content([GEMINI_PROMPT, uploaded])
        finally:
            genai.delete_file(uploaded.name)
    else:
        img = Image.open(file_path)
        response = gemini.generate_content([GEMINI_PROMPT, img])

    text = response.text.strip()
    text = re.sub(r'```(?:json)?\n?|\n?```', '', text).strip()
    data = json.loads(text)

    # Gemini a veces devuelve el monto como texto ("140000.00") en vez de
    # número — se acepta cualquiera de las dos formas, siempre que sea
    # convertible a número real; si no lo es, se rechaza con un error claro
    # en vez de guardar un dato que rompe el =SUM() de la hoja en silencio.
    try:
        data['monto'] = float(data['monto'])
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"monto inválido en la respuesta de Gemini: {data.get('monto')!r}") from None

    return data


_MARKDOWN_ESPECIALES = re.compile(r'([_*`\[])')


def escapar_markdown(texto) -> str:
    """Escapa los caracteres especiales del Markdown (legado) de Telegram
    (_, *, `, [) en texto libre tipeado por el operador (nombre, categoría,
    descripción) antes de interpolarlo en un mensaje con parse_mode='Markdown'
    — así un nombre como "Juan_Perez" no rompe el parseo del mensaje de
    confirmación (antes dependía solo del reintento en texto plano de
    responder_con_reintento; esto evita tener que llegar a ese caso)."""
    return _MARKDOWN_ESPECIALES.sub(r'\\\1', str(texto))


async def responder_con_reintento(message, texto_principal: str, texto_fallback: str, **kwargs):
    """Manda la confirmación con formato (Markdown); si falla (ej. un caracter
    especial de Markdown en un nombre, un blip de red), reintenta con un
    mensaje simple en texto plano — así el usuario siempre se entera de que
    el dato ya se guardó, en vez de quedarse sin ninguna respuesta creyendo
    que falló y recargando el mismo pago por las dudas."""
    try:
        await message.reply_text(texto_principal, **kwargs)
    except Exception as e:
        logger.error(f"Falló el mensaje de confirmación con formato, reintentando en texto plano: {e}")
        try:
            await message.reply_text(texto_fallback)
        except Exception as e2:
            logger.error(f"También falló el mensaje de confirmación de respaldo: {e2}")


# ─── Google Sheets ────────────────────────────────────────────────────────────
gc = build_gspread_client()


def get_or_create_sheet(mes: str) -> gspread.Worksheet:
    """Obtiene o crea la hoja del mes (con año, ej. 'JULIO 2026'). Si la crea,
    agrega encabezados y resumen."""
    titulo = mes_sheet_title(mes)
    spreadsheet = gc.open_by_key(SHEETS_ID)
    try:
        ws = spreadsheet.worksheet(titulo)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=titulo, rows=500, cols=12)

        # ── Encabezados de tabla ──────────────────────────────────────────────
        ws.append_row(HEADER_ROW)
        ws.format('A1:F1', {'textFormat': {'bold': True}})

        # ── Resumen automático (columnas G-H) ─────────────────────────────────
        resumen = [
            ['TOTAL BRUTO',           '=SUM(D2:D500)'],
            ['DESCUENTO ING. BRUTOS', '=SUM(E2:E500)'],
            ['TOTAL NETO',            '=H1-H2'],
        ]
        ws.update('G1:H3', resumen)
        ws.format('G1:G3', {'textFormat': {'bold': True}})
        ws.format('H1', {
            'backgroundColor': {'red': 0.18, 'green': 0.62, 'blue': 0.18},
            'textFormat': {'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}, 'bold': True}
        })
        ws.format('H2', {
            'backgroundColor': {'red': 0.85, 'green': 0.2, 'blue': 0.2},
            'textFormat': {'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}, 'bold': True}
        })
        ws.format('H3', {
            'backgroundColor': {'red': 0.18, 'green': 0.44, 'blue': 0.78},
            'textFormat': {'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}, 'bold': True}
        })

        logger.info(f"Hoja '{titulo}' creada con resumen.")
    return ws


def get_or_create_gastos_sheet(mes: str) -> gspread.Worksheet:
    """Obtiene o crea la hoja de gastos del mes. Separada de la de ingresos
    para no romper los SUM() de la de ingresos, pero con un resumen que
    cruza ambas: total ingresos (neto de Ing. Brutos), total gastos y
    resultado neto del mes."""
    get_or_create_sheet(mes)  # asegura que la hoja de ingresos exista antes de referenciarla
    titulo_ingresos = mes_sheet_title(mes)
    titulo = gastos_sheet_title(mes)
    spreadsheet = gc.open_by_key(SHEETS_ID)
    try:
        ws = spreadsheet.worksheet(titulo)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=titulo, rows=500, cols=8)

        ws.append_row(GASTOS_HEADER_ROW)
        ws.format('A1:D1', {'textFormat': {'bold': True}})

        # ── Resumen (columnas F-G): ingresos vs. gastos vs. resultado ─────────
        resumen = [
            ['TOTAL INGRESOS (neto)', f"='{titulo_ingresos}'!H3"],
            ['TOTAL GASTOS',          '=SUM(C2:C500)'],
            ['RESULTADO NETO',        '=G1-G2'],
        ]
        ws.update('F1:G3', resumen)
        ws.format('F1:F3', {'textFormat': {'bold': True}})
        ws.format('G1', {
            'backgroundColor': {'red': 0.18, 'green': 0.62, 'blue': 0.18},
            'textFormat': {'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}, 'bold': True}
        })
        ws.format('G2', {
            'backgroundColor': {'red': 0.85, 'green': 0.2, 'blue': 0.2},
            'textFormat': {'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}, 'bold': True}
        })
        ws.format('G3', {
            'backgroundColor': {'red': 0.18, 'green': 0.44, 'blue': 0.78},
            'textFormat': {'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}, 'bold': True}
        })

        logger.info(f"Hoja '{titulo}' creada con resumen.")
    return ws


# ─── Parsers de mensajes ──────────────────────────────────────────────────────
COCHERAS_ESPECIALES = {'MOTO', 'DOBLE'}


def parse_cochera(raw: str) -> Optional[object]:
    """Devuelve el número de cochera (int) o 'MOTO'/'DOBLE', o None si no es válido.
    Exige que el campo entero sea el número (no que lo contenga) — así
    "5 IB" sin la coma antes de IB se rechaza en vez de leerse como cochera 5."""
    raw = raw.strip()
    raw_upper = raw.upper()
    if raw_upper in COCHERAS_ESPECIALES:
        return raw_upper
    if not re.fullmatch(r'\d+', raw):
        return None
    return int(raw)


def parse_cocheras(raw: str) -> Optional[list]:
    """Una o más cocheras en un mismo pago (ej. un cliente con 2 cocheras que
    paga todo junto con una sola transferencia). Se escriben separadas por
    ';' — '5;12;23' o '5;MOTO' — porque la coma ya es el separador entre
    Nombre/Cochera/Mes. Devuelve la lista de valores validados (cada uno
    pasado por parse_cochera), o None si alguno no es válido."""
    tokens = [t.strip() for t in raw.split(';')]
    valores = []
    for t in tokens:
        v = parse_cochera(t)
        if v is None:
            return None
        valores.append(v)
    return valores if valores else None


def parse_mes(raw: str) -> Optional[str]:
    """Valida que sea un mes real (ENERO..DICIEMBRE). Un typo de mes sin
    validar crearía una hoja nueva fragmentada en el Sheet sin avisar a nadie."""
    mes = raw.strip().upper()
    return mes if mes in MESES_ORDEN else None


def parse_monto(raw: str) -> Optional[float]:
    """Solo acepta números planos, sin separador de miles (15000, no 15.000),
    porque la coma ya se usa como separador de campos en estos mensajes."""
    raw = raw.strip()
    if not re.fullmatch(r'\d+(\.\d{1,2})?', raw):
        return None
    return float(raw)


def parse_caption(caption: str) -> Optional[dict]:
    """
    Formatos válidos:
      Juan García, 5, JUNIO          → cochera numerada, sin ing. brutos
      Juan García, MOTO, JUNIO       → moto, sin ing. brutos
      Juan García, DOBLE, JUNIO      → doble, sin ing. brutos
      Juan García, 5, JUNIO, IB      → cochera numerada, con ing. brutos
      Juan García, MOTO, JUNIO, IB   → moto, con ing. brutos
      Juan García, 5;12;23, JUNIO    → un pago cubre varias cocheras (se
                                        guarda en el Sheet como "5 y 12 y 23")
    """
    parts = [p.strip() for p in caption.split(',')]
    if len(parts) not in (3, 4):
        return None

    nombre, cocheras_raw, mes_raw = parts[0], parts[1], parts[2]
    ing_brutos = len(parts) == 4 and parts[3].upper() == 'IB'

    if not nombre:
        return None

    mes = parse_mes(mes_raw)
    if mes is None:
        return None

    cocheras = parse_cocheras(cocheras_raw)
    if cocheras is None:
        return None

    # Una sola cochera se guarda tal cual (int, o 'MOTO'/'DOBLE') para no
    # tocar el formato ya usado en filas existentes. Varias se guardan
    # unidas con ' y ', mismo estilo que ya usa PADRON para las dobles.
    cochera = cocheras[0] if len(cocheras) == 1 else ' y '.join(str(c) for c in cocheras)

    return {
        'nombre':     nombre,
        'cochera':    cochera,
        'mes':        mes,
        'ing_brutos': ing_brutos
    }


def parse_efectivo_message(text: str) -> Optional[dict]:
    """
    Formato:
      EFECTIVO, Mes
      Cochera, Nombre, Monto
      Cochera, Nombre, Monto
      ...
    Devuelve {'mes': str, 'filas': [...], 'errores': [...]}, o None si ni
    siquiera la primera línea tiene el formato esperado.
    """
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if not lines:
        return None

    header = [p.strip() for p in lines[0].split(',')]
    if len(header) < 2 or header[0].upper() != 'EFECTIVO':
        return None
    mes = parse_mes(header[1])
    if mes is None:
        return None

    filas = []
    errores = []
    for i, line in enumerate(lines[1:], start=2):
        parts = [p.strip() for p in line.split(',')]
        if len(parts) != 3:
            errores.append(f"Línea {i}: \"{line}\" — esperaba Cochera, Nombre, Monto")
            continue

        cochera_raw, nombre, monto_raw = parts

        cochera = parse_cochera(cochera_raw)
        if cochera is None:
            errores.append(f"Línea {i}: cochera inválida \"{cochera_raw}\"")
            continue

        if not nombre:
            errores.append(f"Línea {i}: falta el nombre")
            continue

        monto = parse_monto(monto_raw)
        if monto is None:
            errores.append(f"Línea {i}: monto inválido \"{monto_raw}\" (usá solo números, sin puntos de miles, ej. 15000)")
            continue

        filas.append({'cochera': cochera, 'nombre': nombre, 'monto': monto})

    return {'mes': mes, 'filas': filas, 'errores': errores}


def parse_gastos_message(text: str) -> Optional[dict]:
    """
    Formato:
      GASTOS, Mes, Categoría, Monto, Descripción
    """
    parts = [p.strip() for p in text.strip().split(',', 4)]
    if len(parts) != 5 or parts[0].upper() != 'GASTOS':
        return None

    _, mes_raw, categoria, monto_raw, descripcion = parts
    if not categoria or not descripcion:
        return None

    mes = parse_mes(mes_raw)
    if mes is None:
        return None

    monto = parse_monto(monto_raw)
    if monto is None:
        return None

    return {
        'mes':         mes,
        'categoria':   categoria.upper(),
        'monto':       monto,
        'descripcion': descripcion
    }


def parse_cambio_message(text: str) -> Optional[dict]:
    """
    Formato:
      CAMBIO, Nro, NombreNuevo
    Sirve tanto para cocheras de auto/doble como para motos: ambas tienen
    columna NRO COCHERA en el padrón, aunque los captions de pago de motos
    no usen ese número (se matchean por nombre).
    """
    parts = [p.strip() for p in text.strip().split(',', 2)]
    if len(parts) != 3 or parts[0].upper() != 'CAMBIO':
        return None

    _, nro_raw, nombre_nuevo = parts
    if not re.fullmatch(r'\d+', nro_raw) or not nombre_nuevo:
        return None

    return {'nro': int(nro_raw), 'nombre_nuevo': nombre_nuevo}


# ─── Handlers ─────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🅿️ *Bot de Registro de Pagos*\n\n"
        "*Transferencia / Mercado Pago* — mandame la imagen o PDF del comprobante con el caption:\n"
        "`Nombre, Cochera, Mes`\n"
        "`Nombre, Cochera, Mes, IB` ← con ing. brutos\n"
        "`Nombre, Cochera;Cochera;Cochera, Mes` ← una transferencia cubre varias cocheras\n"
        "Ejemplo: `Juan García, 5, JUNIO`\n"
        "Ejemplo varias cocheras: `José, 1;2, JUNIO`\n\n"
        "*Efectivo* — mensaje de texto, una línea por cochera:\n"
        "`EFECTIVO, Mes`\n"
        "`Cochera, Nombre, Monto`\n"
        "Ejemplo:\n"
        "`EFECTIVO, JUNIO`\n"
        "`5, Juan García, 15000`\n"
        "`12, María López, 15000`\n\n"
        "*Gastos* — mensaje de texto:\n"
        "`GASTOS, Mes, Categoría, Monto, Descripción`\n"
        "Ejemplo: `GASTOS, JUNIO, SUELDOS, 80000, Sueldo Carlos`\n\n"
        "*Cambio de dueño de cochera* — mensaje de texto:\n"
        "`CAMBIO, Nro, NombreNuevo`\n"
        "Ejemplo: `CAMBIO, 34, Pedro Gómez`\n\n"
        "*Cocheras pendientes de este mes* — mandá `PENDIENTES` como mensaje "
        "de texto (también se manda solo el día 28 de cada mes a las 10hs).",
        parse_mode='Markdown'
    )


async def handle_comprobante(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message

    if ALLOWED_USER_ID and update.effective_user.id != ALLOWED_USER_ID:
        await message.reply_text("🚫 No tenés permisos para usar este bot.")
        return

    caption = message.caption or ''
    data = parse_caption(caption)

    if not data:
        await message.reply_text(
            "❌ *Formato incorrecto*\n\n"
            "Sin ing. brutos: `Nombre, Cochera, Mes`\n"
            "Con ing. brutos: `Nombre, Cochera, Mes, IB`\n"
            "Varias cocheras: `Nombre, Cochera;Cochera, Mes`\n\n"
            "Ejemplo: `Juan García, 5, JUNIO, IB`",
            parse_mode='Markdown'
        )
        return

    mime_type   = 'image/jpeg'
    file_source = None

    if message.photo:
        file_source = message.photo[-1]
    elif message.document:
        doc       = message.document
        mime_type = 'application/pdf' if doc.mime_type and 'pdf' in doc.mime_type \
                    else (doc.mime_type or 'image/jpeg')
        file_source = doc
    else:
        await message.reply_text("❌ Necesito una imagen o PDF del comprobante.")
        return

    status   = await message.reply_text("⏳ Leyendo comprobante...")
    suffix   = '.pdf' if mime_type == 'application/pdf' else '.jpg'
    tmp_path = tempfile.mktemp(suffix=suffix)

    try:
        tg_file = await file_source.get_file()
        await tg_file.download_to_drive(tmp_path)

        payment = extract_from_comprobante(tmp_path, mime_type)

        monto        = payment['monto']
        descuento_ib = round(monto * ING_BRUTOS_PCT, 2) if data['ing_brutos'] else ''
        monto_neto   = round(monto - descuento_ib, 2)   if data['ing_brutos'] else monto

        ws = get_or_create_sheet(data['mes'])
        ws.append_row([
            payment['fecha'],
            data['cochera'],
            data['nombre'],
            monto,
            descuento_ib,
            payment['tipo_pago']
        ], table_range='A1:F1')

        ib_line = (
            f"\n📊 Ing. Brutos: -{format_pesos(descuento_ib)}\n"
            f"💵 Neto: {format_pesos(monto_neto)}"
        ) if data['ing_brutos'] else ""

        await status.delete()
        await responder_con_reintento(
            message,
            f"✅ *Registrado — {data['mes']}*\n\n"
            f"👤 {escapar_markdown(data['nombre'])}\n"
            f"🅿️  Cochera {data['cochera']}\n"
            f"💰 Bruto: {format_pesos(monto)}{ib_line}\n"
            f"📅 {payment['fecha']}\n"
            f"💳 {payment['tipo_pago']}",
            f"✅ Registrado — {data['mes']}: {data['nombre']}, cochera {data['cochera']}, {format_pesos(monto)}",
            parse_mode='Markdown'
        )

    except json.JSONDecodeError as e:
        logger.error(f"JSONDecodeError al parsear respuesta de Gemini: {e}")
        await status.delete()
        await message.reply_text(
            "❌ *No pude leer el comprobante*\n\n"
            "¿La imagen es clara? ¿Es un comprobante de pago?\n\n"
            f"`{type(e).__name__}: {e}`",
            parse_mode='Markdown'
        )
    except (ValueError, KeyError) as e:
        logger.error(f"Dato inválido en la respuesta de Gemini: {e}")
        await status.delete()
        await message.reply_text(
            "❌ *No pude leer el comprobante*\n\n"
            "El monto que devolvió Gemini no es válido. ¿La imagen es clara?\n\n"
            f"`{type(e).__name__}: {e}`",
            parse_mode='Markdown'
        )
    except gspread.exceptions.APIError as e:
        logger.error(f"Google Sheets APIError: {e}")
        await status.delete()
        await message.reply_text(
            "❌ *Error al guardar en Google Sheets*\n\n"
            f"`{type(e).__name__}: {e}`",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error inesperado: {e}", exc_info=True)
        await status.delete()
        await message.reply_text(
            "❌ *Error inesperado*\n\n"
            f"`{type(e).__name__}: {e}`",
            parse_mode='Markdown'
        )
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


async def handle_efectivo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    data = message.text and parse_efectivo_message(message.text)

    if not data:
        await message.reply_text(
            "❌ *Formato incorrecto*\n\n"
            "Primera línea: `EFECTIVO, Mes`\n"
            "Una línea por cochera: `Cochera, Nombre, Monto`\n\n"
            "Ejemplo:\n"
            "`EFECTIVO, JUNIO`\n"
            "`5, Juan García, 15000`\n"
            "`12, María López, 15000`",
            parse_mode='Markdown'
        )
        return

    if not data['filas']:
        await message.reply_text(
            "❌ No reconocí ninguna línea de cochera válida.\n\n"
            + "\n".join(data['errores']),
        )
        return

    try:
        ws = get_or_create_sheet(data['mes'])
        fecha = hoy()
        ws.append_rows([
            [fecha, fila['cochera'], fila['nombre'], fila['monto'], '', 'Efectivo']
            for fila in data['filas']
        ], table_range='A1:F1')

        total = sum(fila['monto'] for fila in data['filas'])
        detalle = "\n".join(
            f"🅿️ Cochera {fila['cochera']} — {escapar_markdown(fila['nombre'])} — {format_pesos(fila['monto'])}"
            for fila in data['filas']
        )

        resumen = (
            f"✅ *Efectivo cargado — {data['mes']}*\n\n"
            f"{detalle}\n\n"
            f"💰 Total: {format_pesos(total)} ({len(data['filas'])} cocheras)"
        )
        if data['errores']:
            resumen += "\n\n⚠️ *Líneas no cargadas:*\n" + "\n".join(data['errores'])

        await responder_con_reintento(
            message, resumen,
            f"✅ Efectivo cargado — {data['mes']}: {format_pesos(total)} ({len(data['filas'])} cocheras)",
            parse_mode='Markdown'
        )

    except gspread.exceptions.APIError as e:
        logger.error(f"Google Sheets APIError (efectivo): {e}")
        await message.reply_text(
            f"❌ *Error al guardar en Google Sheets*\n\n`{type(e).__name__}: {e}`",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error inesperado (efectivo): {e}", exc_info=True)
        await message.reply_text(
            f"❌ *Error inesperado*\n\n`{type(e).__name__}: {e}`",
            parse_mode='Markdown'
        )


async def handle_gastos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    data = message.text and parse_gastos_message(message.text)

    if not data:
        await message.reply_text(
            "❌ *Formato incorrecto*\n\n"
            "`GASTOS, Mes, Categoría, Monto, Descripción`\n\n"
            "Ejemplo: `GASTOS, JUNIO, SUELDOS, 80000, Sueldo Carlos`",
            parse_mode='Markdown'
        )
        return

    try:
        ws = get_or_create_gastos_sheet(data['mes'])
        ws.append_row([hoy(), data['categoria'], data['monto'], data['descripcion']], table_range='A1:D1')

        await responder_con_reintento(
            message,
            f"✅ *Gasto registrado — {data['mes']}*\n\n"
            f"🏷️ {escapar_markdown(data['categoria'])}\n"
            f"💸 {format_pesos(data['monto'])}\n"
            f"📝 {escapar_markdown(data['descripcion'])}",
            f"✅ Gasto registrado — {data['mes']}: {data['categoria']}, {format_pesos(data['monto'])}",
            parse_mode='Markdown'
        )

    except gspread.exceptions.APIError as e:
        logger.error(f"Google Sheets APIError (gastos): {e}")
        await message.reply_text(
            f"❌ *Error al guardar en Google Sheets*\n\n`{type(e).__name__}: {e}`",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error inesperado (gastos): {e}", exc_info=True)
        await message.reply_text(
            f"❌ *Error inesperado*\n\n`{type(e).__name__}: {e}`",
            parse_mode='Markdown'
        )


async def handle_cambio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reasigna el dueño de una cochera (auto o moto) en la hoja PADRON,
    buscando el número tanto en la tabla de autos (columna A) como en la
    de motos (columna G) — ambas tienen NRO COCHERA propio."""
    message = update.message
    data = message.text and parse_cambio_message(message.text)

    if not data:
        await message.reply_text(
            "❌ *Formato incorrecto*\n\n"
            "`CAMBIO, Nro, NombreNuevo`\n\n"
            "Ejemplo: `CAMBIO, 34, Pedro Gómez`",
            parse_mode='Markdown'
        )
        return

    try:
        ws = gc.open_by_key(SHEETS_ID).worksheet(PADRON_SHEET_TITLE)
        pattern = re.compile(rf'^{data["nro"]}$')

        cell = ws.find(pattern, in_column=1)   # columna A: NRO autos/dobles
        col_nombre = 2                          # columna B: NOMBRE autos/dobles
        if cell is None or cell.row == 1:
            cell = ws.find(pattern, in_column=8)  # columna H: NRO motos
            col_nombre = 9                        # columna I: NOMBRE motos

        if cell is None or cell.row == 1:
            await message.reply_text(f"❌ No encontré la cochera {data['nro']} en el padrón.")
            return

        nombre_viejo = ws.cell(cell.row, col_nombre).value or '(vacía)'
        ws.update_cell(cell.row, col_nombre, data['nombre_nuevo'])

        await responder_con_reintento(
            message,
            f"🔄 *Cochera {data['nro']}*\n{escapar_markdown(nombre_viejo)} → {escapar_markdown(data['nombre_nuevo'])}",
            f"🔄 Cochera {data['nro']}: {nombre_viejo} -> {data['nombre_nuevo']}",
            parse_mode='Markdown'
        )

    except gspread.exceptions.APIError as e:
        logger.error(f"Google Sheets APIError (cambio): {e}")
        await message.reply_text(
            f"❌ *Error al guardar en Google Sheets*\n\n`{type(e).__name__}: {e}`",
            parse_mode='Markdown'
        )
    except gspread.exceptions.WorksheetNotFound:
        await message.reply_text(
            f"❌ No encontré la hoja '{PADRON_SHEET_TITLE}'. ¿Ya la creaste en el spreadsheet?"
        )
    except Exception as e:
        logger.error(f"Error inesperado (cambio): {e}", exc_info=True)
        await message.reply_text(
            f"❌ *Error inesperado*\n\n`{type(e).__name__}: {e}`",
            parse_mode='Markdown'
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enruta mensajes de texto sin '/' según la primera palabra: EFECTIVO,
    GASTOS o CAMBIO. Cualquier otro texto se ignora — evita responderle a
    charla suelta."""
    message = update.message

    if ALLOWED_USER_ID and update.effective_user.id != ALLOWED_USER_ID:
        await message.reply_text("🚫 No tenés permisos para usar este bot.")
        return

    primera_palabra = message.text.strip().split(',')[0].strip().upper()

    if primera_palabra == 'EFECTIVO':
        await handle_efectivo(update, context)
    elif primera_palabra == 'GASTOS':
        await handle_gastos(update, context)
    elif primera_palabra == 'CAMBIO':
        await handle_cambio(update, context)
    elif primera_palabra == 'PENDIENTES':
        await handle_pendientes(update, context)


# ─── Reporte mensual de cocheras pendientes ────────────────────────────────────
def _armar_lineas_pendientes(padron: dict, ingresos: list) -> tuple:
    """Devuelve (lineas, total) — una línea 'Nro, Nombre, Tipo, Monto' por
    cada cochera OCUPADA que todavía no pagó este mes. Las dobles se listan
    como un solo par ('23 y 24') con el precio del par, no dos líneas
    separadas. Las cocheras vacías no aparecen — no hay a quién cobrarle."""
    cocheras = estado_cocheras(ingresos, padron)
    lineas = []
    total = 0.0
    vistos_dobles = set()

    for c in cocheras['pendientes']:
        if c['vacia']:
            continue

        if c['tipo'] == 'auto' and c['pareja']:
            par = tuple(sorted((c['nro'], c['pareja'])))
            if par in vistos_dobles:
                continue
            vistos_dobles.add(par)
            nro_texto, tipo_texto, monto = f"{par[0]} y {par[1]}", 'DOBLE', PRECIO_DOBLE
        elif c['tipo'] == 'auto':
            nro_texto, tipo_texto, monto = str(c['nro']), 'AUTO', PRECIO_AUTO
        else:
            nro_texto, tipo_texto, monto = str(c['nro']), 'MOTO', PRECIO_MOTO

        lineas.append(f"{nro_texto}, {escapar_markdown(c['nombre'])}, {tipo_texto}, {format_pesos(monto)}")
        total += monto

    return lineas, total


async def _enviar_reporte_pendientes(bot):
    """Arma y manda el reporte de cocheras pendientes del mes actual al chat
    de ALLOWED_USER_ID. Usado tanto por el job mensual automático como por
    el comando manual PENDIENTES (para poder probarlo sin esperar al día 28)."""
    try:
        mes_actual = MESES_ORDEN[datetime.datetime.now(TZ_ARGENTINA).month - 1]
        spreadsheet = gc.open_by_key(SHEETS_ID)
        padron = leer_padron(gc, SHEETS_ID)
        ingresos = leer_ingresos(spreadsheet, mes_sheet_title(mes_actual))

        lineas, total = _armar_lineas_pendientes(padron, ingresos)

        if not lineas:
            await bot.send_message(
                chat_id=ALLOWED_USER_ID,
                text=f"✅ *Cocheras pendientes — {mes_actual}*\n\nNo queda nadie sin cobrar. 🎉",
                parse_mode='Markdown'
            )
            return

        # Telegram corta mensajes de más de 4096 caracteres — se parte en
        # varios envíos en vez de arriesgarse a que falle el de un solo bloque.
        pie = f"\n\n💰 *Total pendiente: {format_pesos(total)}*"
        bloque = f"📋 *Cocheras pendientes — {mes_actual}*\n\n"
        for linea in lineas:
            if len(bloque) + len(linea) + 1 > 3800:
                await bot.send_message(chat_id=ALLOWED_USER_ID, text=bloque, parse_mode='Markdown')
                bloque = ''
            bloque += linea + '\n'
        bloque += pie
        await bot.send_message(chat_id=ALLOWED_USER_ID, text=bloque, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error armando el reporte mensual de pendientes: {e}", exc_info=True)
        try:
            await bot.send_message(
                chat_id=ALLOWED_USER_ID,
                text=f"❌ No pude armar el reporte mensual de cocheras pendientes.\n`{type(e).__name__}: {e}`",
                parse_mode='Markdown'
            )
        except Exception:
            pass


async def reporte_pendientes_mensual(context: ContextTypes.DEFAULT_TYPE):
    """Job mensual (día 28, 10:00 hora Argentina)."""
    await _enviar_reporte_pendientes(context.bot)


async def handle_pendientes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando manual — mismo reporte que el job mensual, para probarlo o
    consultarlo cuando se quiera, sin esperar al día 28."""
    if ALLOWED_USER_ID and update.effective_user.id != ALLOWED_USER_ID:
        await update.message.reply_text("🚫 No tenés permisos para usar este bot.")
        return
    await _enviar_reporte_pendientes(context.bot)


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('start', cmd_start))
    app.add_handler(CommandHandler('help',  cmd_start))
    app.add_handler(MessageHandler(
        filters.PHOTO | filters.Document.ALL,
        handle_comprobante
    ))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_text
    ))

    if app.job_queue and ALLOWED_USER_ID:
        app.job_queue.run_monthly(
            reporte_pendientes_mensual,
            when=datetime.time(10, 0, tzinfo=TZ_ARGENTINA),
            day=28,
        )
        logger.info("Reporte mensual de cocheras pendientes programado: día 28, 10:00 hora Argentina.")
    else:
        logger.warning(
            "No se pudo programar el reporte mensual de pendientes "
            "(falta la dependencia job-queue o ALLOWED_USER_ID)."
        )

    if WEBHOOK_URL:
        if not WEBHOOK_SECRET:
            logger.warning(
                "WEBHOOK_SECRET no está configurado — cualquiera que consiga la URL del "
                "webhook puede mandar updates falsos sin pasar por Telegram. Configurá "
                "WEBHOOK_SECRET en las variables de entorno."
            )
        logger.info(f"Modo webhook → {WEBHOOK_URL}")
        app.run_webhook(
            listen='0.0.0.0',
            port=PORT,
            url_path='webhook',
            webhook_url=f'{WEBHOOK_URL}/webhook',
            secret_token=WEBHOOK_SECRET or None
        )
    else:
        logger.info("Modo polling (local)")
        app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
