# dashboard/demo_data.py — Datos de ejemplo para correr el dashboard sin
# credenciales reales de Google (DASHBOARD_DEMO=1), solo para revisar cómo
# se ve. No lo usa el deploy real.
#
# Los campos "_fmt" se calculan con format_pesos (la misma función que usa
# el camino real) en vez de escribirse a mano, para que el modo demo no se
# desalinee en silencio si el formato de moneda cambia algún día.

from sheets_common import format_pesos

DEMO_MESES = [
    {'mes': 'MAYO', 'anio': 2026, 'titulo': 'MAYO 2026'},
    {'mes': 'JUNIO', 'anio': 2026, 'titulo': 'JUNIO 2026'},
    {'mes': 'JULIO', 'anio': 2026, 'titulo': 'JULIO 2026'},
]

AUTOS_TOTAL = 84
MOTOS_TOTAL = 4

_CAMPOS_MONETARIOS = [
    'ingreso_bruto', 'ingreso_neto', 'total_transferencias', 'total_efectivo',
    'total_gastos', 'deuda_heredada', 'objetivo_rendicion', 'entregado_a_socios',
    'ganancia_mes',
]


def _construir_cocheras(pendientes: list, sin_identificar: int = 0) -> dict:
    """Arma el bloque 'cocheras' de un mes demo: todas las cocheras
    cobradas salvo las que aparecen en `pendientes`."""
    pend_autos = {p['nro']: p for p in pendientes if p['tipo'] == 'auto'}
    pend_motos = {p['nro']: p for p in pendientes if p['tipo'] == 'moto'}

    todas = []
    for nro in range(1, AUTOS_TOTAL + 1):
        if nro in pend_autos:
            p = pend_autos[nro]
            todas.append({'nro': nro, 'nombre': p['nombre'], 'tipo': 'auto', 'vacia': p['vacia'], 'cobrada': False})
        else:
            todas.append({'nro': nro, 'nombre': f'Inquilino {nro}', 'tipo': 'auto', 'vacia': False, 'cobrada': True})
    for nro in range(1, MOTOS_TOTAL + 1):
        if nro in pend_motos:
            p = pend_motos[nro]
            todas.append({'nro': nro, 'nombre': p['nombre'], 'tipo': 'moto', 'vacia': p['vacia'], 'cobrada': False})
        else:
            todas.append({'nro': nro, 'nombre': f'Moto {nro}', 'tipo': 'moto', 'vacia': False, 'cobrada': True})

    pendientes_final = [c for c in todas if not c['cobrada']]
    return {
        'total': len(todas),
        'cobradas': len(todas) - len(pendientes_final),
        'sin_identificar': sin_identificar,
        'pendientes': pendientes_final,
        'todas': todas,
    }


def _con_formato(mes: str, anio: int, titulo: str, valores: dict, cocheras: dict) -> dict:
    resultado = {'mes': mes, 'anio': anio, 'titulo': titulo, **valores, 'cocheras': cocheras}
    for campo in _CAMPOS_MONETARIOS:
        resultado[f'{campo}_fmt'] = format_pesos(valores[campo])
    return resultado


DEMO_DASHBOARD = {
    'MAYO 2026': _con_formato('MAYO', 2026, 'MAYO 2026', {
        'ingreso_bruto': 12800000, 'ingreso_neto': 12650000,
        'total_transferencias': 1800000, 'total_efectivo': 11000000,
        'total_gastos': 400000, 'deuda_heredada': 0,
        'objetivo_rendicion': 9800000, 'entregado_a_socios': 9800000,
        'progreso_pct': 1.0, 'ganancia_mes': 2600000,
    }, _construir_cocheras([])),

    'JUNIO 2026': _con_formato('JUNIO', 2026, 'JUNIO 2026', {
        'ingreso_bruto': 12300000, 'ingreso_neto': 12150000,
        'total_transferencias': 2200000, 'total_efectivo': 10100000,
        'total_gastos': 500000, 'deuda_heredada': 0,
        'objetivo_rendicion': 9800000, 'entregado_a_socios': 9600000,
        'progreso_pct': 0.9795918367346939, 'ganancia_mes': 2200000,
    }, _construir_cocheras([
        {'nro': 12, 'nombre': 'Roberto Sosa', 'tipo': 'auto', 'vacia': False},
        {'nro': 47, 'nombre': '', 'tipo': 'auto', 'vacia': True},
        {'nro': 3, 'nombre': 'Elena Ruiz', 'tipo': 'moto', 'vacia': False},
        {'nro': 61, 'nombre': 'Carlos Bianchi', 'tipo': 'auto', 'vacia': False},
    ])),

    'JULIO 2026': _con_formato('JULIO', 2026, 'JULIO 2026', {
        'ingreso_bruto': 8450000, 'ingreso_neto': 8340000,
        'total_transferencias': 3250000, 'total_efectivo': 5200000,
        'total_gastos': 620000, 'deuda_heredada': 1200000,
        'objetivo_rendicion': 11000000, 'entregado_a_socios': 4580000,
        'progreso_pct': 0.4163636363636364, 'ganancia_mes': 3250000,
    }, _construir_cocheras([
        {'nro': 12, 'nombre': 'Roberto Sosa', 'tipo': 'auto', 'vacia': False},
        {'nro': 47, 'nombre': '', 'tipo': 'auto', 'vacia': True},
        {'nro': 55, 'nombre': '', 'tipo': 'auto', 'vacia': True},
        {'nro': 61, 'nombre': 'Carlos Bianchi', 'tipo': 'auto', 'vacia': False},
        {'nro': 70, 'nombre': 'Julian Alvarez', 'tipo': 'auto', 'vacia': False},
        {'nro': 3, 'nombre': 'Elena Ruiz', 'tipo': 'moto', 'vacia': False},
        {'nro': 4, 'nombre': 'Nadia Fernandez', 'tipo': 'moto', 'vacia': False},
    ], sin_identificar=2)),
}

