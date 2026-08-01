// ── Formatting & UI utilities ──────────────────────────────────────────────

export function fmtCPU(v) {
  if (v == null) return '?';
  if (typeof v === 'string') return v;
  if (v >= 1) return v % 1 === 0 ? v.toString() : v.toFixed(1);
  return (v * 1000).toFixed(0) + 'm';
}

export function fmtMem(v) {
  if (v == null) return '?';
  if (typeof v === 'string') return v;
  if (v >= 1024 ** 3) return (v / 1024 ** 3).toFixed(v % 1024 ** 3 === 0 ? 0 : 0) + 'Gi';
  if (v >= 1024 ** 2) return (v / 1024 ** 2).toFixed(0) + 'Mi';
  if (v >= 1024) return (v / 1024).toFixed(0) + 'Ki';
  return v + 'B';
}

export function _toast(msg, duration = 2500) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._tid);
  t._tid = setTimeout(() => t.classList.remove('show'), duration);
}

export function filterItems(input) {
  const q = input.value.toLowerCase();
  const panel = document.getElementById('pb');
  const items = panel.querySelectorAll('.item');
  items.forEach(el => {
    const text = el.textContent.toLowerCase();
    el.style.display = (!q || text.includes(q)) ? '' : 'none';
  });
  const sections = panel.querySelectorAll('h4');
  sections.forEach(h4 => {
    let next = h4.nextElementSibling;
    let hasVisible = false;
    while (next && next.tagName !== 'H4') {
      if (next.classList.contains('item') && next.style.display !== 'none') hasVisible = true;
      next = next.nextElementSibling;
    }
    h4.style.display = hasVisible || !q ? '' : 'none';
  });
}

export function resSummary(c) {
  const r = c.resources || {};
  const parts = [];
  if (r['nvidia.com/gpu']) parts.push('GPU:' + r['nvidia.com/gpu']);
  if (r.cpu) parts.push('CPU:' + r.cpu);
  if (r.memory) parts.push('Mem:' + r.memory);
  if (!parts.length) return '';
  return `<span style="font-size:9px;color:var(--dim);margin-left:4px">${parts.join(' ')}</span>`;
}

export function containerActs(c) {
  if (c.status === 'running') return `<button onclick="event.stopPropagation();doStop('${c.name}')" title="stop">⏹</button>`;
  if (c.status === 'stopped') return `<button onclick="event.stopPropagation();doStart('${c.name}')" title="start">▶</button>`;
  if (c.status === 'terminating') return `<span style="font-size:9px;color:var(--amber)">stopping…</span>`;
  return '';
}

// ── Window bindings for HTML onclick handlers ─────────────────────────────
window.filterItems = filterItems;
