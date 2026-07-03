# dashboard/padron.py — Lectura y parseo de la hoja PADRON.
#
# Layout real (confirmado contra el Sheet del usuario):
#
#   A1:D130  autos/dobles — NRO COCHERA | NOMBRE | PLANTA | ANOTACIONES
#            (no hay columna MONTO — el precio no se trackea por cochera acá)
#   H1:I24   motos        — NRO COCHERA | NOMBRE
#
# Nombre vacío = cochera vacía/sin dueño. Fin de tabla = primera fila con
# NRO COCHERA vacío (no se usa NOMBRE vacío como fin, porque nombre vacío
# es un estado válido).

import logging
import unicodedata
from dataclasses import dataclass

import gspread

from sheets_common import PADRON_SHEET_TITLE

logger = logging.getLogger(__name__)

PADRON_AUTOS_RANGE = 'A1:D130'
PADRON_MOTOS_RANGE = 'H1:I24'
PADRON_AUTOS_HEADER = ['NRO COCHERA', 'NOMBRE', 'PLANTA', 'ANOTACIONES']
PADRON_MOTOS_HEADER = ['NRO COCHERA', 'NOMBRE']


class PadronLayoutError(Exception):
    """El encabezado real de la hoja PADRON no coincide con lo esperado."""


@dataclass
class CocheraPadron:
    tabla: str  # 'autos' | 'motos'
    nro: int
    nombre: str
    planta: str = ''
    anotaciones: str = ''

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
        if not nro_raw.isdigit():
            logger.warning(f"PADRON/{tabla}: NRO COCHERA no numérico '{nro_raw}', se ignora la fila.")
            continue

        nombre = (fila[1] if len(fila) > 1 else '').strip()
        resultado.append(CocheraPadron(
            tabla=tabla,
            nro=int(nro_raw),
            nombre=nombre,
            planta=(fila[2].strip() if tabla == 'autos' and len(fila) > 2 else ''),
            anotaciones=(fila[3].strip() if tabla == 'autos' and len(fila) > 3 else ''),
        ))
    return resultado


def leer_padron(gc: gspread.Client, sheets_id: str) -> dict:
    """Devuelve {'autos': [CocheraPadron], 'motos': [CocheraPadron]}."""
    ws = gc.open_by_key(sheets_id).worksheet(PADRON_SHEET_TITLE)
    autos = _parse_tabla(ws.get(PADRON_AUTOS_RANGE), PADRON_AUTOS_HEADER, 'autos')
    motos = _parse_tabla(ws.get(PADRON_MOTOS_RANGE), PADRON_MOTOS_HEADER, 'motos')
    return {'autos': autos, 'motos': motos}
