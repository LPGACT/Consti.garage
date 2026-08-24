# dashboard/metrics.py — Fórmulas financieras del dashboard. Todo se deriva
# de las hojas de ingresos/gastos que ya escribe bot.py — no hay ningún
# ledger nuevo que mantener sincronizado.
#
# Reglas de negocio (cerradas con el dueño de la playa, no son supuestos):
#   - La rendición a socios (config. RENDICION_OBJETIVO_BASE, por período)
#     sale SOLO del efectivo, después de pagar los gastos con esa misma
#     plata. Es fija, no depende de cuántas cocheras estén vacías.
#   - Cada mes es independiente: si el efectivo no alcanza para cubrir el
#     objetivo, se entrega lo que haya y listo — el faltante NO se arrastra
#     al objetivo del mes siguiente (antes sí se arrastraba; se sacó a
#     pedido explícito del dueño).
#   - Lo que gana el dueño = todo lo que le transfieren (Transferencia +
#     Mercado Pago, nunca se reparte) + lo que sobra del efectivo después
#     de gastos y rendición de ese mismo mes (nunca negativo).

import datetime
import logging
import re
from typing import Optional

import gspread

from sheets_common import (
    MESES_ORDEN, OBJETIVO_SHEET_TITLE, PADRON_SHEET_TITLE,
    gastos_sheet_title, parse_mes_sheet_title,
)
from dashboard.padron import normaliza_nombre

logger = logging.getLogger(__name__)


def _parse_float(value) -> float:
    if value in (None, ''):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


_EPOCH_SHEETS = datetime.date(1899, 12, 30)


def _normaliza_fecha(valor):
    """Sheets a veces guarda una fecha como número de serie (días desde el
    30/12/1899) en vez de texto 'DD/MM/YYYY' — pasa cuando se tipea la fecha
    directo en la hoja y Google Sheets la autoconvierte a celda tipo Fecha
    (el bot siempre escribe texto, así que esto solo pasa con carga manual).
    Sin esto, el dashboard mostraba el número crudo (ej. '46237') como fecha."""
    if isinstance(valor, (int, float)):
        try:
            return (_EPOCH_SHEETS + datetime.timedelta(days=int(valor))).strftime('%d/%m/%Y')
        except (OverflowError, ValueError):
            return str(valor)
    return valor


_TIPOS_PAGO_CONOCIDOS = {
    'TRANSFERENCIA': 'Transferencia',
    'MERCADO PAGO':  'Mercado Pago',
    'EFECTIVO':      'Efectivo',
}


def _normaliza_tipo_pago(tipo_pago: str) -> Optional[str]:
    """Forma canónica del tipo de pago (case/espacios insensible), o None si
    no matchea ninguno de los tres conocidos. Antes la comparación era exacta
    ('Transferencia' con T mayúscula nomás) — una fila cargada como
    'TRANSFERENCIA' no caía en ningún bucket y esa plata desaparecía en
    silencio de los totales."""
    return _TIPOS_PAGO_CONOCIDOS.get(str(tipo_pago).strip().upper())


def _parse_monto_texto(value: str) -> Optional[float]:
    """Parsea montos con formato de celda, tanto '$9,800,000.00' (miles con
    coma, decimal con punto) como '$9.800.000,00' o '$9.800.000' (convención
    argentina, miles con punto). El último separador (. o ,) se interpreta
    como decimal solo si le siguen 1 o 2 dígitos; si le siguen 3, es un
    separador de miles más (ej. '9.800.000' → 9800000, no 9.800)."""
    texto = re.sub(r'[^\d.,]', '', str(value))
    if not texto:
        return None

    ultimo = max(texto.rfind('.'), texto.rfind(','))
    if ultimo == -1:
        limpio = texto
    else:
        parte_decimal = texto[ultimo + 1:]
        if len(parte_decimal) in (1, 2):
            entero = re.sub(r'[.,]', '', texto[:ultimo])
            limpio = f'{entero}.{parte_decimal}' if entero else f'0.{parte_decimal}'
        else:
            limpio = re.sub(r'[.,]', '', texto)

    try:
        return float(limpio)
    except ValueError:
        return None


