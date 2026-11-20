let filter = 'all';
let tasks = [];
let pendingDelete = null;
const nodes = new Map();

const STATUS = {
  queued: 'Sırada', running: 'İndiriliyor', paused: 'Duraklatıldı',
  completed: 'Tamamlandı', error: 'Hata', canceled: 'İptal',
};

function openAdd(extra = '') {
  const w = window.open('/add' + extra, 'kdm_add', 'width=760,height=820');
  if (!w) location.href = '/add' + extra;
}

function taskNode(t) {
  const el = document.createElement('div');
  el.className = 'task';
  el.innerHTML = `
    <div class="top">
      <span class="badge st"></span>
      <span class="badge kind"></span>
      <div class="name"></div>
      <div class="actions">
        <button class="icon" data-a="pause" title="Duraklat">⏸</button>
        <button class="icon" data-a="resume" title="Sürdür / Yeniden dene">▶</button>
        <button class="icon" data-a="cancel" title="İptal">⏹</button>
        <button class="icon" data-a="open" title="Klasörde göster">📂</button>
        <button class="icon" data-a="log" title="Günlük">📜</button>
        <button class="icon" data-a="delete" title="Kaldır">🗑</button>
      </div>
    </div>
    <div class="bar"><div></div></div>
    <div class="meta"><span class="m-status"></span><span class="m-size"></span><span class="m-speed"></span><span class="m-eta"></span></div>
    <div class="err hidden"></div>`;
  el.addEventListener('click', e => {
    const b = e.target.closest('button[data-a]');
    if (b) action(el.dataset.id, b.dataset.a);
  });
  return el;
}

function updateNode(el, t) {
  el.dataset.id = t.id;
  el.className = `task st-${t.status}`;
  $('.badge.st', el).textContent = STATUS[t.status] || t.status;
  $('.badge.kind', el).textContent = t.kind === 'http' ? 'Dosya' : 'Medya';
  const name = t.filename || t.title || t.url;
  $('.name', el).textContent = name;
  $('.name', el).title = t.url;
  const bar = $('.bar', el);
  const indet = t.status === 'running' && t.progress == null;
  bar.classList.toggle('indet', indet);
  $('.bar > div', el).style.width = (t.status === 'completed' ? 100 : (t.progress || 0)) + '%';
  $('.m-status', el).textContent = t.status_text || '';
  $('.m-size', el).textContent = t.total ? `${fmtSize(t.downloaded)} / ${fmtSize(t.total)}${t.progress != null && t.status !== 'completed' ? ` (%${t.progress})` : ''}`
    : (t.downloaded ? fmtSize(t.downloaded) : '');
  $('.m-speed', el).textContent = t.status === 'running' && t.speed ? `${fmtSize(t.speed)}/s` : '';
  $('.m-eta', el).textContent = t.status === 'running' && t.eta ? `Kalan: ${fmtTime(t.eta)}` : '';
  const err = $('.err', el);
  err.textContent = t.error || '';
  err.classList.toggle('hidden', !t.error);
  const show = (a, v) => $(`[data-a=${a}]`, el).classList.toggle('hidden', !v);
  show('pause', t.status === 'running' || t.status === 'queued');
  show('resume', ['paused', 'error', 'canceled'].includes(t.status));
  show('cancel', ['running', 'queued', 'paused'].includes(t.status));
}

