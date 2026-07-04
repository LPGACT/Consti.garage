const TOKEN_KEY = 'dashboard_password';

const TITULOS_PAGINA = {
  resumen: ['Resumen', 'Así viene el mes'],
  ingresos: ['Ingresos', 'Pagos recibidos este mes'],
  gastos: ['Gastos', 'Egresos del mes'],
  cocheras: ['Cocheras', 'Cobradas y pendientes contra el padrón'],
};

let meses = [];       // [{mes, anio, titulo}], orden cronológico
let mesIndex = -1;
let paginaActual = 'resumen';

// Datos de la página+mes actualmente visible. Se piden de nuevo cada vez que
// cambiás de página o de mes (nunca se sirven de un cache viejo) — así el
// dashboard siempre refleja lo último cargado por el bot, aunque haya quedado
// abierto en el celular mientras se registraba un pago nuevo.
let ingresosDelMes = [];
let gastosDelMes = [];
let cocherasDelMes = null;

// Filtros por página
const filtros = {
  ingresos: { tipoPago: 'TODOS', texto: '' },
  cocheras: { estado: 'TODAS', tipo: 'TODOS', texto: '' },
  gastos: { texto: '' },
};

function token() {
  return localStorage.getItem(TOKEN_KEY) || '';
}

async function fetchJSON(url, opts = {}) {
  const resp = await fetch(url, {
    ...opts,
    headers: { ...(opts.headers || {}), Authorization: `Bearer ${token()}` },
  });
  if (resp.status === 401) {
    localStorage.removeItem(TOKEN_KEY);
    mostrarLogin();
    throw new Error('401');
  }
  if (!resp.ok) throw new Error(`${url} → ${resp.status}`);
  return resp.json();
}

function mostrarLogin() {
  document.getElementById('login-view').classList.remove('hidden');
  document.getElementById('app').classList.add('hidden');
}

function mostrarApp() {
  document.getElementById('login-view').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');
}

async function intentarLogin() {
  const password = document.getElementById('password').value;
  const loginError = document.getElementById('login-error');
  loginError.textContent = '';
  try {
    const resp = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    });
    if (!resp.ok) {
      loginError.textContent = 'Contraseña incorrecta.';
      return;
    }
    localStorage.setItem(TOKEN_KEY, password);
    mostrarApp();
    await init();
  } catch (e) {
    loginError.textContent = 'No pude conectar con el servidor.';
  }
}

document.getElementById('login-btn').addEventListener('click', intentarLogin);
document.getElementById('password').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    intentarLogin();
  }
});

// ── Navegación entre páginas ─────────────────────────────────────────────
function mostrarPagina(pagina) {
  paginaActual = pagina;

  document.querySelectorAll('.page').forEach((el) => el.classList.add('hidden'));
  document.getElementById(`page-${pagina}`).classList.remove('hidden');

  document.querySelectorAll('[data-page]').forEach((el) => {
    el.classList.toggle('active', el.dataset.page === pagina);
  });

  const [titulo, subtitulo] = TITULOS_PAGINA[pagina];
  document.getElementById('titulo-pagina').textContent = titulo;
  document.getElementById('subtitulo-pagina').textContent = subtitulo;

  cargarPaginaActual();
}

document.querySelectorAll('[data-page]').forEach((el) => {
  el.addEventListener('click', () => mostrarPagina(el.dataset.page));
});

// ── Selector de mes ──────────────────────────────────────────────────────
function capitalizar(mes) {
  return mes.charAt(0) + mes.slice(1).toLowerCase();
}

function actualizarSelectorMes() {
  const actual = meses[mesIndex];
  document.getElementById('mes-label').textContent = actual
    ? `${capitalizar(actual.mes)} ${actual.anio}`
    : '—';
  document.getElementById('mes-prev').disabled = mesIndex <= 0;
  document.getElementById('mes-next').disabled = mesIndex >= meses.length - 1;
}

