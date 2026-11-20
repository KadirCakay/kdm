let capture = null;     // eklentiden gelen veri
let current = null;     // seçili kaynak {url, type, headers}
let result = null;      // probe sonucu
let extraSubs = [];     // yakalanan/elle eklenen harici altyazılar
let settings = {};

const TYPE_LABEL = { hls: 'HLS', dash: 'DASH', file: 'Dosya', page: 'Sayfa', subtitle: 'Altyazı' };
const BBB_RE = /\/(playback|presentation)\/.*[0-9a-f]{40}-\d{13}/i;

// "Hannibal 3. Sezon 3. Bölüm izle | SiteAdı" -> "Hannibal 3. Sezon 3. Bölüm"
function cleanTitle(t) {
  if (!t) return t;
  let x = t.trim();
  const WATCH = /\s+(full\s*hd\s*|hd\s*|online\s*)?([iİ]zle|watch(\s+online)?)$/i;
  // "… | SiteAdı" veya "… _ SiteAdı" (| karakteri dosya adında _ olur)
  let m = x.match(/^(.*\S)\s+[|_]\s+([^|_]{2,40})$/);
  if (m && !/\d/.test(m[2])) x = m[1];
  // "… İzle - SiteAdı" veya "… - site.com": tire yalnızca site adı gibi görünüyorsa atılır
  m = x.match(/^(.*\S)\s+[-–—]\s+(\S{2,40})$/);
  if (m && !/\d/.test(m[2]) && (WATCH.test(m[1]) || /\.[a-z]{2,}$/i.test(m[2]))) x = m[1];
  x = x.replace(WATCH, '');
  return x.trim() || t;
}

function show(id, v) { $(id).classList.toggle('hidden', !v); }

function finish() {
  if (window.opener || capture) { window.close(); }
  setTimeout(() => { location.href = '/'; }, 150);
}

function mediaLabel(m) {
  const parts = [TYPE_LABEL[m.type] || m.type];
  const k = m.inspect && m.inspect.kind;
  if (k === 'master' || (!k && m.master)) {
    let t = 'ana liste';
    if (m.inspect && m.inspect.heights && m.inspect.heights.length) t += ` · ${m.inspect.heights[0]}p'ye kadar`;
    if (m.inspect && m.inspect.audios > 1) t += ` · ${m.inspect.audios} ses`;
    if (m.inspect && m.inspect.subs) t += ` · ${m.inspect.subs} altyazı`;
    parts.push(t);
  } else if (k === 'audio') parts.push('yalnızca ses');
  else if (k === 'media') parts.push('alt liste');
  if (m.size && m.type === 'file') parts.push(fmtSize(m.size));
  return `[${parts.join(' · ')}]  ${shortUrl(m.url, 80)}`;
}

async function inspectAll(items) {
  const hls = items.filter(m => m.type === 'hls');
  await Promise.all(hls.map(async m => {
    try {
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), 8000);
      const r = await fetch('/api/inspect', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: ctl.signal,
        body: JSON.stringify({ url: m.url, headers: m.headers || {}, cookies: capture.cookies || [] }),
      });
      clearTimeout(timer);
      m.inspect = await r.json();
    } catch (_) {}
  }));
}

function score(m) {
  const k = m.inspect && m.inspect.kind;
  if (m.type === 'page' && BBB_RE.test(m.url)) return 0;
  if (m.type === 'hls' && (k === 'master' || (!k && m.master))) return 1;
  if (m.type === 'dash') return 2;
  if (m.type === 'hls' && k !== 'audio' && k !== 'subtitle') return 3;
  if (m.type === 'file') return 4;
  if (m.type === 'page') return 5;
  return 6;
}

async function setupCapture() {
  show('#manualSrc', false);
  show('#captureSrc', true);
  $('#pageTitle').textContent = (capture.title || '') + (capture.page_url ? ' — ' + shortUrl(capture.page_url, 60) : '');
  const sel = $('#source');
  sel.innerHTML = '<option>Akışlar inceleniyor…</option>';
  let options = [...(capture.media || [])];
  if (capture.page_url) options.push({ url: capture.page_url, type: 'page', headers: {} });
  await inspectAll(options);
  // altyazı listelerini medya listesinden çıkar
  options = options.filter(m => !(m.inspect && m.inspect.kind === 'subtitle'));
  const isBbb = capture.page_url && BBB_RE.test(capture.page_url);
  sel.innerHTML = '';
  options.forEach((m, i) => {
    const o = document.createElement('option');
    o.value = i;
    o.textContent = m.type === 'page'
      ? (isBbb ? `[BigBlueButton kaydı – slaytlar + ekran + ses]  ${shortUrl(m.url, 60)}` : `[Sayfa adresi – site desteği ile]  ${shortUrl(m.url, 70)}`)
      : mediaLabel(m);
    sel.appendChild(o);
  });
  let idx = capture.explicit ? options.findIndex(m => m.url === capture.selected) : -1;
  if (idx < 0) {
    // en iyi kaynağı seç: BBB > HLS ana liste > DASH > diğer HLS > dosya > sayfa
    const best = options.map((m, i) => [score(m), i]).sort((a, b) => a[0] - b[0] || a[1] - b[1])[0];
    idx = best ? best[1] : 0;
  }
  sel.value = idx;
  sel.onchange = () => { current = options[+sel.value]; probe(); };
  extraSubs = (capture.subtitles || []).map(s => ({ ...s, checked: true }));
  current = options[idx];
  if (current) probe();
}