_DEMO_GASTOS_RAW = {
    'JULIO 2026': [
        {'fecha': '03/07/2026', 'categoria': 'SUELDOS', 'monto': 350000, 'descripcion': 'Sueldo Carlos'},
        {'fecha': '05/07/2026', 'categoria': 'MANTENIMIENTO', 'monto': 90000, 'descripcion': 'Arreglo portón automático'},
        {'fecha': '10/07/2026', 'categoria': 'LIMPIEZA', 'monto': 45000, 'descripcion': 'Insumos de limpieza'},
        {'fecha': '15/07/2026', 'categoria': 'SEGURIDAD', 'monto': 120000, 'descripcion': 'Cámaras nuevas planta baja'},
        {'fecha': '20/07/2026', 'categoria': 'IMPUESTOS', 'monto': 15000, 'descripcion': 'Tasa municipal'},
    ],
    'JUNIO 2026': [
        {'fecha': '02/06/2026', 'categoria': 'SUELDOS', 'monto': 350000, 'descripcion': 'Sueldo Carlos'},
        {'fecha': '18/06/2026', 'categoria': 'MANTENIMIENTO', 'monto': 150000, 'descripcion': 'Pintura planta 1'},
    ],
    'MAYO 2026': [
        {'fecha': '04/05/2026', 'categoria': 'SUELDOS', 'monto': 350000, 'descripcion': 'Sueldo Carlos'},
        {'fecha': '22/05/2026', 'categoria': 'SEGURIDAD', 'monto': 50000, 'descripcion': 'Reparación alarma'},
    ],
}
DEMO_GASTOS = {
    titulo: [{**g, 'monto_fmt': format_pesos(g['monto'])} for g in filas]
    for titulo, filas in _DEMO_GASTOS_RAW.items()
}

_DEMO_INGRESOS_RAW = {
    'JULIO 2026': [
        {'fecha': '01/07/2026', 'cochera': 1, 'nombre': 'Juan García', 'monto': 140000, 'ing_brutos': 0, 'tipo_pago': 'Efectivo'},
        {'fecha': '02/07/2026', 'cochera': 2, 'nombre': 'María López', 'monto': 140000, 'ing_brutos': 3500, 'tipo_pago': 'Mercado Pago'},
        {'fecha': '03/07/2026', 'cochera': 34, 'nombre': 'Pedro Gómez', 'monto': 180000, 'ing_brutos': 0, 'tipo_pago': 'Transferencia'},
        {'fecha': '04/07/2026', 'cochera': 'MOTO', 'nombre': 'Elena Ruiz', 'monto': 70000, 'ing_brutos': 0, 'tipo_pago': 'Efectivo'},
        {'fecha': '05/07/2026', 'cochera': 8, 'nombre': 'Carlos Díaz', 'monto': 140000, 'ing_brutos': 0, 'tipo_pago': 'Transferencia'},
        {'fecha': '06/07/2026', 'cochera': 15, 'nombre': 'Nadia Fernández', 'monto': 140000, 'ing_brutos': 0, 'tipo_pago': 'Efectivo'},
        {'fecha': '07/07/2026', 'cochera': 'DOBLE', 'nombre': 'Julian Alvarez', 'monto': 180000, 'ing_brutos': 0, 'tipo_pago': 'Efectivo'},
    ],
    'JUNIO 2026': [
        {'fecha': '01/06/2026', 'cochera': 1, 'nombre': 'Juan García', 'monto': 140000, 'ing_brutos': 0, 'tipo_pago': 'Efectivo'},
        {'fecha': '02/06/2026', 'cochera': 2, 'nombre': 'María López', 'monto': 140000, 'ing_brutos': 0, 'tipo_pago': 'Transferencia'},
    ],
    'MAYO 2026': [
        {'fecha': '01/05/2026', 'cochera': 1, 'nombre': 'Juan García', 'monto': 140000, 'ing_brutos': 0, 'tipo_pago': 'Efectivo'},
    ],
}
DEMO_INGRESOS = {
    titulo: [{**r, 'monto_fmt': format_pesos(r['monto'])} for r in filas]
    for titulo, filas in _DEMO_INGRESOS_RAW.items()
}
