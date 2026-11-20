// KDM Yakalayıcı - arka plan betiği (Chrome/Edge/Brave/Opera: service worker, Firefox: event page)

const DEFAULTS = { port: 9614, catchDownloads: false, overlay: true, minCatchMB: 1 };

const MANIFEST_RE = /\.(m3u8|mpd)(\?|#|$)/i;
const FILE_RE = /\.(mp4|m4v|webm|mkv|mov|flv|avi|wmv|mp3|m4a|aac|ogg|oga|opus|wav|flac)(\?|#|$)/i;
const SUB_RE = /\.(vtt|webvtt|srt|ass|ssa|ttml|dfxp)(\?|#|$)/i;
const SEG_RE = /\.(ts|m4s|m4f|cmfv|cmfa|key)(\?|#|$)/i;
const SEG_HINT = /(^|[\/_\-.])(seg|segment|frag|fragment|chunk|part)[-_]?\d+/i;
const SKIP_HOSTS = /(^|\.)(googlevideo\.com|doubleclick\.net|googlesyndication\.com|imasdk\.googleapis\.com)$/i;
const DL_EXT = /\.(mp4|m4v|mkv|webm|mov|avi|flv|wmv|mp3|m4a|flac|wav|zip|rar|7z|tar|gz|iso|exe|msi|dmg|pkg|deb|rpm|apk|pdf|epub)(\?|#|$)/i;
const KEEP_HEADERS = /^(referer|origin|user-agent|authorization|x-[\w-]+|accept|accept-language)$/i;
const MAX_ITEMS = 60;

const LANG3 = { tur: 'tr', eng: 'en', ger: 'de', deu: 'de', fre: 'fr', fra: 'fr', spa: 'es', ita: 'it', por: 'pt',
  rus: 'ru', ara: 'ar', jpn: 'ja', kor: 'ko', chi: 'zh', zho: 'zh', dut: 'nl', nld: 'nl', pol: 'pl' };
const LANG_RE = /(?:^|[\/_\-.=])(tr|en|de|fr|es|it|pt|ru|ar|ja|ko|zh|nl|pl|sv|fa|az|tur|eng|ger|deu|fre|fra|spa|ita|por|rus|ara|jpn|kor|chi|zho|dut|nld|pol|turkish|english|german|french|spanish)(?=$|[\/_\-.?&])/i;
const LANG_WORD = { turkish: 'tr', english: 'en', german: 'de', french: 'fr', spanish: 'es' };

const extraHeaderOpt = chrome.webRequest.OnSendHeadersOptions &&
  chrome.webRequest.OnSendHeadersOptions.EXTRA_HEADERS ? ['extraHeaders'] : [];

let tabs = {};                 // tabId -> { media: {url: item}, subs: {url: item} }
const reqHeaders = new Map();  // requestId -> headers
let saveTimer = null;
let settings = { ...DEFAULTS };

const ready = (async () => {
  try {
    const s = await chrome.storage.session.get('tabs');
    tabs = s.tabs || {};
  } catch (_) {}
  try {
    settings = { ...DEFAULTS, ...(await chrome.storage.local.get(Object.keys(DEFAULTS))) };
  } catch (_) {}
})();

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== 'local') return;
  for (const [k, v] of Object.entries(changes)) settings[k] = v.newValue;
});

function persist() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => chrome.storage.session.set({ tabs }).catch(() => {}), 400);
}

const apiBase = () => `http://127.0.0.1:${settings.port || DEFAULTS.port}`;

function tabState(tabId) {
  if (!tabs[tabId]) tabs[tabId] = { media: {}, subs: {} };
  return tabs[tabId];
}

function header(list, name) {
  const h = (list || []).find(x => x.name.toLowerCase() === name);
  return h ? h.value : '';
}

