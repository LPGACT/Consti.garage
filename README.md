# 🅿️ Bot de Registro de Pagos — Instrucciones de Setup

## ¿Qué hace este bot?
Recibís un comprobante de pago (imagen o PDF) en WhatsApp → lo reenviás al bot de Telegram con un caption → el bot extrae automáticamente el monto y lo carga en Google Sheets en la hoja del mes correspondiente.

**Formato del caption:**
```
Juan García, 5, JUNIO
```
(Nombre, Número de cochera, Mes)

---

## PASO 1 — Crear el bot de Telegram

1. Abrí Telegram y buscá **@BotFather**
2. Mandá `/newbot`
3. Poné un nombre (ej: `Pagos Estacionamiento`)
4. Poné un username que termine en `bot` (ej: `pagos_estacionamiento_bot`)
5. BotFather te devuelve un **token** → copialo (lo necesitás en el `.env`)

**Conseguir tu User ID:**
1. Buscá **@userinfobot** en Telegram
2. Mandá `/start`
3. Te dice tu ID numérico → copialo

---

## PASO 2 — Conseguir la API key de Gemini (gratis)

1. Entrá a [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. Hacé clic en **"Create API Key"**
3. Copiá la key → la necesitás en el `.env`

> ✅ Gratis hasta 1.500 imágenes/día. Para tu uso (200/mes) nunca vas a pagar.

---

## PASO 3 — Crear el Google Sheet y la cuenta de servicio

### 3a. Crear el Google Sheet
1. Entrá a [https://sheets.google.com](https://sheets.google.com) y creá una nueva hoja
2. Poné un nombre (ej: `Pagos Estacionamiento 2025`)
3. Copiá el ID de la URL:
   `https://docs.google.com/spreadsheets/d/**[ESTE_ES_EL_ID]**/edit`

### 3b. Crear la cuenta de servicio (para que el bot escriba en Sheets)
1. Entrá a [https://console.cloud.google.com](https://console.cloud.google.com)
2. Creá un proyecto nuevo (ej: `bot-estacionamiento`)
3. Buscá **"APIs & Services"** → **"Enable APIs"**
4. Activá **"Google Sheets API"**
5. Andá a **"Credentials"** → **"Create Credentials"** → **"Service Account"**
6. Poné cualquier nombre → hacé clic en **"Done"**
7. Hacé clic en la cuenta de servicio que acabás de crear
8. Andá a la pestaña **"Keys"** → **"Add Key"** → **"JSON"**
9. Se descarga un archivo `credentials.json` → guardalo en la carpeta del proyecto

### 3c. Darle acceso al Sheet
1. Abrí el archivo `credentials.json` descargado
2. Copiá el campo `"client_email"` (algo como `bot@proyecto.iam.gserviceaccount.com`)
3. Abrí tu Google Sheet
4. Hacé clic en **Compartir** → pegá ese email → dale permisos de **Editor**

---

## PASO 4 — Configurar el proyecto localmente

```bash
# 1. Clonar / copiar los archivos en una carpeta
mkdir bot-estacionamiento
cd bot-estacionamiento

# 2. Copiar bot.py, requirements.txt, .env.example y credentials.json acá

# 3. Crear entorno virtual e instalar dependencias
python -m venv venv
source venv/bin/activate      # Mac/Linux
# venv\Scripts\activate       # Windows

pip install -r requirements.txt

# 4. Crear el .env con tus datos
cp .env.example .env
# Editá .env con tu editor de texto y completá todos los campos
```

---

## PASO 5a — Correr el bot localmente

```bash
python bot.py
```

Si ves `Modo polling (local)` en la terminal, está funcionando.

> ⚠️ El bot solo funciona mientras la terminal esté abierta y tu compu encendida.

---

## PASO 5b — Deploy en Render (para que corra 24/7 gratis)

1. Subí el proyecto a [GitHub](https://github.com) (podés hacerlo privado)
2. Entrá a [https://render.com](https://render.com) y creá una cuenta
3. **"New"** → **"Web Service"** → conectá tu repositorio
4. Configuración:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
   - **Instance Type:** Free
5. En **"Environment Variables"** agregá todas las variables del `.env`
6. Para `GOOGLE_CREDENTIALS_JSON`: abrí el `credentials.json`, copiá **todo el contenido** y pegalo como valor de esa variable
7. Para `WEBHOOK_URL`: pegá la URL que te da Render (ej: `https://tu-bot.onrender.com`)
8. Hacé deploy

> ⚠️ El tier gratuito de Render "duerme" después de 15 min sin actividad. Cuando mandás el primer mensaje tarda ~30 segundos en despertar. Para uso esporádico está bien. Si querés que sea instantáneo, el plan de $7/mes lo mantiene siempre activo.

---

## Cómo usar el bot

### Transferencia / Mercado Pago (con comprobante)

1. Abrís Telegram, buscás tu bot por username
2. Cuando un cliente te manda un comprobante por WhatsApp, lo reenviás al bot
3. En el caption escribís: `Nombre, Cochera, Mes`
   - Ejemplo: `María López, 12, JULIO`
4. El bot responde con la confirmación y carga en Sheets automáticamente

**Si el mes no existe en el Sheet:** el bot crea la hoja automáticamente con los encabezados.

### Efectivo (sin comprobante, varias cocheras en un solo mensaje)

Mandás un mensaje de texto (no hace falta `/`), primera línea con el mes y después una línea por cochera:

```
EFECTIVO, JULIO
5, Juan García, 15000
12, María López, 15000
```

El monto va sin separador de miles (`15000`, no `15.000` — la coma ya se usa para separar los campos). El bot carga cada línea como una fila en la misma hoja del mes, con "Efectivo" como tipo de pago, y te avisa si alguna línea no se pudo leer sin perder las demás.

### Gastos

Mensaje de texto con: `GASTOS, Mes, Categoría, Monto, Descripción`

```
GASTOS, JULIO, SUELDOS, 80000, Sueldo Carlos
```

Se guarda en una hoja aparte (`JULIO 2026 - GASTOS`) para no mezclarse con los ingresos. Esa hoja también tiene el resumen del mes: Total Ingresos (neto), Total Gastos y Resultado Neto (columnas F-G). El resumen se crea la primera vez que registrás un gasto en ese mes — si nunca cargás ningún gasto en un mes, esa hoja no existe y no hay resumen para ese mes.

### Cambio de dueño de cochera

Mensaje de texto con: `CAMBIO, Nro, NombreNuevo`

```
CAMBIO, 34, Pedro Gómez
```

Busca la cochera (auto o moto) por número en la hoja `PADRON` y reemplaza el nombre. Sirve para cuando cambia el inquilino. El bot confirma con el nombre viejo y el nuevo.

---

## Nombres de hoja con año

Las hojas de mes ahora se llaman `"JULIO 2026"` en vez de `"JULIO"` — el año se agrega automáticamente (el año actual), sin que cambies cómo escribís el caption. Esto evita que un mismo mes en dos años distintos (ej. julio 2026 y julio 2027) termine escribiendo en la misma hoja.

**Si ya tenías hojas de mes de antes de este cambio**, hay que renombrarlas a mano una sola vez:
1. Renombrá cada hoja de mes agregándole el año (`JULIO` → `JULIO 2026`).
2. Renombrá también su hoja de gastos correspondiente (`JULIO - GASTOS` → `JULIO 2026 - GASTOS`).
3. En la hoja de gastos, corregí a mano la fórmula de la celda G1 (`='JULIO'!H3` → `='JULIO 2026'!H3`) — es solo cosmético para esa celda del propio Sheet, el dashboard no depende de ella.

## Hoja PADRON (para el dashboard)

Se usa para saber qué cocheras existen y cruzarlas contra los pagos del mes. Es una pestaña nueva llamada exactamente `PADRON` en el mismo spreadsheet, con dos tablas:

- **Autos y dobles** en `A1:D130`: `NRO COCHERA | NOMBRE | PLANTA | ANOTACIONES`. Nombre vacío = cochera vacía. Para las dobles (dos espacios con un precio distinto, ej. 34 y 35), poné en ANOTACIONES el número de la pareja (ej. `"doble con 35"`) para que el dashboard las marque cobradas juntas.
- **Motos** en `H1:I24`: `NRO COCHERA | NOMBRE`. Los pagos de motos se cargan al bot sin número (`Juan, MOTO, JULIO`) y se cruzan contra esta tabla **por nombre** — si el nombre no coincide exactamente (typo, o cambio de inquilino sin actualizar acá), el dashboard no lo va a poder identificar.

Si el layout real de tu Sheet no coincide con estos rangos exactos, el dashboard va a fallar con un error claro (no va a leer datos corridos en silencio) — avisame para ajustar `PADRON_AUTOS_RANGE`/`PADRON_MOTOS_RANGE` en `dashboard/padron.py`.

---

## Estructura del Google Sheet

Cada mes tiene dos hojas:

**Ingresos (`JULIO 2026`)** — transferencia, Mercado Pago y efectivo, todos juntos:

| Fecha | Cochera | Nombre | Monto | Ing. Brutos (2.5%) | Tipo de Pago |
|-------|---------|--------|-------|---------------------|--------------|
| 05/06/2025 | 5 | Juan García | 15000.00 | | Transferencia |
| 07/06/2025 | 12 | María López | 15000.00 | | Mercado Pago |
| 08/06/2025 | 7 | Carlos Díaz | 15000.00 | | Efectivo |

**Gastos (`JULIO 2026 - GASTOS`)** — separada, con su propio total:

| Fecha | Categoría | Monto | Descripción |
|-------|-----------|-------|-------------|
| 08/06/2025 | SUELDOS | 80000.00 | Sueldo Carlos |

---

## Dashboard financiero (PWA)

Vive en `dashboard/` — un backend (FastAPI) que lee los mismos Sheets del bot y calcula, mes a mes: ganancia, ingresos por tipo de pago, gastos filtrables, progreso de la rendición a socios (con la deuda que se arrastra si un mes el efectivo no alcanza) y cocheras cobradas/pendientes contra el padrón.

### Correrlo en local

```bash
pip install -r requirements.txt
uvicorn dashboard.main:app --reload --port 8001
```

Necesita las mismas variables `GOOGLE_SHEETS_ID` / `GOOGLE_CREDENTIALS_JSON` (o `credentials.json` local) que el bot, más `DASHBOARD_PASSWORD` y `RENDICION_OBJETIVO_BASE` (ver `.env.example`).

Abrí `http://localhost:8001` en la compu, o desde el iPhone a `http://<IP-local-de-tu-PC>:8001` estando en la misma red Wi-Fi.

### Instalarlo como app en el iPhone

Con el dashboard abierto en Safari: **Compartir → Agregar a pantalla de inicio**. Queda como un ícono más, sin pasar por la App Store.

### Deploy

No está desplegado todavía. Cuando quieras ponerlo en Render, es un segundo Web Service en el mismo repo:
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `uvicorn dashboard.main:app --host 0.0.0.0 --port $PORT`
- Mismas env vars de Sheets + `DASHBOARD_PASSWORD` + `RENDICION_OBJETIVO_BASE`
