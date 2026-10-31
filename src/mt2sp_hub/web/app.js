'use strict';
const el = id => document.getElementById(id);
let token = location.hash.slice(1);
history.replaceState(null, '', '/');
try {
  if (token) sessionStorage.setItem('hub-session', token);
  else token = sessionStorage.getItem('hub-session') || '';
} catch (_) { /* The current tab still works when browser storage is unavailable. */ }
let state = null;
let pending = false;
let connected = false;
let shownRoot = null;

function controls() {
  const active = connected && state && !pending && !state.busy && !state.stopped;
  const normal = active && !state.review;
  const ready = normal && state.ready;
  const allowed = {
    folder: active, select: active, check: normal && state.root,
    attach: normal && state.setup_ready, recover: normal && state.root,
    archive: ready, import: ready && el('archive').files.length,
    confirm: active && state.review, cancel: active && state.review, stop: active
  };
  for (const [id, enabled] of Object.entries(allowed)) el(id).disabled = !enabled;
  document.querySelectorAll('[data-package]').forEach(button => { button.disabled = !ready; });
}

function render(next) {
  if (state && next.revision < state.revision) return;
  const changed = !state || state.revision !== next.revision || !connected;
  state = next;
  connected = true;
  if (changed) {
    if (shownRoot !== state.root) {
      el('folder').value = state.root;
      shownRoot = state.root;
    }
    el('selected-folder').textContent = state.root ? 'Selected: ' + state.root : '';
    el('kind').textContent = state.kind === 'synthetic' ? 'Practice sandbox - synthetic files only' : 'Engineering preview';
    el('notice').textContent = state.stopped ? state.message : state.busy
      ? 'Working on your installation. This can take a few minutes. Keep the launcher running.'
      : state.review ? 'Review ready. Read the changes below, then confirm or cancel.'
      : state.recovery_required ? 'Recovery needed. Review recovery before changing add-ons.' : state.message.split('\n')[0];
    el('notice').className = state.error ? 'error' : state.recovery_required ? 'warning' : '';
    el('details').textContent = state.review ? state.review.text : state.message;
    el('review-state').textContent = state.busy ? 'Working...' : state.review ? 'Ready for your review' : 'No review';
    const rows = state.packages.map(item => {
      const row = document.createElement('tr');
      const name = document.createElement('td');
      name.textContent = item.id;
      const version = document.createElement('small');
      version.textContent = item.version;
      name.append(version);
      const enabled = document.createElement('td');
      enabled.textContent = item.enabled ? 'Enabled' : 'Disabled';
      const actions = document.createElement('td');
      for (const action of [item.enabled ? 'disable' : 'enable', 'remove']) {
        const button = document.createElement('button');
        button.textContent = action[0].toUpperCase() + action.slice(1);
        button.className = 'quiet';
        button.dataset.package = item.id;
        button.setAttribute('aria-label', button.textContent + ' ' + item.id);
        button.addEventListener('click', () => act(action, item.id));
        actions.append(button);
      }
      row.append(name, enabled, actions);
      return row;
    });
    el('packages').replaceChildren(...rows);
    el('installed').hidden = !rows.length;
    el('empty').hidden = !!rows.length;
    el('empty').textContent = state.ready ? 'No add-ons installed yet.' : 'Check a game folder to see its add-ons.';
  }
  controls();
}

async function request(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), path === '/api/import' ? 90000 : 10000);
  try {
    const response = await fetch(path, { ...options, signal: controller.signal, cache: 'no-store', credentials: 'omit',
      headers: { 'X-Hub-Token': token, ...options.headers } });
    const result = await response.json();
    if (!response.ok) throw new Error(result.message || 'The request could not be completed.');
    return result;
  } finally { clearTimeout(timer); }
}

function disconnected(message) {
  connected = false;
  controls();
  el('notice').className = 'error';
  el('notice').textContent = message;
}

async function refresh() {
  try { render(await request('/api/state')); }
  catch (_) { disconnected('Connection unavailable. Keep the Hub launcher running and use its private link. '
    + 'An operation may still be running; Hub does not automatically repeat it.'); }
}

async function submit(path, body, contentType) {
  if (!connected || pending || !state || state.busy || state.stopped) return;
  pending = true;
  controls();
  try {
    render(await request(path, { method: 'POST', body,
      headers: { 'Content-Type': contentType, 'X-Hub-Revision': String(state.revision) } }));
  } catch (error) {
    await refresh();
    el('notice').className = 'error';
    el('notice').textContent = connected ? error.message
      : 'Connection lost. The request may have started. Keep the launcher running and check again; do not repeat it blindly.';
  } finally { pending = false; controls(); }
}

function act(action, value) {
  const body = { action };
  if (value !== undefined) body.value = value;
  if (action === 'confirm') body.review = state.review.id;
  return submit('/api/action', JSON.stringify(body), 'application/json');
}

el('select').addEventListener('click', () => act('select', el('folder').value.trim().replace(/^"(.*)"$/, '$1')));
el('folder').addEventListener('keydown', event => { if (event.key === 'Enter' && !el('select').disabled) el('select').click(); });
for (const action of ['check', 'attach', 'recover', 'confirm', 'cancel', 'stop']) {
  el(action).addEventListener('click', () => act(action));
}
el('archive').addEventListener('change', controls);
el('import').addEventListener('click', async () => {
  const file = el('archive').files[0];
  if (!file) return;
  if (!file.size || file.size > state.max_archive) {
    el('notice').textContent = 'Choose a non-empty ZIP no larger than ' + (state.max_archive / 1048576) + ' MiB.';
    el('notice').className = 'error';
    return;
  }
  await submit('/api/import', file, 'application/zip');
  el('archive').value = '';
  controls();
});

async function poll() {
  if (state && state.stopped) return;
  if (!pending) await refresh();
  setTimeout(poll, state && state.busy ? 750 : 2000);
}
if (token) poll();
else disconnected('Start Hub and open the private local link printed by its launcher. This tab has no session.');