document.getElementById('mes-prev').addEventListener('click', () => {
  if (mesIndex > 0) {
    mesIndex -= 1;
    actualizarSelectorMes();
    cargarPaginaActual();
  }
});

document.getElementById('mes-next').addEventListener('click', () => {
  if (mesIndex < meses.length - 1) {
    mesIndex += 1;
    actualizarSelectorMes();
    cargarPaginaActual();
  }
});

// ── Carga y render por página ────────────────────────────────────────────
function tituloMesActual() {
  const actual = meses[mesIndex];
  return actual ? actual.titulo : null;
}

function mostrarError(mensaje) {
  document.getElementById('error-banner-texto').textContent =
    mensaje || 'No se pudo cargar. Revisá tu conexión.';
  document.getElementById('error-banner').classList.remove('hidden');
}

function ocultarError() {
  document.getElementById('error-banner').classList.add('hidden');
}

function mensajeDeError(e) {
  const match = /→ (\d+)$/.exec(e.message);
  if (!match) return 'No pude conectar con el servidor. Revisá tu conexión.';
  const status = Number(match[1]);
  if (status === 404) return 'No hay datos cargados para este mes todavía.';
  if (status >= 500) return 'Error del servidor. Probá de nuevo en un momento.';
  return 'No se pudo cargar. Intentá de nuevo.';
}

function mostrarCargando() {
  document.getElementById('loading-indicator').classList.remove('hidden');
}

function ocultarCargando() {
  document.getElementById('loading-indicator').classList.add('hidden');
}

document.getElementById('error-retry').addEventListener('click', () => {
  ocultarError();
  cargarPaginaActual();
});

function actualizarBadgeCocheras(cocheras) {
  const badges = document.querySelectorAll('.cocheras-badge');
  const hayAviso = cocheras && cocheras.sin_identificar > 0;
  badges.forEach((b) => {
    b.classList.toggle('hidden', !hayAviso);
    if (hayAviso) b.textContent = cocheras.sin_identificar;
  });
}

async function cargarPaginaActual() {
  const titulo = tituloMesActual();
  if (!titulo) return;

  mostrarCargando();
  ocultarError();
  try {
    if (paginaActual === 'resumen') {
      const data = await fetchJSON(`/api/dashboard?mes=${mesQuery()}`);
      renderResumen(data);
    } else if (paginaActual === 'ingresos') {
      ingresosDelMes = await fetchJSON(`/api/ingresos?mes=${mesQuery()}`);
      renderIngresos();
    } else if (paginaActual === 'gastos') {
      gastosDelMes = await fetchJSON(`/api/gastos?mes=${mesQuery()}`);
      renderGastos();
    } else if (paginaActual === 'cocheras') {
      const data = await fetchJSON(`/api/dashboard?mes=${mesQuery()}`);
      cocherasDelMes = data.cocheras;
      actualizarBadgeCocheras(data.cocheras);
      renderCocheras();
    }
    ocultarError();
  } catch (e) {
    if (e.message === '401') return; // ya se mostró la pantalla de login
    mostrarError(mensajeDeError(e));
  } finally {
    ocultarCargando();
  }
}

function mesQuery() {
  const actual = meses[mesIndex];
  return `${encodeURIComponent(actual.mes)}&anio=${actual.anio}`;
}

