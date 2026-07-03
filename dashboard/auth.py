# dashboard/auth.py — Gate simple de contraseña compartida. Es un dashboard
# de un solo usuario, no hace falta nada más elaborado que esto.

import hmac
import os

from fastapi import Header, HTTPException

DASHBOARD_PASSWORD = os.getenv('DASHBOARD_PASSWORD', '')


async def require_auth(authorization: str = Header(default='')) -> None:
    if not DASHBOARD_PASSWORD:
        raise HTTPException(status_code=500, detail="DASHBOARD_PASSWORD no está configurada en el servidor.")
    token = authorization.removeprefix('Bearer ').strip()
    if not hmac.compare_digest(token, DASHBOARD_PASSWORD):
        raise HTTPException(status_code=401, detail="Contraseña inválida")