function guessLang(url) {
  try {
    const u = new URL(url);
    const p = u.searchParams;
    const q = p.get('lang') || p.get('language') || p.get('lng') || p.get('locale');
    if (q) return q.slice(0, 5).toLowerCase();
    const m = decodeURIComponent(u.pathname).match(LANG_RE);
    if (m) {
      const l = m[1].toLowerCase();
      return LANG3[l] || LANG_WORD[l] || l;
    }
  } catch (_) {}
  return 'und';
}

function classify(url, ct) {
  ct = (ct || '').toLowerCase().split(';')[0].trim();
  if (ct.includes('mpegurl') || /\.m3u8(\?|#|$)/i.test(url)) return 'hls';
  if (ct.includes('dash+xml') || /\.mpd(\?|#|$)/i.test(url)) return 'dash';
  if (ct === 'text/vtt' || ct.includes('subrip') || ct.includes('ttml') || SUB_RE.test(url)) {
    return ct.startsWith('text/html') ? null : 'subtitle';
  }
  if (ct === 'video/mp2t' || SEG_RE.test(url) || ct.startsWith('text/') || ct.startsWith('image/')) return null;
  if (ct.startsWith('video/') || ct.startsWith('audio/') || FILE_RE.test(url)) return 'file';
  return null;
}

function cleanHeaders(list) {
  const out = {};
  for (const h of list || []) if (KEEP_HEADERS.test(h.name) && h.value) out[h.name] = h.value;
  return out;
}

function updateBadge(tabId) {
  const t = tabs[tabId];
  const n = t ? Object.keys(t.media).length : 0;
  chrome.action.setBadgeText({ tabId, text: n ? String(n) : '' }).catch(() => {});
  chrome.action.setBadgeBackgroundColor({ tabId, color: '#2563eb' }).catch(() => {});
}

async function inspectHls(tabId, url) {
  try {
    const r = await fetch(url, { credentials: 'include' });
    const txt = await r.text();
    const item = tabs[tabId] && tabs[tabId].media[url];
    if (!item) return;
    item.master = txt.includes('#EXT-X-STREAM-INF');
    item.hasSubs = /TYPE=SUBTITLES/i.test(txt);
    if (!item.master && /\.(vtt|webvtt)(\?|$)/im.test(txt) && !/#EXT-X-STREAM-INF/.test(txt)) {
      // altyazı oynatma listesi
      delete tabs[tabId].media[url];
      tabs[tabId].subs[url] = { url, lang: guessLang(url), headers: item.headers, time: item.time };
    }
    persist();
    updateBadge(tabId);
  } catch (_) {}
}

function trim(map) {
  const keys = Object.keys(map);
  if (keys.length <= MAX_ITEMS) return;
  keys.sort((a, b) => map[a].time - map[b].time).slice(0, keys.length - MAX_ITEMS).forEach(k => delete map[k]);
}

chrome.webRequest.onSendHeaders.addListener(d => {
  if (d.tabId < 0) return;
  reqHeaders.set(d.requestId, d.requestHeaders);
  if (reqHeaders.size > 400) reqHeaders.delete(reqHeaders.keys().next().value);
}, { urls: ['<all_urls>'] }, ['requestHeaders', ...extraHeaderOpt]);

chrome.webRequest.onHeadersReceived.addListener(d => {
  const sent = reqHeaders.get(d.requestId);
  reqHeaders.delete(d.requestId);
  if (d.tabId < 0 || !/^https?:/.test(d.url)) return;
  if (d.statusCode < 200 || d.statusCode >= 300) return;
  let host = '';
  try { host = new URL(d.url).hostname; } catch (_) { return; }
  if (SKIP_HOSTS.test(host)) return;
  const ct = header(d.responseHeaders, 'content-type');
  const type = classify(d.url, ct);
  if (!type) return;

  let size = 0;
  const cr = header(d.responseHeaders, 'content-range');
  if (cr && cr.includes('/')) size = parseInt(cr.split('/')[1], 10) || 0;
  if (!size) size = parseInt(header(d.responseHeaders, 'content-length'), 10) || 0;
  if (type === 'file') {
    if (size && size < 400 * 1024) return;
    try { if (SEG_HINT.test(new URL(d.url).pathname)) return; } catch (_) {}
  }

  ready.then(() => {
    const st = tabState(d.tabId);
    const headers = cleanHeaders(sent);
    if (!headers.Referer && !headers.referer && d.initiator) headers.Referer = d.initiator + '/';
    const now = Date.now();
    if (type === 'subtitle') {
      if (!st.subs[d.url]) st.subs[d.url] = { url: d.url, lang: guessLang(d.url), headers, time: now };
      trim(st.subs);
    } else {
      const prev = st.media[d.url];
      st.media[d.url] = { url: d.url, type, size: Math.max(size, prev ? prev.size : 0), ct,
        headers, time: prev ? prev.time : now, master: prev ? prev.master : undefined };
      trim(st.media);
      if (type === 'hls' && !prev) inspectHls(d.tabId, d.url);
    }
    persist();
    updateBadge(d.tabId);
  });
}, { urls: ['<all_urls>'] }, ['responseHeaders']);

chrome.webRequest.onErrorOccurred.addListener(d => reqHeaders.delete(d.requestId), { urls: ['<all_urls>'] });

chrome.tabs.onRemoved.addListener(tabId => ready.then(() => { delete tabs[tabId]; persist(); }));
chrome.tabs.onUpdated.addListener((tabId, info) => {
  // Tam sayfa yenilemesi/gezinmesi: eski listeyi temizle (SPA içi geçişlerde liste korunur)
  if (info.status === 'loading' && info.url) {
    ready.then(() => { delete tabs[tabId]; persist(); updateBadge(tabId); });
  }
});

// ---------------------------------------------------------------- yardımcılar

function rank(a, b) {
  const pri = m => (m.type === 'hls' && m.master) ? 0 : m.type === 'dash' ? 1 : m.type === 'hls' ? 2 : 3;
  const ba = Math.floor(a.time / 15000), bb = Math.floor(b.time / 15000);
  if (ba !== bb) return bb - ba;              // daha yeni olan önce
  if (pri(a) !== pri(b)) return pri(a) - pri(b);
  return (b.size || 0) - (a.size || 0);
}

async function collectCookies(urls) {
  const out = [];
  const seen = new Set();
  const origins = new Set();
  for (const u of urls) {
    try { const x = new URL(u); if (/^https?:$/.test(x.protocol)) origins.add(x.origin + '/'); } catch (_) {}
  }
  for (const origin of origins) {
    let list = [];
    try { list = await chrome.cookies.getAll({ url: origin }); } catch (_) {}
    for (const c of list) {
      const key = `${c.domain}|${c.path}|${c.name}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ domain: c.domain, path: c.path, name: c.name, value: c.value, secure: c.secure,
        httpOnly: c.httpOnly, hostOnly: c.hostOnly, expirationDate: c.expirationDate });
    }
  }
  return out;
}

async function ping() {
  try {
    const r = await fetch(apiBase() + '/api/ping', { cache: 'no-store' });
    return r.ok;
  } catch (_) { return false; }
}

function notify(message) {
  chrome.notifications.create({ type: 'basic', iconUrl: 'icons/48.png', title: 'KDM', message }).catch?.(() => {});
}

function guessType(url) {
  if (MANIFEST_RE.test(url)) return /\.mpd/i.test(url) ? 'dash' : 'hls';
  if (FILE_RE.test(url) || DL_EXT.test(url)) return 'file';
  return 'page';
}

async function sendCapture(tabId, selectedUrl, opts = {}) {
  await ready;
  let tab = null;
  try { tab = tabId >= 0 ? await chrome.tabs.get(tabId) : null; } catch (_) {}
  const st = tabs[tabId] || { media: {}, subs: {} };
  let media = Object.values(st.media).sort(rank);
  if (opts.only) media = [];
  if (selectedUrl && selectedUrl !== (tab && tab.url) && !media.find(m => m.url === selectedUrl)) {
    media.unshift({ url: selectedUrl, type: guessType(selectedUrl), size: opts.size || 0,
      headers: (opts.pageUrl || (tab && tab.url)) ? { Referer: opts.pageUrl || tab.url } : {}, time: Date.now() });
  }
  const subs = opts.only ? [] : Object.values(st.subs).sort((a, b) => a.time - b.time);
  const pageUrl = tab ? tab.url : (opts.pageUrl || '');
  const cookies = await collectCookies([pageUrl, ...media.map(m => m.url), ...subs.map(s => s.url)]);
  const payload = {
    page_url: pageUrl, title: tab ? tab.title : '', explicit: !!selectedUrl,
    selected: selectedUrl || (media[0] && media[0].url) || pageUrl,
    media, subtitles: subs.map(s => ({ url: s.url, lang: s.lang, headers: s.headers })), cookies,
  };
  let res;
  try {
    const r = await fetch(apiBase() + '/api/capture', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    res = await r.json();
  } catch (e) {
    notify('KDM uygulamasına ulaşılamadı. Uygulamanın çalıştığından emin olun (python run.py).');
    return { ok: false, error: String(e) };
  }
  await chrome.windows.create({ url: res.url, type: 'popup', width: 780, height: 860 });
  return { ok: true };
}

// ---------------------------------------------------------------- mesajlar

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    await ready;
    if (msg.type === 'list') {
      const st = tabs[msg.tabId] || { media: {}, subs: {} };
      sendResponse({ media: Object.values(st.media).sort(rank), subs: Object.values(st.subs), online: await ping() });
    } else if (msg.type === 'capture') {
      sendResponse(await sendCapture(msg.tabId, msg.url));
    } else if (msg.type === 'clear') {
      delete tabs[msg.tabId]; persist(); updateBadge(msg.tabId);
      sendResponse({ ok: true });
    } else if (msg.type === 'grab' && sender.tab) {
      const src = msg.src && /^https?:/.test(msg.src) ? msg.src : null;
      sendResponse(await sendCapture(sender.tab.id, src));
    } else if (msg.type === 'hasMedia' && sender.tab) {
      const st = tabs[sender.tab.id];
      sendResponse({ count: st ? Object.keys(st.media).length : 0, overlay: settings.overlay !== false });
    } else if (msg.type === 'openApp') {
      chrome.tabs.create({ url: apiBase() + '/' });
      sendResponse({ ok: true });
    }
  })();
  return true;
});

// ---------------------------------------------------------------- sağ tık menüsü

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: 'kdm-link', title: 'KDM ile indir', contexts: ['link', 'video', 'audio'] });
    chrome.contextMenus.create({ id: 'kdm-page', title: 'Bu sayfadaki videoyu KDM ile indir', contexts: ['page', 'frame'] });
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  const src = info.srcUrl || info.linkUrl;
  const url = src && /^https?:/.test(src) ? src : null;
  sendCapture(tab ? tab.id : -1, info.menuItemId === 'kdm-page' ? null : url, { pageUrl: info.pageUrl });
});

// ---------------------------------------------------------------- tarayıcı indirmelerini yakala

chrome.downloads.onCreated.addListener(async item => {
  await ready;
  if (!settings.catchDownloads) return;
  const url = item.finalUrl || item.url;
  if (!/^https?:/.test(url) || url.startsWith(apiBase())) return;
  const big = item.fileSize > (settings.minCatchMB || 1) * 1024 * 1024 || item.totalBytes > (settings.minCatchMB || 1) * 1024 * 1024;
  const known = DL_EXT.test(url) || DL_EXT.test(item.filename || '');
  if (!big && !known) return;
  if (!(await ping())) return;  // uygulama kapalıysa tarayıcı indirsin
  try { await chrome.downloads.cancel(item.id); await chrome.downloads.erase({ id: item.id }); } catch (_) {}
  let tabId = -1;
  try { const [t] = await chrome.tabs.query({ active: true, lastFocusedWindow: true }); if (t) tabId = t.id; } catch (_) {}
  sendCapture(tabId, url, { only: true, size: item.totalBytes || item.fileSize || 0, pageUrl: item.referrer });
});
