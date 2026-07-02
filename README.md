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

Se guarda en una hoja aparte (`JULIO - GASTOS`) para no mezclarse con los ingresos. Esa hoja también tiene el resumen del mes: Total Ingresos (neto), Total Gastos y Resultado Neto (columnas F-G). El resumen se crea la primera vez que registrás un gasto en ese mes — si nunca cargás ningún gasto en un mes, esa hoja no existe y no hay resumen para ese mes.

---

## Estructura del Google Sheet

Cada mes tiene dos hojas:

**Ingresos (`JULIO`)** — transferencia, Mercado Pago y efectivo, todos juntos:

| Fecha | Cochera | Nombre | Monto | Ing. Brutos (2.5%) | Tipo de Pago |
|-------|---------|--------|-------|---------------------|--------------|
| 05/06/2025 | 5 | Juan García | 15000.00 | | Transferencia |
| 07/06/2025 | 12 | María López | 15000.00 | | Mercado Pago |
| 08/06/2025 | 7 | Carlos Díaz | 15000.00 | | Efectivo |

**Gastos (`JULIO - GASTOS`)** — separada, con su propio total:

| Fecha | Categoría | Monto | Descripción |
|-------|-----------|-------|-------------|
| 08/06/2025 | SUELDOS | 80000.00 | Sueldo Carlos |

---

## Próximos pasos (cuando quieras expandir)

- Dashboard interactivo (TypeScript) con filtros sobre Ingresos / Gastos / Rendición a socios
- Barra de progreso de rendición mensual a socios
