# bot.py — Bot de registro de pagos para playa de estacionamiento
#
# Formatos de caption:
#   Sin ing. brutos:  Juan García | 5 | JUNIO
#   Con ing. brutos:  Juan García | 5 | JUNIO | IB

import os
import re
import json
import logging
import tempfile
from typing import Optional
from dotenv import load_dotenv

import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes
)
from PIL import Image

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
PORT            = int(os.getenv('PORT', 8000))

ING_BRUTOS_PCT = 0.025  # 2.5%

HEADER_ROW = ['Fecha', 'Cochera', 'Nombre', 'Monto', 'Ing. Brutos (2.5%)', 'Tipo de Pago']


def format_pesos(amount: float) -> str:
    """Formatea en pesos argentinos: $140.000,00"""
    s = f"{amount:,.2f}"                                     # "140,000.00"
    return "$" + s.replace(',', 'X').replace('.', ',').replace('X', '.')


# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format='%(asctime)s — %(levelname)s — %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Gemini ───────────────────────────────────────────────────────────────────
genai.configure(api_key=GEMINI_API_KEY)
gemini = genai.GenerativeModel('gemini-1.5-flash')

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
        uploaded = genai.upload_file(file_path, mime_type='application/pdf')
        try:
            response = gemini.generate_content([GEMINI_PROMPT, uploaded])
        finally:
            genai.delete_file(uploaded.name)
    else:
        img = Image.open(file_path)
        response = gemini.generate_content([GEMINI_PROMPT, img])

    text = response.text.strip()
    text = re.sub(r'```(?:json)?\n?|\n?```', '', text).strip()
    return json.loads(text)


# ─── Google Sheets ────────────────────────────────────────────────────────────
def build_gspread_client() -> gspread.Client:
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


gc = build_gspread_client()


def get_or_create_sheet(mes: str) -> gspread.Worksheet:
    """Obtiene o crea la hoja del mes. Si la crea, agrega encabezados y resumen."""
    spreadsheet = gc.open_by_key(SHEETS_ID)
    try:
        ws = spreadsheet.worksheet(mes)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=mes, rows=500, cols=12)

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

        logger.info(f"Hoja '{mes}' creada con resumen.")
    return ws


# ─── Parser de caption ────────────────────────────────────────────────────────
COCHERAS_ESPECIALES = {'MOTO', 'DOBLE'}


def parse_caption(caption: str) -> Optional[dict]:
    """
    Formatos válidos:
      Juan García | 5 | JUNIO          → cochera numerada, sin ing. brutos
      Juan García | MOTO | JUNIO       → moto, sin ing. brutos
      Juan García | DOBLE | JUNIO      → doble, sin ing. brutos
      Juan García | 5 | JUNIO | IB     → cochera numerada, con ing. brutos
      Juan García | MOTO | JUNIO | IB  → moto, con ing. brutos
    """
    parts = [p.strip() for p in caption.split('|')]
    if len(parts) not in (3, 4):
        return None

    nombre, cochera_raw, mes = parts[0], parts[1], parts[2]
    ing_brutos = len(parts) == 4 and parts[3].upper() == 'IB'

    if not nombre or not mes:
        return None

    cochera_upper = cochera_raw.upper()
    if cochera_upper in COCHERAS_ESPECIALES:
        cochera = cochera_upper
    else:
        match = re.search(r'\d+', cochera_raw)
        if not match:
            return None
        cochera = int(match.group())

    return {
        'nombre':     nombre,
        'cochera':    cochera,
        'mes':        mes.upper(),
        'ing_brutos': ing_brutos
    }


# ─── Handlers ─────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🅿️ *Bot de Registro de Pagos*\n\n"
        "Mandame una imagen o PDF del comprobante con el caption:\n\n"
        "`Nombre | Cochera | Mes`\n"
        "`Nombre | Cochera | Mes | IB` ← con ing. brutos\n\n"
        "*Ejemplos:*\n"
        "`Juan García | 5 | JUNIO`\n"
        "`María López | MOTO | JUNIO`\n"
        "`Carlos Díaz | DOBLE | JUNIO | IB`",
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
            "Sin ing. brutos: `Nombre | Cochera | Mes`\n"
            "Con ing. brutos: `Nombre | Cochera | Mes | IB`\n\n"
            "Ejemplo: `Juan García | 5 | JUNIO | IB`",
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
        ])

        ib_line = (
            f"\n📊 Ing. Brutos: -{format_pesos(descuento_ib)}\n"
            f"💵 Neto: {format_pesos(monto_neto)}"
        ) if data['ing_brutos'] else ""

        await status.delete()
        await message.reply_text(
            f"✅ *Registrado — {data['mes']}*\n\n"
            f"👤 {data['nombre']}\n"
            f"🅿️  Cochera {data['cochera']}\n"
            f"💰 Bruto: {format_pesos(monto)}{ib_line}\n"
            f"📅 {payment['fecha']}\n"
            f"💳 {payment['tipo_pago']}",
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


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('start', cmd_start))
    app.add_handler(CommandHandler('help',  cmd_start))
    app.add_handler(MessageHandler(
        filters.PHOTO | filters.Document.ALL,
        handle_comprobante
    ))

    if WEBHOOK_URL:
        logger.info(f"Modo webhook → {WEBHOOK_URL}")
        app.run_webhook(
            listen='0.0.0.0',
            port=PORT,
            url_path='webhook',
            webhook_url=f'{WEBHOOK_URL}/webhook'
        )
    else:
        logger.info("Modo polling (local)")
        app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
