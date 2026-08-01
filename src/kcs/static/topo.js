// ── Topology rendering & panel shell ────────────────────────────────────────
import { fmtCPU, fmtMem } from './utils.js';

export function render() {
  if (window._loading) {
    document.getElementById('topo').innerHTML =
      '<div class="loading"><div class="skel"></div><div style="margin-top:12px;font-size:11px">loading cluster...</div></div>';
    return;
  }
  if (window._loadError) {
    document.getElementById('topo').innerHTML =
      `<div class="loading"><div style="font-size:12px;color:var(--red);margin-bottom:8px">Unable to reach server</div><div style="font-size:10px;color:var(--dim)">${window._loadError}</div></div>`;
    return;
  }
  const { server, workers, containers, images, nfs } = window.data;

  const allNodes = [server, ...workers];
  window._maxHW = { cpu: 0, memory: 0, gpu: 0, storage: 0 };
  allNodes.forEach(n => {
    const a = n.allocatable || n.capacity || {};
    window._maxHW.cpu = Math.max(window._maxHW.cpu, a.cpu || 0);
    window._maxHW.memory = Math.max(window._maxHW.memory, a.memory || 0);
    window._maxHW.gpu = Math.max(window._maxHW.gpu, a.gpu || 0);
    window._maxHW.storage = Math.max(window._maxHW.storage, a.storage || 0);
  });

  const topo = document.getElementById('topo');
  if (!topo.querySelector('.card')) {
    _renderTopo();
  } else {
    _updateSummaries();
    drawLines();
  }
  highlightCard();
}

// ── Hardware bars ──────────────────────────────────────────────────────────

export function hwBar(label, used, total, maxTotal) {
  if (!total && !used) return '';
  const pct = total > 0 ? Math.min(100, (used / total) * 100) : 0;
  const width = maxTotal > 0 ? Math.max(2, (total / maxTotal) * 100) : 100;
  const fill = pct > 0 ? `<span class="bar-fill" style="width:${pct}%"></span>` : '';
  const cls = pct > 90 ? 'bar high' : 'bar';
  return `<div class="item" style="display:block;padding:6px 10px">
    <div style="display:flex;justify-content:space-between;margin-bottom:3px">
      <span>${label}</span>
      <span class="mono">${fmtCPU(used)} / ${fmtCPU(total)}</span>
    </div>
    <div class="${cls}" style="width:${width}%">${fill}</div>
  </div>`;
}

export function hwMemBar(label, used, total, maxTotal) {
  if (!total && !used) return '';
  const pct = total > 0 ? Math.min(100, (used / total) * 100) : 0;
  const width = maxTotal > 0 ? Math.max(2, (total / maxTotal) * 100) : 100;
  const fill = pct > 0 ? `<span class="bar-fill" style="width:${pct}%"></span>` : '';
  const cls = pct > 90 ? 'bar high' : 'bar';
  return `<div class="item" style="display:block;padding:6px 10px">
    <div style="display:flex;justify-content:space-between;margin-bottom:3px">
      <span>${label}</span>
      <span class="mono">${fmtMem(used)} / ${fmtMem(total)}</span>
    </div>
    <div class="${cls}" style="width:${width}%">${fill}</div>
  </div>`;
}

export function hwSection(node) {
  const a = node.allocatable || node.capacity || {};
  const u = node.used || {};
  const cpu = a.cpu || 0, mem = a.memory || 0, gpu = a.gpu || 0, storage = a.storage || 0;
  const maxHW = window._maxHW || {};
  const bars = [];
  if (cpu > 0) bars.push(hwBar('CPU', u.cpu || 0, cpu, maxHW.cpu || cpu));
  if (mem > 0) bars.push(hwMemBar('Memory', u.memory || 0, mem, maxHW.memory || mem));
  if (gpu > 0) bars.push(hwBar('GPU', u.gpu || 0, gpu, maxHW.gpu || gpu));
  if (storage > 0) bars.push(hwMemBar('Disk', u.storage || 0, storage, maxHW.storage || storage));
  if (!bars.length) return '';
  return `<h4>hardware</h4>${bars.join('')}`;
}