def leer_objetivo_por_mes(spreadsheet: gspread.Spreadsheet) -> dict:
    """{(mes, año): objetivo} desde la hoja RENDICION_OBJETIVO_BASE, si existe.
    Cada fila es el objetivo vigente A PARTIR de ese mes (no hace falta una
    fila por mes — solo se agrega una cuando cambia el precio). Filas con
    mes/año o monto ilegible se ignoran con un warning, no rompen el resto."""
    try:
        ws = spreadsheet.worksheet(OBJETIVO_SHEET_TITLE)
    except gspread.WorksheetNotFound:
        return {}

    resultado = {}
    for fila in ws.get_all_values()[1:]:
        if len(fila) < 2 or not fila[0].strip():
            continue
        parsed = parse_mes_sheet_title(fila[0].strip().upper())
        if not parsed:
            logger.warning(f"RENDICION_OBJETIVO_BASE: fila con mes-año ilegible '{fila[0]}', se ignora.")
            continue
        monto = _parse_monto_texto(fila[1])
        if monto is None:
            logger.warning(f"RENDICION_OBJETIVO_BASE: monto ilegible '{fila[1]}' para '{fila[0]}', se ignora.")
            continue
        resultado[parsed] = monto
    return resultado


def leer_ingresos(spreadsheet: gspread.Spreadsheet, titulo: str) -> list:
    """Filas de la hoja de ingresos de un mes, o [] si no existe."""
    try:
        ws = spreadsheet.worksheet(titulo)
    except gspread.WorksheetNotFound:
        return []

    # Se lee por POSICIÓN de columna (A-F), no por nombre de header vía
    # get_all_records: la fila 1 de esta hoja también tiene el resumen
    # (G1:H3) al lado de la tabla, y una celda de encabezado borrada por
    # error ahí (o cualquiera de las columnas vacías) rompe get_all_records
    # entero. Leyendo por posición no importa qué diga (o no diga) la fila 1.
    filas = ws.get('A2:F', value_render_option='UNFORMATTED_VALUE')
    resultado = []
    for fila in filas:
        fecha = fila[0] if len(fila) > 0 else ''
        if not str(fecha).strip():
            continue

        monto = _parse_float(fila[3] if len(fila) > 3 else '')
        ing_brutos = _parse_float(fila[4] if len(fila) > 4 else '')
        if ing_brutos > monto:
            # Dato mal cargado a mano (ej. tipeado en la columna equivocada)
            # — sin este límite, ingreso_neto podía dar negativo en silencio.
            logger.warning(
                f"{titulo}: Ingresos Brutos ({ing_brutos}) mayor al Monto ({monto}) en la fila "
                f"de {fila[2] if len(fila) > 2 else '?'!r} — se limita a {monto}."
            )
            ing_brutos = monto

        resultado.append({
            'fecha': _normaliza_fecha(fecha),
            'cochera': fila[1] if len(fila) > 1 else '',
            'nombre': str(fila[2]).strip() if len(fila) > 2 else '',
            'monto': monto,
            'ing_brutos': ing_brutos,
            'tipo_pago': str(fila[5]).strip() if len(fila) > 5 else '',
        })
    return resultado


def leer_gastos(spreadsheet: gspread.Spreadsheet, titulo: str) -> list:
    """Filas de la hoja de gastos de un mes, o [] si no existe (mes sin
    ningún gasto cargado todavía)."""
    try:
        ws = spreadsheet.worksheet(titulo)
    except gspread.WorksheetNotFound:
        return []

    # Mismo motivo que en leer_ingresos: esta hoja tiene el resumen (F1:G3)
    # al lado de la tabla en la misma fila 1 — se lee por posición, no por
    # nombre de header.
    filas = ws.get('A2:D', value_render_option='UNFORMATTED_VALUE')
    resultado = []
    for fila in filas:
        fecha = fila[0] if len(fila) > 0 else ''
        if not str(fecha).strip():
            continue
        resultado.append({
            'fecha': _normaliza_fecha(fecha),
            'categoria': str(fila[1]).strip() if len(fila) > 1 else '',
            'monto': _parse_float(fila[2] if len(fila) > 2 else ''),
            'descripcion': str(fila[3]).strip() if len(fila) > 3 else '',
        })
    return resultado


