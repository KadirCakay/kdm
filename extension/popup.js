const $ = s => document.querySelector(s);
const DEFAULTS = { port: 9614, catchDownloads: false, overlay: true, minCatchMB: 1 };
const LABEL = { hls: 'HLS', dash: 'DASH', file: 'DOSYA' };
let tabId = null;

function fmtSize(n) {
  if (!n) return '';
  const u = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  while (n >= 1024 && i < 3) { n /= 1024; i++; }
  return `${n.toFixed(i > 1 ? 1 : 0)} ${u[i]}`;
}

function short(u) {
  try { const x = new URL(u); return x.host + x.pathname; } catch (_) { return u; }
}

function el(tag, attrs = {}, text = '') {
  const e = document.createElement(tag);
  Object.assign(e, attrs);
  if (text) e.textContent = text;
  return e;
}

async function send(msg) {
  return new Promise(res => chrome.runtime.sendMessage(msg, r => { void chrome.runtime.lastError; res(r); }));
}

async function capture(url) {
  const r = await send({ type: 'capture', tabId, url });
  if (r && r.ok) window.close();
  else $('#warn').style.display = 'block';
}

async function load() {
  const res = await send({ type: 'list', tabId });
  if (!res) return;
  $('#dot').className = 'dot ' + (res.online ? 'on' : 'off');
  $('#status').textContent = res.online ? 'bağlı' : 'çalışmıyor';
  $('#warn').style.display = res.online ? 'none' : 'block';

  const media = $('#media');
  media.innerHTML = '';
  if (!res.media.length) media.appendChild(el('div', { className: 'empty' }, 'Henüz medya yakalanmadı.'));
  for (const m of res.media) {
    const row = el('div', { className: 'item' });
    row.appendChild(el('span', { className: 'badge' }, (LABEL[m.type] || m.type) + (m.master ? ' ★' : '')));
    row.appendChild(el('span', { className: 'u', title: m.url }, short(m.url)));
    if (m.size && m.type === 'file') row.appendChild(el('span', { className: 'muted' }, fmtSize(m.size)));
    const b = el('button', {}, 'İndir');
    b.onclick = () => capture(m.url);
    row.appendChild(b);
    media.appendChild(row);
  }
  const subs = $('#subs');
  subs.innerHTML = '';
  if (!res.subs.length) subs.appendChild(el('div', { className: 'empty' }, 'Altyazı yakalanmadı.'));
  for (const s of res.subs) {
    const row = el('div', { className: 'item' });
    row.appendChild(el('span', { className: 'badge sub' }, s.lang || 'und'));
    row.appendChild(el('span', { className: 'u', title: s.url }, short(s.url)));
    subs.appendChild(row);
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  tabId = tab ? tab.id : -1;
  $('#sendPage').onclick = () => capture(null);
  $('#openApp').onclick = () => send({ type: 'openApp' });
  $('#clear').onclick = async () => { await send({ type: 'clear', tabId }); load(); };

  const s = { ...DEFAULTS, ...(await chrome.storage.local.get(Object.keys(DEFAULTS))) };
  $('#port').value = s.port;
  $('#overlay').checked = s.overlay;
  $('#catchDownloads').checked = s.catchDownloads;
  $('#minCatchMB').value = s.minCatchMB;
  $('#port').onchange = e => chrome.storage.local.set({ port: parseInt(e.target.value, 10) || 9614 });
  $('#overlay').onchange = e => chrome.storage.local.set({ overlay: e.target.checked });
  $('#catchDownloads').onchange = e => chrome.storage.local.set({ catchDownloads: e.target.checked });
  $('#minCatchMB').onchange = e => chrome.storage.local.set({ minCatchMB: parseFloat(e.target.value) || 0 });

  load();
  setInterval(load, 2000);
});