function render() {
  const list = $('#list');
  const visible = tasks.filter(t => filter === 'all' || t.status === filter).reverse();
  const ids = new Set(visible.map(t => t.id));
  for (const [id, el] of nodes) if (!ids.has(id)) { el.remove(); nodes.delete(id); }
  let prev = null;
  for (const t of visible) {
    let el = nodes.get(t.id);
    if (!el) { el = taskNode(t); nodes.set(t.id, el); }
    updateNode(el, t);
    const want = prev ? prev.nextSibling : list.firstChild;
    if (want !== el) list.insertBefore(el, want);
    prev = el;
  }
  let empty = $('.empty', list);
  if (!visible.length) {
    if (!empty) {
      empty = document.createElement('div');
      empty.className = 'empty';
      empty.innerHTML = 'Henüz indirme yok.<br><br>“+ Yeni İndirme” ile bağlantı ekleyin veya tarayıcı eklentisiyle bir sayfadaki videoyu yakalayın.';
      list.appendChild(empty);
    }
  } else if (empty) empty.remove();

  const running = tasks.filter(t => t.status === 'running');
  const speed = running.reduce((a, t) => a + (t.speed || 0), 0);
  $('#stats').textContent = `${tasks.length} görev · ${running.length} aktif` + (speed ? ` · toplam ${fmtSize(speed)}/s` : '');
  document.title = running.length ? `(${running.length}) KDM ${speed ? fmtSize(speed) + '/s' : ''}` : 'KDM İndirme Yöneticisi';
}

async function refresh() {
  try {
    tasks = await api('/api/tasks');
    render();
  } catch (e) {
    $('#stats').textContent = 'Sunucuya bağlanılamıyor… (KDM çalışıyor mu?)';
  }
}

async function action(id, a) {
  if (a === 'delete') {
    const t = tasks.find(x => x.id === id);
    pendingDelete = id;
    $('#deleteName').textContent = t ? (t.filename || t.title || t.url) : '';
    $('#deleteFiles').checked = false;
    $('#deleteModal').classList.remove('hidden');
    return;
  }
  if (a === 'log') {
    const r = await api(`/api/tasks/${id}/log`);
    $('#logBody').textContent = r.logs.join('\n') || '(boş)';
    $('#logModal').classList.remove('hidden');
    return;
  }
  try { await api(`/api/tasks/${id}/${a}`, { method: 'POST' }); } catch (e) { alert(e.message); }
  refresh();
}

async function loadSettings() {
  const info = await api('/api/info');
  $('#ffmpegWarn').classList.toggle('hidden', info.ffmpeg);
  for (const [k, v] of Object.entries(info.settings)) {
    const el = $('#s_' + k);
    if (!el) continue;
    if (el.type === 'checkbox') el.checked = !!v; else el.value = v;
  }
}

document.addEventListener('DOMContentLoaded', () => {
  bindModalClose();
  $('#btnNew').onclick = () => openAdd();
  $('#btnPauseAll').onclick = () => api('/api/bulk/pause_all', { method: 'POST' }).then(refresh);
  $('#btnResumeAll').onclick = () => api('/api/bulk/resume_all', { method: 'POST' }).then(refresh);
  $('#btnClear').onclick = () => api('/api/bulk/clear_finished', { method: 'POST' }).then(refresh);
  $('#btnFolder').onclick = () => api('/api/bulk/open_folder', { method: 'POST' });
  $('#btnSettings').onclick = async () => { await loadSettings(); $('#settingsModal').classList.remove('hidden'); };
  $('#btnSaveSettings').onclick = async () => {
    const body = {};
    $$('[id^=s_]').forEach(el => { body[el.id.slice(2)] = el.type === 'checkbox' ? el.checked : el.value; });
    try { await api('/api/settings', { body }); $('#settingsModal').classList.add('hidden'); }
    catch (e) { alert(e.message); }
  };
  $('#btnConfirmDelete').onclick = async () => {
    const files = $('#deleteFiles').checked ? '1' : '0';
    await api(`/api/tasks/${pendingDelete}?files=${files}`, { method: 'DELETE' });
    $('#deleteModal').classList.add('hidden');
    refresh();
  };
  $$('#tabs button').forEach(b => b.onclick = () => {
    $$('#tabs button').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    filter = b.dataset.f;
    render();
  });
  loadSettings().catch(() => {});
  refresh();
  setInterval(refresh, 1000);
});
