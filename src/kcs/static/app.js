// ── Entry point ─────────────────────────────────────────────────────────────
import { R, schedulePoll } from './state.js';

// Side-effect imports: register window-bound functions and render logic
import './utils.js';
import './topo.js';
import './panel.js';
import './actions.js';

document.addEventListener('keydown', e => { if (e.key === 'Escape') window.closePanel(); });
document.addEventListener('click', e => {
  if (!document.getElementById('p').classList.contains('show')) return;
  if (e.target.closest('.card') || e.target.closest('.actions')) return;
  if (!e.target.closest('#p')) window.closePanel();
});

R().then(() => schedulePoll());
