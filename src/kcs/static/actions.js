// ── Container CRUD & proxy operations ────────────────────────────────────────
import { api, R, schedulePoll, speedUp } from './state.js';
import { _toast } from './utils.js';
import { refreshPanel } from './topo.js';
import './panel.js';  // ensure panel functions registered on window

// ── Create ─────────────────────────────────────────────────────────────────

window.doCreate = async function () {
  const m = document.getElementById('f-msg');
  m.className = 'msg'; m.textContent = '';
  const g = (id) => document.getElementById(id).value.trim();
  const portsRaw = g('f-ports');
  const ports = portsRaw ? portsRaw.split(',').map(s => parseInt(s.trim())).filter(Boolean) : null;
  const body = {
    image: g('f-image'),
    name: g('f-name') || null,
    ports,
    replicas: parseInt(document.getElementById('f-replicas').value) || 1,
    node: document.getElementById('f-node').value || null,
    volumes: g('f-volumes') ? g('f-volumes').split(',').map(s => s.trim()).filter(Boolean) : null,
    gpus: g('f-gpus') ? parseInt(g('f-gpus')) : null,
    cpu: g('f-cpu') || null,
    memory: g('f-memory') || null,
  };
  if (!body.image) { m.className = 'msg err'; m.textContent = 'Image is required'; return; }
  try {
    await api('POST', '/containers', body);
    m.className = 'msg ok'; m.textContent = 'Created.';
    speedUp(6);
    setTimeout(() => { R(); window.closePanel(); }, 800);
  } catch (e) { m.className = 'msg err'; m.textContent = e.message; }
};

// ── Start / Stop / Delete ──────────────────────────────────────────────────

window.doStop = async function (name) {
  const c = (window.data.containers || []).find(c => c.name === name);
  if (c) c.status = 'terminating';
  refreshPanel();
  speedUp(8);
  try { await api('POST', `/containers/${name}/stop`); }
  catch (e) { _toast('Stop failed: ' + e.message); }
  await R();
  schedulePoll();
};

window.doStart = async function (name) {
  const c = (window.data.containers || []).find(c => c.name === name);
  if (c) c.status = 'pending';
  refreshPanel();
  speedUp(8);
  try { await api('POST', `/containers/${name}/start`); }
  catch (e) { _toast('Start failed: ' + e.message); }
  await R();
  schedulePoll();
};

window.doDelete = async function (name) {
  if (!confirm(`Delete '${name}'?`)) return;
  speedUp(4);
  try {
    await api('DELETE', `/containers/${name}?force=true`);
    await R();
    if (window._view && window._view.type === 'container') window.showServer();
    else refreshPanel();
  } catch (e) { _toast('Delete failed: ' + e.message); }
  schedulePoll();
};

// ── Shell proxy ────────────────────────────────────────────────────────────

window.toggleProxyForm = function (name) {
  window._proxyFormOpen = name;
  window._proxyFormSession = '';
  const id = name.replace(/[^a-zA-Z0-9]/g, '');
  const btn = document.querySelector('#pb button[onclick*="toggleProxyForm"]');
  const form = document.getElementById('pf-' + id);
  if (btn) btn.style.display = 'none';
  if (form) form.style.display = '';
  const input = document.getElementById('pfi-' + id);
  if (input) setTimeout(() => input.focus(), 50);
};

window.hideProxyForm = function (name) {
  window._proxyFormOpen = null;
  window._proxyFormSession = '';
  const id = name.replace(/[^a-zA-Z0-9]/g, '');
  const btn = document.querySelector('#pb button[onclick*="toggleProxyForm"]');
  const form = document.getElementById('pf-' + id);
  if (btn) btn.style.display = '';
  if (form) form.style.display = 'none';
};

window.doStartProxy = async function (name) {
  const session = window._proxyFormSession.trim();
  window._proxyFormSession = '';
  window.hideProxyForm(name);
  try {
    await api('POST', '/shell-proxy/start', { container: name, session });
    speedUp(4);
    await R();
    if (window._view.type === 'container') window.showContainer(window._view.name);
  } catch (e) { _toast('Proxy start failed: ' + e.message); }
};

window.copyProxy = async function (wrapper) {
  const cmd = `CLAUDE_CODE_SHELL=${wrapper} claude`;
  try { await navigator.clipboard.writeText(cmd); }
  catch (e) {
    const ta = document.createElement('textarea');
    ta.value = cmd; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); document.body.removeChild(ta);
  }
  _toast('Copied', 1500);
};

window.stopProxy = async function (container, session) {
  try {
    await api('POST', `/shell-proxy/stop?container=${encodeURIComponent(container)}&session=${encodeURIComponent(session || '')}`);
    speedUp(3);
    await R();
    if (window._view.type === 'container') window.showContainer(window._view.name);
  } catch (e) { _toast('Proxy stop failed: ' + e.message); }
};

window.doDeleteImage = async function (tag) {
  if (!confirm(`Forget image '${tag}'?`)) return;
  try {
    await api('DELETE', `/images/${encodeURIComponent(tag)}`);
    speedUp(3);
    await R();
    window.showServer();
  } catch (e) { _toast('Delete failed: ' + e.message); }
};
