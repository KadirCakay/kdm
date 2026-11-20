// Videoların üzerinde IDM tarzı "İndir" düğmesi gösterir.
(() => {
  if (window.__kdmOverlay) return;
  window.__kdmOverlay = true;

  let enabled = true;
  let host = null, btn = null, current = null, hideTimer = null;

  function build() {
    host = document.createElement('div');
    host.style.cssText = 'position:fixed;z-index:2147483647;top:0;left:0;display:none;';
    const root = host.attachShadow({ mode: 'closed' });
    root.innerHTML = `
      <style>
        button { all: initial; font: 600 13px system-ui, sans-serif; color: #fff; background: #2563eb;
          padding: 6px 12px; border-radius: 8px; cursor: pointer; box-shadow: 0 2px 8px rgba(0,0,0,.35);
          display: flex; gap: 6px; align-items: center; opacity: .92; }
        button:hover { opacity: 1; background: #1d4ed8; }
      </style>
      <button title="KDM ile indir">⬇ Bu videoyu indir</button>`;
    btn = root.querySelector('button');
    btn.addEventListener('click', e => {
      e.preventDefault(); e.stopPropagation();
      const src = current && (current.currentSrc || current.src);
      btn.textContent = '⏳ Gönderiliyor…';
      chrome.runtime.sendMessage({ type: 'grab', src }, () => {
        btn.textContent = '⬇ Bu videoyu indir';
        void chrome.runtime.lastError;
      });
    }, true);
    host.addEventListener('mouseenter', () => clearTimeout(hideTimer));
    (document.documentElement || document.body).appendChild(host);
  }

  function place(v) {
    const r = v.getBoundingClientRect();
    if (r.width < 200 || r.height < 110) return hide();
    if (!host) build();
    current = v;
    host.style.display = 'block';
    host.style.top = Math.max(4, r.top + 10) + 'px';
    host.style.left = Math.max(4, r.right - 190) + 'px';
    clearTimeout(hideTimer);
    hideTimer = setTimeout(hide, 2500);
  }

  function hide() { if (host) host.style.display = 'none'; current = null; }

  function videoAt(x, y) {
    for (const v of document.querySelectorAll('video')) {
      const r = v.getBoundingClientRect();
      if (x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) return v;
    }
    return null;
  }

  let last = 0;
  document.addEventListener('mousemove', e => {
    if (!enabled) return;
    const now = Date.now();
    if (now - last < 150) return;
    last = now;
    const v = videoAt(e.clientX, e.clientY);
    if (v) place(v);
  }, { passive: true, capture: true });

  try {
    chrome.runtime.sendMessage({ type: 'hasMedia' }, res => {
      void chrome.runtime.lastError;
      if (res && res.overlay === false) enabled = false;
    });
    chrome.storage.onChanged.addListener((c, area) => {
      if (area === 'local' && c.overlay) enabled = c.overlay.newValue !== false;
    });
  } catch (_) {}
})();