// ── Resumen ──────────────────────────────────────────────────────────────
function renderResumen(data) {
  document.getElementById('hero-ganancia').textContent = data.ganancia_mes_fmt;
  document.getElementById('tile-ingreso-bruto').textContent = data.ingreso_bruto_fmt;
  document.getElementById('tile-ingreso-neto').textContent = data.ingreso_neto_fmt;
  document.getElementById('tile-transferencias').textContent = data.total_transferencias_fmt;
  document.getElementById('tile-efectivo').textContent = data.total_efectivo_fmt;
  document.getElementById('tile-gastos').textContent = data.total_gastos_fmt;

  const pct = Math.min(data.progreso_pct, 1);
  const fill = document.getElementById('meter-fill');
  fill.style.width = `${pct * 100}%`;
  fill.classList.toggle('completo', data.progreso_pct >= 1);
  document.getElementById('meter-entregado').textContent =
    `${data.entregado_a_socios_fmt} (${Math.round(data.progreso_pct * 100)}%)`;
  document.getElementById('meter-objetivo').textContent = `Meta: ${data.objetivo_rendicion_fmt}`;

  const badge = document.getElementById('badge-deuda');
  if (data.deuda_heredada > 0) {
    badge.classList.remove('hidden');
    document.getElementById('badge-deuda-texto').textContent =
      `Arrastra ${data.deuda_heredada_fmt} de meses anteriores`;
  } else {
    badge.classList.add('hidden');
  }

  document.getElementById('resumen-cocheras-cobradas').textContent = data.cocheras.cobradas;
  document.getElementById('resumen-cocheras-total').textContent = `de ${data.cocheras.total} cobradas`;

  actualizarBadgeCocheras(data.cocheras);
}

// Crea un elemento con texto plano (nunca HTML) — los datos que renderizamos
// vienen de un Google Sheet que el dueño edita a mano sin sanitizar, así que
// nunca deben insertarse como innerHTML (evita XSS si una celda tuviera un
// tag <script> u otro HTML).
function crearEl(tag, className, texto) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (texto !== undefined) el.textContent = texto;
  return el;
}

// ── Ingresos ─────────────────────────────────────────────────────────────
function renderIngresos() {
  const datos = ingresosDelMes;
  const f = filtros.ingresos;

  const filtrados = datos.filter((r) => {
    if (f.tipoPago !== 'TODOS' && r.tipo_pago !== f.tipoPago) return false;
    if (f.texto) {
      const q = f.texto.toLowerCase();
      const cochera = String(r.cochera).toLowerCase();
      if (!r.nombre.toLowerCase().includes(q) && !cochera.includes(q)) return false;
    }
    return true;
  });

  const cont = document.getElementById('ingresos-lista');
  cont.innerHTML = '';
  if (filtrados.length === 0) {
    cont.innerHTML = '<div class="empty-state">Sin ingresos que coincidan.</div>';
    return;
  }
  filtrados.forEach((r) => {
    const div = crearEl('div', 'lista-item');

    const info = crearEl('span', 'info');
    info.appendChild(crearEl('span', 'titulo', `${r.nombre} — Cochera ${r.cochera}`));

    const subtitulo = crearEl('span', 'subtitulo');
    subtitulo.append(`${r.fecha} · `);
    subtitulo.appendChild(crearEl('span', 'tag tag-tipo', r.tipo_pago));
    info.appendChild(subtitulo);

    div.appendChild(info);
    div.appendChild(crearEl('span', 'monto', r.monto_fmt));
    cont.appendChild(div);
  });
}

document.querySelectorAll('#chips-tipo-pago .chip').forEach((chip) => {
  chip.addEventListener('click', () => {
    document.querySelectorAll('#chips-tipo-pago .chip').forEach((c) => c.classList.remove('active'));
    chip.classList.add('active');
    filtros.ingresos.tipoPago = chip.dataset.value;
    renderIngresos();
  });
});

document.getElementById('buscar-ingresos').addEventListener('input', (e) => {
  filtros.ingresos.texto = e.target.value.trim();
  renderIngresos();
});

// ── Gastos ───────────────────────────────────────────────────────────────
function renderGastos() {
  const datos = gastosDelMes;
  const q = filtros.gastos.texto.toLowerCase();

  const filtrados = q
    ? datos.filter((g) => g.categoria.toLowerCase().includes(q) || g.descripcion.toLowerCase().includes(q))
    : datos;

  const cont = document.getElementById('gastos-lista');
  cont.innerHTML = '';
  if (filtrados.length === 0) {
    cont.innerHTML = '<div class="empty-state">Sin gastos que coincidan.</div>';
    return;
  }
  filtrados.forEach((g) => {
    const div = crearEl('div', 'lista-item');

    const info = crearEl('span', 'info');
    info.appendChild(crearEl('span', 'titulo', g.categoria));
    info.appendChild(crearEl('span', 'subtitulo', `${g.fecha} · ${g.descripcion}`));

    div.appendChild(info);
    div.appendChild(crearEl('span', 'monto', g.monto_fmt));
    cont.appendChild(div);
  });
}

