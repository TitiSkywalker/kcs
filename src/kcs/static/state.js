// ── Global state & API layer ───────────────────────────────────────────────
// Shared mutable state lives on window (accessible from all modules + inline HTML)
window.A = '/api/v1';
window.data = null;
window._view = null;
window._lastNodeView = null;
window._proxies = [];
window._proxyFormOpen = null;
window._proxyFormSession = '';
window._loading = true;
window._loadError = null;
window._fastUntil = 0;
window._pollTimer = null;
window.POLL_SLOW = 2000;
window.POLL_FAST = 800;

function speedUp(seconds = 6) {
  window._fastUntil = Math.max(window._fastUntil, Date.now() + seconds * 1000);
}

function schedulePoll() {
  clearTimeout(window._pollTimer);
  const delay = Date.now() < window._fastUntil ? window.POLL_FAST : window.POLL_SLOW;
  window._pollTimer = setTimeout(() => { R().then(() => schedulePoll()); }, delay);
}

import { render } from './topo.js';

async function R() {
  try {
    const newData = await api('GET', '/status');
    window.data = newData;
    window._loading = false;
    window._loadError = null;
    try { window._proxies = (await api('GET', '/shell-proxy')).proxies || []; }
    catch (e) { window._proxies = []; }
    render();
  } catch (e) {
    window._loadError = e.message;
    if (window._loading) render();
  }
}

window.manualRefresh = function () {
  const btn = document.getElementById('refresh-btn');
  btn.classList.add('spinning');
  R().then(() => { btn.classList.remove('spinning'); schedulePoll(); });
};

function _apiKey() {
  return sessionStorage.getItem('kcs_api_key') || '';
}

let _pendingAuth = null;

window.showLogin = function () {
  document.getElementById('login-overlay').style.display = '';
  document.getElementById('login-input').value = '';
  document.getElementById('login-err').style.display = 'none';
  document.getElementById('login-input').focus();
};

window.doLogin = async function () {
  const key = document.getElementById('login-input').value.trim();
  if (!key) return;
  try {
    const r = await fetch(window.A + '/status', { headers: { 'Authorization': 'Bearer ' + key } });
    if (r.ok) {
      sessionStorage.setItem('kcs_api_key', key);
      document.getElementById('login-overlay').style.display = 'none';
      if (_pendingAuth) { _pendingAuth(); _pendingAuth = null; }
      R();
      return;
    }
  } catch (e) { }
  document.getElementById('login-err').style.display = '';
  document.getElementById('login-input').focus();
};

async function api(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  const key = _apiKey();
  if (key) opts.headers['Authorization'] = 'Bearer ' + key;
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(window.A + path, opts);
  if (r.status === 401) {
    return new Promise((resolve, reject) => {
      _pendingAuth = async () => {
        try {
          const key2 = _apiKey();
          opts.headers['Authorization'] = 'Bearer ' + key2;
          const retry = await fetch(window.A + path, opts);
          if (!retry.ok) {
            const d = await retry.json().catch(() => ({}));
            reject(new Error(d.detail || retry.statusText));
            return;
          }
          resolve(retry.json().catch(() => ({})));
        } catch (e) { reject(e); }
      };
      window.showLogin();
    });
  }
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || r.statusText);
  }
  return r.json().catch(() => ({}));
}

// ── Exports for other modules ─────────────────────────────────────────────
export { R, schedulePoll, speedUp, api };
