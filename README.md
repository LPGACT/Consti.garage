# 🅿️ Bot de Registro de Pagos — Instrucciones de Setup

## ¿Qué hace este bot?
Recibís un comprobante de pago (imagen o PDF) en WhatsApp → lo reenviás al bot de Telegram con un caption → el bot extrae automáticamente el monto y lo carga en Google Sheets en la hoja del mes correspondiente.

**Formato del caption:**
```
Juan García, 5, JUNIO
```
(Nombre, Número de cochera, Mes)

---

## ⚡ Actualizar la instalación existente (hacer esto una vez, en la compu con el `.env`)

Si ya tenías el bot corriendo antes del dashboard, hacé esto en orden en la computadora donde vive tu `.env`/`credentials.json`:

1. **Traer el código nuevo**
   ```bash
   git pull
   pip install -r requirements.txt
   ```
   (agrega `fastapi` y `uvicorn`, necesarios para el dashboard)

2. **Migrar las hojas de mes existentes** (agregarles el año) — ver la sección [Nombres de hoja con año](#nombres-de-hoja-con-año) más abajo. Sin este paso, el bot va a crear hojas nuevas duplicadas la próxima vez que uses un mes que ya existía.

3. **Crear la pestaña `PADRON`** en el mismo Google Sheet, con el layout exacto de la sección [Hoja PADRON](#hoja-padron-para-el-dashboard) más abajo (`A1:D130` autos/dobles, `H1:I24` motos). Sin esto, el dashboard no puede calcular cocheras cobradas/pendientes.

4. **Agregar al `.env`** las variables nuevas (mirá `.env.example`):
   ```
   DASHBOARD_PASSWORD=elegí-una-contraseña
   RENDICION_OBJETIVO_BASE=9800000
   ```
   (`SERIE_CACHE_TTL_SECONDS` y `PADRON_CACHE_TTL_SECONDS` son opcionales, tienen default)

5. **Correr el bot como siempre:**
   ```bash
   python bot.py
   ```

6. **Correr el dashboard** (en otra terminal):
   ```bash
   uvicorn dashboard.main:app --reload --port 8001
   ```
   Abrí `http://localhost:8001` (o desde el iPhone a `http://<IP-local-de-tu-PC>:8001` en la misma Wi-Fi) — ver [Dashboard financiero](#dashboard-financiero-pwa) para instalarlo como app.

> Si el bot ya está desplegado en Render: al pushear a GitHub se redespliega solo (si el auto-deploy está activo). No te olvides igual de hacer los pasos 2 y 3 directamente sobre el Google Sheet **real** de producción — eso no lo hace el deploy por vos.

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
9. Se descarga un archivo `credentials.json` → renombralo a `credentials.json` si no se llama así y guardalo en `~/secrets/` (`C:\Users\TU_USUARIO\secrets\` en Windows) — **no** en la carpeta del proyecto, para que no quede sincronizado por git/OneDrive junto con el código

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

# 2. Copiar bot.py, requirements.txt y .env.example acá (credentials.json NO va acá, ver Paso 3b)

# 3. Crear entorno virtual e instalar dependencias
python -m venv venv
source venv/bin/activate      # Mac/Linux
# venv\Scripts\activate       # Windows

pip install -r requirements.txt

# 4. Crear el .env con tus datos, en ~/secrets/ (no en la carpeta del proyecto)
mkdir -p ~/secrets
cp .env.example ~/secrets/.env
# Editá ~/secrets/.env con tu editor de texto y completá todos los campos
```

> El bot y el dashboard leen `~/secrets/.env` y `~/secrets/credentials.json` (no la carpeta del proyecto) — es intencional, para que un secreto real nunca quede en una carpeta sincronizada por git o por OneDrive/Drive. En Render no aplica: ahí las variables se cargan directo en el dashboard del servicio (Paso 5b).

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

- **Autos y dobles** en `A1:D130`: `NRO COCHERA | NOMBRE | PLANTA | ANOTACIONES`. Nombre vacío = cochera vacía.
  - **Dobles**: una sola fila con el NRO COCHERA combinado (ej. `"23 y 24"`) y ANOTACIONES `DOBLE`. El dashboard la expande en las dos cocheras. Para cargar el pago en el bot usás **uno solo de los dos números puntuales** (ej. `Nombre, 23, JULIO`) — nunca `DOBLE` genérico sin número — así el dashboard sabe qué par marcar cobrado.
  - **Espacio para motos dentro de la tabla de autos**: si el NOMBRE es `ESPACIO MOTO` o `ESPACIO MOTOS` (sea en una fila simple o en una doble combinada), esa cochera se excluye del conteo de autos — no cuenta como ocupada ni como pendiente. Las motos reales se trackean aparte, abajo.
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

### Objetivo de rendición a socios (cambia cuando cambia el precio)

El monto a rendir no es una constante fija en el `.env` — cambia cada vez que cambia el precio por cochera, y no querés que eso reescriba silenciosamente la rendición de meses ya cerrados. Por eso vive en una hoja del Sheet, `RENDICION_OBJETIVO_BASE`, con dos columnas:

| Mes-Año | Objetivo |
|---|---|
| julio 2026 | $9.800.000 |

Agregá una fila **solo cuando cambie el precio** (no hace falta una por mes) — el valor rige desde ese mes en adelante, hasta la próxima fila. `RENDICION_OBJETIVO_BASE` en el `.env`/Render solo se usa como valor por defecto para meses anteriores a la primera fila de esta hoja (o si la hoja no existe todavía).

### Instalarlo como app en el iPhone

Con el dashboard abierto en Safari: **Compartir → Agregar a pantalla de inicio**. Queda como un ícono más, sin pasar por la App Store.

### Deploy

No está desplegado todavía. Cuando quieras ponerlo en Render, es un segundo Web Service en el mismo repo:
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `uvicorn dashboard.main:app --host 0.0.0.0 --port $PORT`
- Mismas env vars de Sheets + `DASHBOARD_PASSWORD` + `RENDICION_OBJETIVO_BASE`