document.getElementById('buscar-gastos').addEventListener('input', (e) => {
  filtros.gastos.texto = e.target.value.trim();
  renderGastos();
});

// ── Cocheras ─────────────────────────────────────────────────────────────
function renderCocheras() {
  const datos = cocherasDelMes;
  if (!datos) return;

  const avisoSinId = document.getElementById('cocheras-sin-identificar');
  if (datos.sin_identificar > 0) {
    avisoSinId.classList.remove('hidden');
    avisoSinId.textContent =
      `${datos.sin_identificar} cobro(s) con "DOBLE" genérico (formato viejo) sin cochera identificada.`;
  } else {
    avisoSinId.classList.add('hidden');
  }

  const f = filtros.cocheras;
  const filtradas = datos.todas.filter((c) => {
    if (f.estado === 'COBRADAS' && !c.cobrada) return false;
    if (f.estado === 'PENDIENTES' && c.cobrada) return false;
    if (f.tipo !== 'TODOS' && c.tipo !== f.tipo) return false;
    if (f.texto) {
      const q = f.texto.toLowerCase();
      if (!String(c.nro).includes(q) && !c.nombre.toLowerCase().includes(q)) return false;
    }
    return true;
  });

  const cont = document.getElementById('cocheras-lista');
  cont.innerHTML = '';
  if (filtradas.length === 0) {
    cont.innerHTML = '<div class="empty-state">No hay cocheras que coincidan.</div>';
    return;
  }
  filtradas.forEach((c) => {
    const div = crearEl('div', 'lista-item');
    const nombre = c.nombre || (c.vacia ? '(vacía)' : '(sin nombre)');

    const info = crearEl('span', 'info');
    info.appendChild(crearEl('span', 'titulo', `${c.nro} — ${nombre}`));
    const subtitulo = crearEl('span', 'subtitulo');
    subtitulo.appendChild(crearEl('span', 'tag tag-tipo', c.tipo));
    info.appendChild(subtitulo);

    div.appendChild(info);
    div.appendChild(crearEl(
      'span',
      `tag ${c.cobrada ? 'tag-cobrada' : 'tag-pendiente'}`,
      c.cobrada ? 'Cobrada' : 'Pendiente'
    ));
    cont.appendChild(div);
  });
}

['chips-estado-cochera', 'chips-tipo-cochera'].forEach((id) => {
  document.querySelectorAll(`#${id} .chip`).forEach((chip) => {
    chip.addEventListener('click', () => {
      document.querySelectorAll(`#${id} .chip`).forEach((c) => c.classList.remove('active'));
      chip.classList.add('active');
      if (id === 'chips-estado-cochera') filtros.cocheras.estado = chip.dataset.value;
      else filtros.cocheras.tipo = chip.dataset.value;
      renderCocheras();
    });
  });
});

document.getElementById('buscar-cocheras').addEventListener('input', (e) => {
  filtros.cocheras.texto = e.target.value.trim();
  renderCocheras();
});

// ── Init ─────────────────────────────────────────────────────────────────
async function init() {
  try {
    meses = await fetchJSON('/api/meses');
  } catch (e) {
    return;
  }
  if (meses.length === 0) {
    document.getElementById('mes-label').textContent = 'Sin datos';
    return;
  }
  mesIndex = meses.length - 1; // mes más reciente
  actualizarSelectorMes();
  mostrarPagina('resumen');
}

if (token()) {
  mostrarApp();
  init();
} else {
  mostrarLogin();
}

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js');
}