async function probe() {
  show('#error', false);
  show('#resultCard', false);
  show('#loading', true);
  try {
    result = await api('/api/probe', {
      body: {
        url: current.url, type: current.type, headers: current.headers || {},
        cookies: capture ? capture.cookies : [],
      },
    });
    renderResult();
  } catch (e) {
    $('#error').textContent = e.message;
    show('#error', true);
  } finally {
    show('#loading', false);
  }
}

function renderResult() {
  const r = result;
  const isPl = r.kind === 'playlist';
  const isHttp = r.kind === 'http';
  let name = r.title || '';
  // Akışlarda (m3u8/mpd) dosya adı genelde anlamsızdır: sayfa başlığını kullan
  const isStream = current && (current.type === 'hls' || current.type === 'dash');
  if (!isHttp && !isPl && r.kind !== 'bbb' && capture && capture.title &&
      (isStream || /^(index|master|playlist|manifest|video|chunklist)/i.test(name))) {
    name = cleanTitle(capture.title);
  }
  $('#name').value = name;
  $('#nameLabel').textContent = isPl ? 'Liste adı' : (isHttp ? 'Dosya adı' : 'Dosya adı (uzantısız)');
  const meta = [];
  if (r.extractor) meta.push(r.extractor);
  if (r.duration) meta.push(fmtTime(r.duration));
  if (r.size) meta.push(fmtSize(r.size));
  if (r.note) meta.push(r.note);
  if (isHttp) meta.push(r.resumable ? 'Çok bağlantılı + devam ettirilebilir' : 'Tek bağlantı (sunucu parçalı indirmeyi desteklemiyor)');
  $('#metaInfo').textContent = meta.join(' · ');
  const th = $('#thumb');
  if (r.thumbnail) { th.src = r.thumbnail; show('#thumb', true); } else show('#thumb', false);

  // kalite
  show('#qualityBox', !isHttp && r.qualities && r.qualities.length);
  const q = $('#quality');
  q.innerHTML = '';
  (r.qualities || []).forEach((x, i) => {
    const o = document.createElement('option');
    o.value = i; o.textContent = x.label; q.appendChild(o);
  });

  // ses izleri (DUAL yayınlar vb.)
  const at = r.audio_tracks || [];
  show('#audioBox', at.length > 1);
  $('#audioSel').innerHTML = '<option value="">Varsayılan</option>' +
    at.map(a => `<option value="${esc(a.id)}">${esc(a.label)}</option>`).join('') +
    (at.length > 1 ? '<option value="all">Hepsi (çoklu ses, MKV)</option>' : '');
  const trTrack = at.find(a => /^(tr|tur)/i.test(a.lang || '') || /türk|turk/i.test(a.label));
  if (trTrack) $('#audioSel').value = trTrack.id;

  // site tarafından bildirilen harici altyazılar (ör. BBB altyazıları)
  for (const s of r.extra_subtitles || []) {
    if (!extraSubs.find(x => x.url === s.url)) extraSubs.push({ url: s.url, lang: s.lang, checked: true });
  }

  // liste / dizi
  show('#playlistBox', isPl);
  if (isPl) {
    $('#folderName').value = r.title || '';
    $('#epCount').textContent = `(${r.entries.length})`;
    $('#entries').innerHTML = r.entries.map((e, i) => `
      <label class="item check" style="margin:0"><input type="checkbox" data-i="${i}" checked>
        <span class="grow">${esc(e.title)}</span>
        <span class="muted small">${e.duration ? fmtTime(e.duration) : ''}</span></label>`).join('');
  }

  // altyazılar
  show('#subsBox', !isPl);
  $('#embed').checked = !!settings.embed_subtitles;
  renderSubs();
  show('#resultCard', true);
}