def listar_meses_ingresos(spreadsheet: gspread.Spreadsheet) -> list:
    """(mes, año, título) de todas las hojas de ingresos, ordenados
    cronológicamente. Hojas sin año (formato viejo, todavía no migradas a
    mano) quedan afuera con un warning en el log — no truena, pero avisa."""
    resultado = []
    for ws in spreadsheet.worksheets():
        parsed = parse_mes_sheet_title(ws.title)
        if parsed:
            mes, year = parsed
            resultado.append((mes, year, ws.title))
        elif ws.title not in (PADRON_SHEET_TITLE, OBJETIVO_SHEET_TITLE) and not ws.title.endswith(' - GASTOS'):
            logger.warning(f"Hoja '{ws.title}' no matchea patrón de mes con año — excluida del dashboard.")
    resultado.sort(key=lambda t: (t[1], MESES_ORDEN.index(t[0])))
    return resultado


def calcular_serie_mensual(spreadsheet: gspread.Spreadsheet, objetivo_base_default: float) -> dict:
    """Recorre TODAS las hojas de mes en orden cronológico. Devuelve
    {titulo: métricas}. Cada mes es independiente — si un mes no llega al
    objetivo de rendición, ese faltante no se arrastra al mes siguiente.

    El objetivo de rendición no es una constante: viene de la hoja
    RENDICION_OBJETIVO_BASE (una fila por cada vez que cambió el precio,
    no una fila por mes) y se arrastra hacia adelante hasta la próxima
    fila. `objetivo_base_default` solo se usa para los meses anteriores
    a la primera fila de esa tabla (o si la tabla no existe)."""
    meses = listar_meses_ingresos(spreadsheet)
    objetivos_config = leer_objetivo_por_mes(spreadsheet)
    objetivo_vigente = objetivo_base_default
    por_mes = {}

    for mes, year, titulo in meses:
        if (mes, year) in objetivos_config:
            objetivo_vigente = objetivos_config[(mes, year)]

        ingresos = leer_ingresos(spreadsheet, titulo)
        gastos = leer_gastos(spreadsheet, gastos_sheet_title(mes, year))

        ingreso_bruto = sum(r['monto'] for r in ingresos)
        descuento_ib = sum(r['ing_brutos'] for r in ingresos)

        total_transferencias = 0.0
        total_efectivo = 0.0
        for r in ingresos:
            tipo_canon = _normaliza_tipo_pago(r['tipo_pago'])
            if tipo_canon in ('Transferencia', 'Mercado Pago'):
                total_transferencias += r['monto']
            elif tipo_canon == 'Efectivo':
                total_efectivo += r['monto']
            else:
                logger.warning(
                    f"{titulo}: Tipo de pago no reconocido '{r['tipo_pago']}' (cochera "
                    f"{r['cochera']!r}, {r['nombre']!r}) — no se suma ni a transferencias "
                    f"ni a efectivo. Revisar esa celda en el Sheet."
                )

        total_gastos = sum(g['monto'] for g in gastos)

        objetivo_mes = objetivo_vigente
        neto_efectivo = total_efectivo - total_gastos
        entregado = max(min(neto_efectivo, objetivo_mes), 0)
        ganancia_mes = total_transferencias + max(neto_efectivo - objetivo_mes, 0)

        por_mes[titulo] = {
            'mes': mes,
            'anio': year,
            'titulo': titulo,
            'ingreso_bruto': ingreso_bruto,
            'ingreso_neto': ingreso_bruto - descuento_ib,
            'total_transferencias': total_transferencias,
            'total_efectivo': total_efectivo,
            'total_gastos': total_gastos,
            'deuda_heredada': 0.0,  # ya no se arrastra — se deja el campo en 0 para no romper el frontend
            'objetivo_rendicion': objetivo_mes,
            'entregado_a_socios': entregado,
            'progreso_pct': (entregado / objetivo_mes) if objetivo_mes > 0 else 1.0,
            'ganancia_mes': ganancia_mes,
            '_ingresos_raw': ingresos,  # uso interno de estado_cocheras, no va en la respuesta de la API
        }

    return por_mes


