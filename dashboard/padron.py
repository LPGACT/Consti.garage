# dashboard/padron.py — Lectura y parseo de la hoja PADRON.
#
# Layout real (confirmado contra el Sheet del usuario):
#
#   A1:D250  autos/dobles — NRO COCHERA | NOMBRE | PLANTA | ANOTACIONES
#            (no hay columna MONTO — el precio no se trackea por cochera acá)
#   H1:I60   motos        — NRO COCHERA | NOMBRE
#
# Los rangos tienen bastante margen de sobra a propósito: el fin real de
# cada tabla lo determina la primera fila con NRO COCHERA vacío, no el
# límite del rango. Un rango justo (ej. exactamente el tamaño de la tabla
# actual) se rompe en silencio el día que alguien inserte una fila en el
# medio de la tabla en vez de escribir sobre una fila vacía — todo lo que
# quede debajo se corre una fila y puede caer fuera del rango sin ningún
# error, solo desaparece del padrón (ya pasó una vez con esta tabla).
#
# Nombre vacío = cochera vacía/sin dueño. Fin de tabla = primera fila con
# NRO COCHERA vacío (no se usa NOMBRE vacío como fin, porque nombre vacío
# es un estado válido).
#
# Dos convenciones reales que no son obvias mirando solo el header:
#   - Cochera doble: UNA fila con NRO COCHERA combinado ("23 y 24") y
#     ANOTACIONES "DOBLE". Se expande a dos CocheraPadron (nro=23, nro=24)
#     con pareja cruzada, para que pagar cualquiera de los dos números
#     marque ambos como cobrados (ver estado_cocheras en metrics.py). El
#     bot solo recibe UNO de los dos números al cargar el pago (nunca
#     "DOBLE" genérico) — así identifica cuál par cobrar.
#   - Espacio para motos dentro de la tabla de autos: NOMBRE "ESPACIO MOTO"
#     o "ESPACIO MOTOS" (single o en una fila doble). Se excluye del todo
#     del conteo de autos — no cuenta como ocupada ni como pendiente. Las
#     motos reales ya se trackean aparte en la tabla H1:I24.

import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

import gspread

from sheets_common import PADRON_SHEET_TITLE

logger = logging.getLogger(__name__)

PADRON_AUTOS_RANGE = 'A1:D250'
PADRON_MOTOS_RANGE = 'H1:I60'
PADRON_AUTOS_HEADER = ['NRO COCHERA', 'NOMBRE', 'PLANTA', 'ANOTACIONES']
PADRON_MOTOS_HEADER = ['NRO COCHERA', 'NOMBRE']

_COCHERA_DOBLE_RE = re.compile(r'^(\d+)\s*Y\s*(\d+)$')
_ESPACIO_MOTO_RE = re.compile(r'^ESPACIO\s+MOTOS?$')


class PadronLayoutError(Exception):
    """El encabezado real de la hoja PADRON no coincide con lo esperado."""


@dataclass
class CocheraPadron:
    tabla: str  # 'autos' | 'motos'
    nro: int
    nombre: str
    planta: str = ''
    anotaciones: str = ''
    pareja: Optional[int] = None  # nro de la otra mitad, si es una cochera doble

    @property
    def ocupada(self) -> bool:
        return bool(self.nombre)


def normaliza_nombre(nombre: str) -> str:
    """Normaliza un nombre para comparación tolerante a mayúsculas/acentos
    (no a errores de tipeo — eso queda como limitación conocida del
    matching de motos por nombre)."""
    sin_acentos = unicodedata.normalize('NFKD', nombre).encode('ascii', 'ignore').decode()
    return ' '.join(sin_acentos.strip().upper().split())


def _normaliza_header(fila: list) -> list:
    return [c.strip().upper() for c in fila]


def _parse_tabla(filas: list, header_esperado: list, tabla: str) -> list:
    if not filas:
        raise PadronLayoutError(f"Tabla '{tabla}': rango vacío, revisar layout de PADRON.")

    header_real = _normaliza_header(filas[0])
    if header_real[:len(header_esperado)] != header_esperado:
        raise PadronLayoutError(
            f"Tabla '{tabla}': encabezado esperado {header_esperado}, "
            f"encontrado {header_real}. Revisar layout real de la hoja PADRON."
        )

    resultado = []
    for fila in filas[1:]:
        nro_raw = (fila[0] if len(fila) > 0 else '').strip()
        if not nro_raw:
            break  # fin de la tabla

        nombre = (fila[1] if len(fila) > 1 else '').strip()
        planta = fila[2].strip() if tabla == 'autos' and len(fila) > 2 else ''
        anotaciones = fila[3].strip() if tabla == 'autos' and len(fila) > 3 else ''

        if _ESPACIO_MOTO_RE.match(nombre.upper()):
            continue  # espacio de motos dentro de la tabla de autos, no cuenta

        doble = _COCHERA_DOBLE_RE.match(nro_raw.upper())
        if doble:
            n1, n2 = int(doble.group(1)), int(doble.group(2))
            resultado.append(CocheraPadron(tabla=tabla, nro=n1, nombre=nombre, planta=planta, anotaciones=anotaciones, pareja=n2))
            resultado.append(CocheraPadron(tabla=tabla, nro=n2, nombre=nombre, planta=planta, anotaciones=anotaciones, pareja=n1))
            continue

        if not nro_raw.isdigit():
            logger.warning(f"PADRON/{tabla}: NRO COCHERA no numérico '{nro_raw}', se ignora la fila.")
            continue

        resultado.append(CocheraPadron(tabla=tabla, nro=int(nro_raw), nombre=nombre, planta=planta, anotaciones=anotaciones))

    vistos = set()
    for c in resultado:
        if c.nro in vistos:
            logger.warning(
                f"PADRON/{tabla}: NRO COCHERA {c.nro} aparece más de una vez — "
                f"revisar filas duplicadas en la hoja PADRON."
            )
        vistos.add(c.nro)

    return resultado


def leer_padron(gc: gspread.Client, sheets_id: str) -> dict:
    """Devuelve {'autos': [CocheraPadron], 'motos': [CocheraPadron]}."""
    ws = gc.open_by_key(sheets_id).worksheet(PADRON_SHEET_TITLE)
    autos = _parse_tabla(ws.get(PADRON_AUTOS_RANGE), PADRON_AUTOS_HEADER, 'autos')
    motos = _parse_tabla(ws.get(PADRON_MOTOS_RANGE), PADRON_MOTOS_HEADER, 'motos')
    return {'autos': autos, 'motos': motos}