function renderSubs() {
  const r = result;
  const items = [];
  (r.subtitles || []).forEach((s, i) => items.push(`
    <label class="item check" style="margin:0"><input type="checkbox" data-site="${i}">
      <span class="grow">${esc(s.name)} <span class="muted small">(${esc(s.lang)})</span></span>
      <span class="badge">site</span></label>`));
  extraSubs.forEach((s, i) => items.push(`
    <div class="item"><input type="checkbox" data-extra="${i}" ${s.checked ? 'checked' : ''}>
      <span class="grow small" title="${esc(s.url)}">${esc(shortUrl(s.url, 60))}</span>
      <input type="text" data-lang="${i}" value="${esc(s.lang || '')}" placeholder="dil">
      <span class="badge">yakalandı</span></div>`));
  $('#subs').innerHTML = items.join('');
  show('#subs', items.length > 0);
  show('#noSubs', items.length === 0);
  $$('#subs [data-extra]').forEach(cb => cb.onchange = () => { extraSubs[+cb.dataset.extra].checked = cb.checked; });
  $$('#subs [data-lang]').forEach(inp => inp.oninput = () => { extraSubs[+inp.dataset.lang].lang = inp.value.trim(); });
}

async function startDownload() {
  const r = result;
  const quality = (r.qualities || [])[+$('#quality').value] || {};
  const body = {
    url: current.url,
    page_url: capture ? capture.page_url : '',
    kind: r.kind === 'playlist' ? 'media' : r.kind,
    video_sel: quality.video || '',
    audio_sel: $('#audioBox').classList.contains('hidden') ? '' : $('#audioSel').value,
    title: $('#name').value.trim(),
    format: quality.format,
    audio_only: !!quality.audio_only,
    headers: current.headers || {},
    cookies: capture ? capture.cookies : [],
    out_dir: $('#outDir').value.trim(),
    embed_subs: $('#embed').checked,
  };
  if (r.kind === 'playlist') {
    body.entries = $$('#entries input:checked').map(cb => r.entries[+cb.dataset.i]);
    if (!body.entries.length) return alert('En az bir bölüm seçin.');
    body.folder_name = $('#folderName').value.trim();
    const langs = $('#plSubs').value.split(',').map(s => s.trim()).filter(Boolean);
    body.sub_langs = langs;
    body.title = '';
  } else {
    const site = $$('#subs [data-site]:checked').map(cb => r.subtitles[+cb.dataset.site]);
    body.sub_langs = site.filter(s => !s.auto).map(s => s.lang);
    body.auto_sub_langs = site.filter(s => s.auto).map(s => s.lang);
    body.extra_subs = extraSubs.filter(s => s.checked).map(s => ({ url: s.url, lang: s.lang || 'und' }));
  }
  $('#btnDownload').disabled = true;
  try {
    const res = await api('/api/tasks', { body });
    if (res.duplicate) alert('Bu video zaten indirme listesinde.');
    finish();
  } catch (e) {
    alert(e.message);
    $('#btnDownload').disabled = false;
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  try {
    const info = await api('/api/info');
    settings = info.settings;
    $('#outDir').value = settings.download_dir;
  } catch (_) {}

  $('#btnProbe').onclick = () => {
    const u = $('#url').value.trim();
    if (!u) return;
    current = { url: u, type: '', headers: {} };
    probe();
  };
  $('#url').addEventListener('keydown', e => { if (e.key === 'Enter') $('#btnProbe').click(); });
  $('#toggleBatch').onchange = e => show('#batchBox', e.target.checked);
  $('#btnBatch').onclick = async () => {
    const langs = $('#batchSubs').value.split(',').map(s => s.trim()).filter(Boolean);
    try {
      const r = await api('/api/batch', { body: { urls: $('#batchUrls').value, sub_langs: langs, out_dir: $('#outDir').value.trim() } });
      if (!r.ids.length) return alert('Geçerli bağlantı bulunamadı.');
      finish();
    } catch (e) { alert(e.message); }
  };
  $('#btnAddSub').onclick = () => {
    const u = $('#subUrl').value.trim();
    if (!u.startsWith('http')) return;
    extraSubs.push({ url: u, lang: $('#subLang').value.trim() || 'und', checked: true });
    $('#subUrl').value = ''; $('#subLang').value = '';
    renderSubs();
  };
  $('#selAll').onclick = () => $$('#entries input').forEach(c => c.checked = true);
  $('#selNone').onclick = () => $$('#entries input').forEach(c => c.checked = false);
  $('#btnCancel').onclick = finish;
  $('#btnDownload').onclick = startDownload;

  const params = new URLSearchParams(location.search);
  const cid = params.get('capture');
  if (cid) {
    try {
      capture = await api('/api/capture/' + cid);
      await setupCapture();
    } catch (e) {
      $('#error').textContent = 'Yakalama verisi bulunamadı (süresi dolmuş olabilir). Eklentiden tekrar gönderin.';
      show('#error', true);
    }
  } else if (params.get('url')) {
    $('#url').value = params.get('url');
    $('#btnProbe').click();
  } else {
    $('#url').focus();
  }
});