def _resolver_pares_dobles(autos: list) -> dict:
    """{nro: nro_pareja}, tomado directo del campo `pareja` que ya arma
    dashboard/padron.py al expandir una fila de cochera doble combinada
    (ej. NRO COCHERA "23 y 24" → dos CocheraPadron con pareja cruzada)."""
    return {c.nro: c.pareja for c in autos if c.pareja}


def _clasificar_cochera(raw) -> tuple:
    """Devuelve ('nro', int) | ('moto', None) | ('doble_generico', None) |
    ('multi', [str, ...]) | ('externo', texto) | ('desconocido', None).
    Necesario porque el valor de la columna Cochera puede volver de Sheets
    como int, float (si Sheets lo guardó como número) o str ('MOTO'/'DOBLE').
    'externo' es un ingreso real que no corresponde a ninguna cochera de
    este padrón (ej. un cliente que paga por transferencia desde otra
    playa) — se identifica por tener texto libre que no es ninguno de los
    valores especiales conocidos. No es un error de carga, no se loguea.
    'multi' es un pago que cubre varias cocheras en una sola fila (ej.
    '5 y 12', un cliente con 2 espacios que paga todo junto con una sola
    transferencia) — cada parte se vuelve a clasificar individualmente en
    estado_cocheras, mismo estilo que ya usa PADRON para las dobles."""
    if isinstance(raw, (int, float)):
        return ('nro', int(raw))
    texto = str(raw).strip().upper()
    if not texto:
        return ('desconocido', None)
    partes = re.split(r'\s+Y\s+', texto)
    if len(partes) > 1:
        return ('multi', partes)
    if texto == 'MOTO':
        return ('moto', None)
    if texto == 'DOBLE':
        return ('doble_generico', None)
    if texto.isdigit():
        return ('nro', int(texto))
    return ('externo', texto)


def estado_cocheras(ingresos: list, padron: dict) -> dict:
    """Cruza los pagos del mes contra el padrón completo (autos + dobles +
    motos). Motos matchean por nombre (decisión explícita del dueño, frágil
    a typos/cambios de inquilino sin avisar). 'DOBLE' genérico (formato
    viejo sin número) no se puede atribuir a una cochera puntual."""
    pares = _resolver_pares_dobles(padron['autos'])
    cobrados_nro = set()
    cobrados_moto_nombre = set()
    sin_identificar = 0

    def _registrar(tipo, valor, fila):
        nonlocal sin_identificar
        if tipo == 'moto':
            cobrados_moto_nombre.add(normaliza_nombre(fila['nombre']))
        elif tipo == 'doble_generico':
            sin_identificar += 1
        elif tipo == 'nro':
            cobrados_nro.add(valor)
            if valor in pares:
                cobrados_nro.add(pares[valor])
        elif tipo == 'externo':
            pass  # ingreso legítimo, no corresponde a ninguna cochera de este padrón
        else:
            logger.warning(f"Cochera no reconocida en fila de ingresos: {fila!r}")

    for fila in ingresos:
        tipo, nro = _clasificar_cochera(fila['cochera'])
        if tipo == 'multi':
            for parte in nro:
                sub_tipo, sub_valor = _clasificar_cochera(parte)
                _registrar(sub_tipo, sub_valor, fila)
        else:
            _registrar(tipo, nro, fila)

    todas = (
        [
            {'nro': c.nro, 'nombre': c.nombre, 'tipo': 'auto', 'vacia': not c.ocupada,
             'cobrada': c.nro in cobrados_nro, 'pareja': c.pareja}
            for c in padron['autos']
        ] + [
            {'nro': c.nro, 'nombre': c.nombre, 'tipo': 'moto', 'vacia': not c.ocupada,
             'cobrada': normaliza_nombre(c.nombre) in cobrados_moto_nombre, 'pareja': None}
            for c in padron['motos']
        ]
    )
    pendientes = [c for c in todas if not c['cobrada']]

    return {
        'total': len(todas),
        'cobradas': len(todas) - len(pendientes),
        'sin_identificar': sin_identificar,
        'pendientes': pendientes,
        'todas': todas,
    }
