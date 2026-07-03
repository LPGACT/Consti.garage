const TOKEN_KEY = 'dashboard_password';

const loginView = document.getElementById('login-view');
const appView = document.getElementById('app');
const loginError = document.getElementById('login-error');

let meses = [];       // [{mes, anio, titulo}], orden cronológico
let mesIndex = -1;
let gastosDelMes = [];

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
  loginView.classList.remove('hidden');
  appView.classList.add('hidden');
}

function mostrarApp() {
  loginView.classList.add('hidden');
  appView.classList.remove('hidden');
}

document.getElementById('login-btn').addEventListener('click', async () => {
  const password = document.getElementById('password').value;
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
});

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

async function cargarMesActual() {
  const actual = meses[mesIndex];
  if (!actual) return;
  actualizarSelectorMes();
  await Promise.all([
    cargarDashboard(actual.mes, actual.anio),
    cargarGastos(actual.mes, actual.anio),
  ]);
}

function fmtPct(pct) {
  return `${Math.round(pct * 100)}%`;
}

async function cargarDashboard(mes, anio) {
  let data;
  try {
    data = await fetchJSON(`/api/dashboard?mes=${encodeURIComponent(mes)}&anio=${anio}`);
  } catch (e) {
    return;
  }

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
    `${data.entregado_a_socios_fmt} (${fmtPct(data.progreso_pct)})`;
  document.getElementById('meter-objetivo').textContent = `Meta: ${data.objetivo_rendicion_fmt}`;

  const badge = document.getElementById('badge-deuda');
  if (data.deuda_heredada > 0) {
    badge.classList.remove('hidden');
    document.getElementById('badge-deuda-texto').textContent =
      `Arrastra ${data.deuda_heredada_fmt} de meses anteriores`;
  } else {
    badge.classList.add('hidden');
  }

  const cocheras = data.cocheras;
  document.getElementById('cocheras-cobradas').textContent = cocheras.cobradas;
  document.getElementById('cocheras-total').textContent = `de ${cocheras.total} cobradas`;

  const avisoSinId = document.getElementById('cocheras-sin-identificar');
  if (cocheras.sin_identificar > 0) {
    avisoSinId.classList.remove('hidden');
    avisoSinId.textContent =
      `${cocheras.sin_identificar} cobro(s) con "DOBLE" genérico (formato viejo) sin cochera identificada.`;
  } else {
    avisoSinId.classList.add('hidden');
  }

  const lista = document.getElementById('pendientes-lista');
  lista.innerHTML = '';
  if (cocheras.pendientes.length === 0) {
    lista.innerHTML = '<div class="empty-state">No hay cocheras pendientes.</div>';
  }
  cocheras.pendientes.forEach((p) => {
    const div = document.createElement('div');
    div.className = 'pendiente-item';
    div.innerHTML = `
      <span>${p.nro} — ${p.nombre || (p.vacia ? '(vacía)' : '(sin nombre)')}</span>
      <span class="tag">${p.tipo}</span>
    `;
    lista.appendChild(div);
  });
}

async function cargarGastos(mes, anio) {
  try {
    gastosDelMes = await fetchJSON(`/api/gastos?mes=${encodeURIComponent(mes)}&anio=${anio}`);
  } catch (e) {
    gastosDelMes = [];
  }
  renderGastos(gastosDelMes);
}

function renderGastos(lista) {
  const cont = document.getElementById('gastos-lista');
  cont.innerHTML = '';
  if (lista.length === 0) {
    cont.innerHTML = '<div class="empty-state">Sin gastos que coincidan.</div>';
    return;
  }
  lista.forEach((g) => {
    const div = document.createElement('div');
    div.className = 'gasto-item';
    div.innerHTML = `
      <span class="info">
        <span class="categoria">${g.categoria}</span>
        <span class="descripcion">${g.descripcion}</span>
      </span>
      <span class="monto">${g.monto_fmt}</span>
    `;
    cont.appendChild(div);
  });
}

document.getElementById('buscar-gastos').addEventListener('input', (e) => {
  const q = e.target.value.trim().toLowerCase();
  const filtrados = gastosDelMes.filter(
    (g) => g.categoria.toLowerCase().includes(q) || g.descripcion.toLowerCase().includes(q)
  );
  renderGastos(filtrados);
});

document.getElementById('mes-prev').addEventListener('click', () => {
  if (mesIndex > 0) {
    mesIndex -= 1;
    cargarMesActual();
  }
});

document.getElementById('mes-next').addEventListener('click', () => {
  if (mesIndex < meses.length - 1) {
    mesIndex += 1;
    cargarMesActual();
  }
});

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
  await cargarMesActual();
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