// ── Panel shell ────────────────────────────────────────────────────────────

export function open(html) {
  document.getElementById('pb').innerHTML = html;
  document.getElementById('p').classList.add('show');
  document.body.classList.add('panel-open');
}

window.closePanel = function () {
  window._view = null;
  window._lastNodeView = null;
  window._proxyFormOpen = null;
  highlightCard();
  document.getElementById('p').classList.remove('show');
  document.body.classList.remove('panel-open');
};

export function highlightCard() {
  document.querySelectorAll('.card.active').forEach(c => c.classList.remove('active'));
  let v = window._view;
  if (v && v.type === 'container') v = window._lastNodeView;
  if (!v) return;
  if (v.type === 'server') {
    const el = document.getElementById('card-server');
    if (el) el.classList.add('active');
  } else if (v.type === 'worker') {
    const el = document.getElementById('card-w' + v.i);
    if (el) el.classList.add('active');
  }
}

export function drawLines() {
  const topo = document.getElementById('topo');
  const svg = document.getElementById('lines');
  const server = document.getElementById('card-server');
  if (!topo || !svg || !server) return;
  const tr = topo.getBoundingClientRect();
  const sr = server.getBoundingClientRect();
  const sx = sr.left + sr.width / 2 - tr.left;
  const sy = sr.bottom - tr.top;
  let paths = '';
  for (let i = 0; ; i++) {
    const w = document.getElementById('card-w' + i);
    if (!w) break;
    const wr = w.getBoundingClientRect();
    const ex = wr.left + wr.width / 2 - tr.left;
    const ey = wr.top - tr.top;
    const cy1 = sy + (ey - sy) * 0.4;
    const cy2 = sy + (ey - sy) * 0.6;
    paths += `<path d="M${sx},${sy} C${sx},${cy1} ${ex},${cy2} ${ex},${ey}" />`;
  }
  svg.setAttribute('viewBox', `0 0 ${tr.width} ${tr.height}`);
  svg.setAttribute('width', tr.width);
  svg.setAttribute('height', tr.height);
  svg.innerHTML = paths;
}

export function refreshPanel() {
  if (!document.getElementById('p').classList.contains('show')) return;
  if (!window._view) return;
  if (window._view.type === 'server') window.showServer();
  else if (window._view.type === 'worker') window.showWorker(window._view.i);
  else if (window._view.type === 'container') window.showContainer(window._view.name);
}

// ── Full initial render ────────────────────────────────────────────────────

