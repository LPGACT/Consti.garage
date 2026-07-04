# dashboard/metrics.py — Fórmulas financieras del dashboard y arrastre de
# deuda de rendición a socios mes a mes. Todo se deriva de las hojas de
# ingresos/gastos que ya escribe bot.py — no hay ningún ledger nuevo que
# mantener sincronizado.
#
# Reglas de negocio (cerradas con el dueño de la playa, no son supuestos):
#   - La rendición a socios ($9.800.000, config. RENDICION_OBJETIVO_BASE)
#     sale SOLO del efectivo, después de pagar los gastos con esa misma
#     plata. Es fija, no depende de cuántas cocheras estén vacías.
#   - Si el efectivo no alcanza, el faltante NO sale del bolsillo del dueño
#     ese mes — se suma al objetivo del mes siguiente ("deuda heredada").
#   - Lo que gana el dueño = todo lo que le transfieren (Transferencia +
#     Mercado Pago, nunca se reparte) + lo que sobra del efectivo después
#     de gastos y rendición (nunca negativo: el déficit ya está cubierto
#     por la deuda heredada, no reduce la ganancia del mes en curso).

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


def _parse_monto_texto(value: str) -> Optional[float]:
    """Parsea montos con formato de celda tipo '$9,800,000.00'."""
    limpio = re.sub(r'[^\d.]', '', str(value).replace(',', ''))
    if not limpio:
        return None
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

    registros = ws.get_all_records(value_render_option='UNFORMATTED_VALUE')
    resultado = []
    for r in registros:
        if not str(r.get('Fecha', '')).strip():
            continue
        resultado.append({
            'fecha': r.get('Fecha'),
            'cochera': r.get('Cochera'),
            'nombre': str(r.get('Nombre', '')).strip(),
            'monto': _parse_float(r.get('Monto')),
            'ing_brutos': _parse_float(r.get('Ing. Brutos (2.5%)')),
            'tipo_pago': str(r.get('Tipo de Pago', '')).strip(),
        })
    return resultado


def leer_gastos(spreadsheet: gspread.Spreadsheet, titulo: str) -> list:
    """Filas de la hoja de gastos de un mes, o [] si no existe (mes sin
    ningún gasto cargado todavía)."""
    try:
        ws = spreadsheet.worksheet(titulo)
    except gspread.WorksheetNotFound:
        return []

    registros = ws.get_all_records(value_render_option='UNFORMATTED_VALUE')
    resultado = []
    for r in registros:
        if not str(r.get('Fecha', '')).strip():
            continue
        resultado.append({
            'fecha': r.get('Fecha'),
            'categoria': str(r.get('Categoría', '')).strip(),
            'monto': _parse_float(r.get('Monto')),
            'descripcion': str(r.get('Descripción', '')).strip(),
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
    """Recorre TODAS las hojas de mes en orden cronológico, acumulando el
    déficit de rendición de un mes al siguiente. Devuelve {titulo: métricas}.

    El objetivo de rendición no es una constante: viene de la hoja
    RENDICION_OBJETIVO_BASE (una fila por cada vez que cambió el precio,
    no una fila por mes) y se arrastra hacia adelante hasta la próxima
    fila. `objetivo_base_default` solo se usa para los meses anteriores
    a la primera fila de esa tabla (o si la tabla no existe)."""
    meses = listar_meses_ingresos(spreadsheet)
    objetivos_config = leer_objetivo_por_mes(spreadsheet)
    deuda_acumulada = 0.0
    objetivo_vigente = objetivo_base_default
    por_mes = {}

    for mes, year, titulo in meses:
        if (mes, year) in objetivos_config:
            objetivo_vigente = objetivos_config[(mes, year)]

        ingresos = leer_ingresos(spreadsheet, titulo)
        gastos = leer_gastos(spreadsheet, gastos_sheet_title(mes, year))

        ingreso_bruto = sum(r['monto'] for r in ingresos)
        descuento_ib = sum(r['ing_brutos'] for r in ingresos)
        total_transferencias = sum(
            r['monto'] for r in ingresos if r['tipo_pago'] in ('Transferencia', 'Mercado Pago')
        )
        total_efectivo = sum(r['monto'] for r in ingresos if r['tipo_pago'] == 'Efectivo')
        total_gastos = sum(g['monto'] for g in gastos)

        objetivo_mes = objetivo_vigente + deuda_acumulada
        neto_efectivo = total_efectivo - total_gastos
        entregado = max(min(neto_efectivo, objetivo_mes), 0)
        deficit_nuevo = max(objetivo_mes - neto_efectivo, 0)
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
            'deuda_heredada': deuda_acumulada,
            'objetivo_rendicion': objetivo_mes,
            'entregado_a_socios': entregado,
            'progreso_pct': (entregado / objetivo_mes) if objetivo_mes > 0 else 1.0,
            'ganancia_mes': ganancia_mes,
            '_ingresos_raw': ingresos,  # uso interno de estado_cocheras, no va en la respuesta de la API
        }
        deuda_acumulada = deficit_nuevo

    return por_mes


def _resolver_pares_dobles(autos: list) -> dict:
    """{nro: nro_pareja}, tomado directo del campo `pareja` que ya arma
    dashboard/padron.py al expandir una fila de cochera doble combinada
    (ej. NRO COCHERA "23 y 24" → dos CocheraPadron con pareja cruzada)."""
    return {c.nro: c.pareja for c in autos if c.pareja}


def _clasificar_cochera(raw) -> tuple:
    """Devuelve ('nro', int) | ('moto', None) | ('doble_generico', None) |
    ('externo', texto) | ('desconocido', None).
    Necesario porque el valor de la columna Cochera puede volver de Sheets
    como int, float (si Sheets lo guardó como número) o str ('MOTO'/'DOBLE').
    'externo' es un ingreso real que no corresponde a ninguna cochera de
    este padrón (ej. un cliente que paga por transferencia desde otra
    playa) — se identifica por tener texto libre que no es ninguno de los
    valores especiales conocidos. No es un error de carga, no se loguea."""
    if isinstance(raw, (int, float)):
        return ('nro', int(raw))
    texto = str(raw).strip().upper()
    if not texto:
        return ('desconocido', None)
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

    for fila in ingresos:
        tipo, nro = _clasificar_cochera(fila['cochera'])
        if tipo == 'moto':
            cobrados_moto_nombre.add(normaliza_nombre(fila['nombre']))
        elif tipo == 'doble_generico':
            sin_identificar += 1
        elif tipo == 'nro':
            cobrados_nro.add(nro)
            if nro in pares:
                cobrados_nro.add(pares[nro])
        elif tipo == 'externo':
            pass  # ingreso legítimo, no corresponde a ninguna cochera de este padrón
        else:
            logger.warning(f"Cochera no reconocida en fila de ingresos: {fila!r}")

    todas = (
        [
            {'nro': c.nro, 'nombre': c.nombre, 'tipo': 'auto', 'vacia': not c.ocupada,
             'cobrada': c.nro in cobrados_nro}
            for c in padron['autos']
        ] + [
            {'nro': c.nro, 'nombre': c.nombre, 'tipo': 'moto', 'vacia': not c.ocupada,
             'cobrada': normaliza_nombre(c.nombre) in cobrados_moto_nombre}
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