function _renderTopo() {
  const { server, workers, containers, images, nfs } = window.data;

  const allNodes = [server, ...workers];
  window._maxHW = { cpu: 0, memory: 0, gpu: 0, storage: 0 };
  allNodes.forEach(n => {
    const a = n.allocatable || n.capacity || {};
    window._maxHW.cpu = Math.max(window._maxHW.cpu, a.cpu || 0);
    window._maxHW.memory = Math.max(window._maxHW.memory, a.memory || 0);
    window._maxHW.gpu = Math.max(window._maxHW.gpu, a.gpu || 0);
    window._maxHW.storage = Math.max(window._maxHW.storage, a.storage || 0);
  });

  let h = `<svg class="lines" id="lines"></svg>`;
  const sres = server.allocatable || server.capacity;
  let serverSum = `${images.length} images · ${containers.length} containers`;
  if (sres) serverSum += ` · ${fmtCPU(sres.cpu || 0)} cpu · ${fmtMem(sres.memory || 0)}`;

  h += `<div class="card server" id="card-server" onclick="showServer()">
    <div class="kind"><span class="dot ${server.status === 'Ready' ? 'on' : 'off'}"></span>server</div>
    <div class="name">${server.name}</div>
    <div class="ip">${server.ip}</div>
    <div class="summary">${serverSum}${nfs ? ' · nfs' : ''}</div>
  </div>`;

  if (workers.length) {
    h += `<div class="workers">`;
    workers.forEach((w, i) => {
      const pods = containers.filter(c => c.node && c.node === w.ip);
      const running = pods.filter(c => c.status === 'running').length;
      const wr = w.allocatable || w.capacity || {};
      const wu = w.used || {};
      let wSum = `${pods.length} container${pods.length !== 1 ? 's' : ''} · ${running} up`;
      if (wr.cpu) wSum += ` · ${fmtCPU(wu.cpu || 0)}/${fmtCPU(wr.cpu)} cpu`;
      if (wr.gpu > 0) wSum += ` · ${wu.gpu || 0}/${wr.gpu} gpu`;
      if (w.disk_pressure) wSum += ` · <span style="color:var(--red)" title="disk pressure">disk</span>`;
      if (w.memory_pressure) wSum += ` · <span style="color:var(--red)" title="memory pressure">mem</span>`;
      if (w.pid_pressure) wSum += ` · <span style="color:var(--red)" title="pid pressure">pid</span>`;
      h += `<div class="card" id="card-w${i}" onclick="showWorker(${i})">
        <div class="kind"><span class="dot ${w.status === 'Ready' ? 'on' : 'off'}"></span>worker</div>
        <div class="name">${w.name}</div>
        <div class="ip">${w.ip}</div>
        <div class="summary">${wSum}</div>
      </div>`;
    });
    h += `</div>`;
  }
  document.getElementById('topo').innerHTML = h;
  window._workers = workers;
  setTimeout(drawLines, 20);
}

// ── In-place summary updates (no flicker) ──────────────────────────────────

export function _updateSummaries() {
  const { server, workers, containers, images, nfs } = window.data;

  const sres = server.allocatable || server.capacity;
  let serverSum = `${images.length} images · ${containers.length} containers`;
  if (sres) serverSum += ` · ${fmtCPU(sres.cpu || 0)} cpu · ${fmtMem(sres.memory || 0)}`;

  const sc = document.getElementById('card-server');
  if (sc) {
    const dot = sc.querySelector('.dot');
    if (dot) dot.className = 'dot ' + (server.status === 'Ready' ? 'on' : 'off');
    const sm = sc.querySelector('.summary');
    if (sm) sm.textContent = serverSum + (nfs ? ' · nfs' : '');
  }

  workers.forEach((w, i) => {
    const card = document.getElementById('card-w' + i);
    if (!card) return;
    const dot = card.querySelector('.dot');
    if (dot) dot.className = 'dot ' + (w.status === 'Ready' ? 'on' : 'off');
    const pods = containers.filter(c => c.node && c.node === w.ip);
    const running = pods.filter(c => c.status === 'running').length;
    const wr = w.allocatable || w.capacity || {};
    const wu = w.used || {};
    let wSum = `${pods.length} container${pods.length !== 1 ? 's' : ''} · ${running} up`;
    if (wr.cpu) wSum += ` · ${fmtCPU(wu.cpu || 0)}/${fmtCPU(wr.cpu)} cpu`;
    if (wr.gpu > 0) wSum += ` · ${wu.gpu || 0}/${wr.gpu} gpu`;
    const sm = card.querySelector('.summary');
    if (sm) {
      const warnings = [];
      if (w.disk_pressure) warnings.push(`<span style="color:var(--red)" title="disk pressure">disk</span>`);
      if (w.memory_pressure) warnings.push(`<span style="color:var(--red)" title="memory pressure">mem</span>`);
      if (w.pid_pressure) warnings.push(`<span style="color:var(--red)" title="pid pressure">pid</span>`);
      if (warnings.length) {
        sm.innerHTML = wSum + ' · ' + warnings.join(' · ');
      } else {
        sm.textContent = wSum;
      }
    }
  });
}
