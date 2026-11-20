"""yt-dlp tabanlı medya motoru: HLS (m3u8), DASH (mpd), web sayfaları, playlist/dizi.

yt-dlp binlerce siteyi tanır; tanımadığı sayfalarda bile "generic" çıkarıcı ile
sayfa içindeki video/akış bağlantılarını bulmaya çalışır.
"""
import os
import re
import threading
import time
from pathlib import Path

import yt_dlp
from yt_dlp.downloader.common import FileDownloader
from yt_dlp.downloader.fragment import FragmentFD
from yt_dlp.utils import DownloadCancelled

from ..utils import sanitize_filename

ANSI = re.compile(r"\x1b\[[0-9;]*m")

# Windows: antivirüs/arama dizini dosyayı kısa süre kilitleyebilir -> yeniden adlandırmayı tekrar dene
_orig_try_rename = getattr(FileDownloader, "try_rename", None)


def _patient_try_rename(self, old, new):
    for i in range(40):
        try:
            return _orig_try_rename(self, old, new)
        except PermissionError:
            if i == 39:
                raise
            time.sleep(0.5)


if _orig_try_rename:   # yt-dlp ileride bu fonksiyonu değiştirirse yama sessizce devre dışı kalır
    FileDownloader.try_rename = _patient_try_rename

# yt-dlp hatası: paralel parça indirmede bir parça alınamayıp atlanırsa, kopyalanan bağlam
# önceki (zaten birleştirilip silinmiş) parçanın adını taşır ve "No such file ...FragN" ile çöker.
# Her parça indirmesinden önce bu alanı temizleyerek atlamanın doğru çalışmasını sağlıyoruz.
_orig_download_fragment = getattr(FragmentFD, "_download_fragment", None)


def _clean_download_fragment(self, ctx, *args, **kwargs):
    if isinstance(ctx, dict):
        ctx.pop("fragment_filename_sanitized", None)
    return _orig_download_fragment(self, ctx, *args, **kwargs)


if _orig_download_fragment:
    FragmentFD._download_fragment = _clean_download_fragment

STD_HEIGHTS = [2160, 1440, 1080, 720, 480, 360]
MEDIA_EXTS = ("mp4", "mkv", "webm", "m4a", "mp3", "mov", "ts", "flv")
MAX_HLS_CONNECTIONS = 5   # akış sunucuları çok fazla paralel bağlantıda parça reddedebiliyor
SKIP_RE = re.compile(r"Skipping fragment (\d+)")


class _Logger:
    def __init__(self, log, on_skip=None):
        self.log = log
        self.on_skip = on_skip
        self._last_retry = 0.0

    def debug(self, msg):
        msg = ANSI.sub("", str(msg))
        m = SKIP_RE.search(msg)
        if m:
            self.log(f"Uyarı: parça {m.group(1)} sunucudan alınamadı, atlandı")
            if self.on_skip:
                self.on_skip()
        elif "Got error" in msg or "Retrying fragment" in msg:
            # yeniden denemeleri günlüğe yaz (çok sık olmasın)
            if time.monotonic() - self._last_retry > 5:
                self._last_retry = time.monotonic()
                self.log(msg.replace("[download] ", ""))

    def info(self, msg):
        self.debug(msg)

    def warning(self, msg):
        msg = ANSI.sub("", str(msg))
        if "Live HLS streams are not supported" in msg:
            return
        self.log("Uyarı: " + msg)

    def error(self, msg):
        self.log(ANSI.sub("", str(msg)))


def base_opts(headers=None, cookiefile=None, cookies_from_browser="", log=None, on_skip=None) -> dict:
    o = {
        "quiet": True,
        "no_warnings": False,
        "noprogress": True,
        "socket_timeout": 30,
        "retries": 15,
        "fragment_retries": 15,
        "retry_sleep_functions": {"fragment": lambda n: min(1.5 ** n, 10), "http": lambda n: min(2 ** n, 30)},
        "extractor_retries": 3,
        "http_headers": dict(headers or {}),
        "color": {"stdout": "no_color", "stderr": "no_color"},
        "logger": _Logger(log or (lambda m: None), on_skip),
    }
    if cookiefile:
        o["cookiefile"] = str(cookiefile)
    elif cookies_from_browser:
        o["cookiesfrombrowser"] = (cookies_from_browser,)
    return o


def friendly_error(e: Exception) -> str:
    msg = ANSI.sub("", str(e))
    low = msg.lower()
    if "drm" in low:
        return ("Bu içerik DRM ile korunuyor (Widevine/PlayReady/FairPlay). "
                "DRM korumalı içerikler desteklenmez.")
    if "unsupported url" in low:
        return ("Bu sayfada indirilebilir bir video bulunamadı. Videoyu tarayıcıda oynatıp "
                "eklentinin yakaladığı akışı (m3u8/mpd/mp4) seçmeyi deneyin.")
    if "403" in low or "forbidden" in low:
        return "Erişim reddedildi (403). Oturum/çerez gerekiyor olabilir; eklenti üzerinden göndermeyi deneyin."
    if "401" in low:
        return "Yetkisiz (401). Platforma tarayıcıda giriş yapıp eklenti üzerinden gönderin."
    return msg.replace("ERROR: ", "").strip()


def _fmt_size(n):
    if not n:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _quality_format(h: int) -> str:
    return f"bv*[height<={h}]+ba/b[height<={h}]/bv*+ba/b"


def probe_media(url, headers=None, cookiefile=None, cookies_from_browser="") -> dict:
    opts = base_opts(headers, cookiefile, cookies_from_browser)
    opts.update({"skip_download": True, "extract_flat": "in_playlist"})
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        info = ydl.sanitize_info(info)

    if info.get("_type") in ("playlist", "multi_video"):
        entries = []
        for i, e in enumerate(info.get("entries") or [], 1):
            if not e:
                continue
            eurl = e.get("webpage_url") or e.get("url")
            if not eurl:
                continue
            entries.append({"url": eurl, "title": e.get("title") or f"Bölüm {i}",
                            "duration": e.get("duration")})
        qualities = [{"id": "best", "label": "En iyi kalite", "format": "bv*+ba/b", "video": "bv*"}]
        qualities += [{"id": f"h{h}", "label": f"En fazla {h}p", "format": _quality_format(h),
                       "video": f"bv*[height<={h}]"} for h in STD_HEIGHTS]
        qualities.append({"id": "audio", "label": "Sadece ses", "format": "ba/b", "audio_only": True})
        return {"kind": "playlist", "title": info.get("title") or "Liste", "entries": entries,
                "qualities": qualities, "subtitles": [], "extractor": info.get("extractor_key")}

    formats = info.get("formats") or []
    duration = info.get("duration") or 0
    best_audio = max((f.get("filesize") or f.get("filesize_approx") or 0
                      for f in formats if f.get("vcodec") == "none"), default=0)
    by_height: dict[int, int] = {}
    for f in formats:
        h = f.get("height")
        if not h or f.get("vcodec") == "none":
            continue
        size = f.get("filesize") or f.get("filesize_approx") or (
            (f.get("tbr") or 0) * 125 * duration if duration else 0)
        if f.get("acodec") == "none":
            size = (size or 0) + best_audio if size else 0
        by_height[h] = max(by_height.get(h, 0), int(size or 0))

    qualities = [{"id": "best", "label": "En iyi kalite", "format": "bv*+ba/b", "video": "bv*"}]
    for h in sorted(by_height, reverse=True):
        size = _fmt_size(by_height[h])
        qualities.append({"id": f"h{h}", "label": f"{h}p" + (f"  (~{size})" if size else ""),
                          "format": _quality_format(h), "video": f"bv*[height<={h}]"})

    # Ayrı ses izleri (ör. DUAL: Türkçe dublaj + orijinal)
    audio_tracks, seen = [], set()
    for f in formats:
        if f.get("vcodec") != "none" or f.get("acodec") == "none":
            continue
        fid = f.get("format_id")
        if not fid or fid in seen:
            continue
        seen.add(fid)
        lang = f.get("language") or ""
        note = f.get("format_note") or ""
        label = " · ".join(x for x in (lang.upper() if lang else "", note, fid if not (lang or note) else "") if x)
        if f.get("abr"):
            label += f" ({int(f['abr'])} kbps)"
        audio_tracks.append({"id": fid, "label": label or fid, "lang": lang})
    if any(f.get("vcodec") == "none" and f.get("acodec") != "none" for f in formats):
        qualities.append({"id": "audio", "label": "Sadece ses", "format": "ba/b", "audio_only": True})

    subs = []
    for lang, lst in (info.get("subtitles") or {}).items():
        if lang in ("live_chat", "rechat"):
            continue
        name = (lst[0].get("name") if lst else None) or lang
        subs.append({"lang": lang, "name": name, "auto": False})
    for lang, lst in (info.get("automatic_captions") or {}).items():
        if lang in ("tr", "en") or lang.endswith("-orig"):
            name = (lst[0].get("name") if lst else None) or lang
            subs.append({"lang": lang, "name": f"{name} (otomatik)", "auto": True})

    return {
        "kind": "media",
        "title": info.get("title") or "video",
        "duration": duration,
        "thumbnail": info.get("thumbnail"),
        "uploader": info.get("uploader"),
        "extractor": info.get("extractor_key"),
        "qualities": qualities,
        "subtitles": subs,
        "audio_tracks": audio_tracks if len(audio_tracks) > 1 else [],
    }


def _unique_base(out_dir: Path, base: str, reserve=None) -> str:
    def on_disk(b):
        for ext in MEDIA_EXTS:
            for suffix in ("", ".part", ".ytdl"):
                if (out_dir / f"{b}.{ext}{suffix}").exists():
                    return True
        return False

    cand, i = base, 0
    while True:
        if not on_disk(cand) and (reserve is None or reserve(cand)):
            return cand
        i += 1
        cand = f"{base} ({i})"


class YtdlpEngine:
    def __init__(self, *, url, headers, cookiefile, cookies_from_browser, out_dir, title=None,
                 base_name=None, fmt="bv*+ba/b", sub_langs=(), auto_sub_langs=(), sub_format="srt",
                 embed_subs=False, connections=8, speed_limit=0, cancel_event: threading.Event,
                 on_progress, on_info, on_status, log, video_sel=None, audio_sel=None, audio_only=False,
                 reserve_name=None):
        self.url = url
        self.headers = headers or {}
        self.cookiefile = cookiefile
        self.cookies_from_browser = cookies_from_browser
        self.out_dir = Path(out_dir)
        self.title = title
        self.base_name = base_name
        self.fmt = fmt or "bv*+ba/b"
        self.sub_langs = list(sub_langs or [])
        self.auto_sub_langs = list(auto_sub_langs or [])
        self.sub_format = sub_format
        self.embed_subs = embed_subs
        self.connections = connections
        self.speed_limit = speed_limit
        self.cancel = cancel_event
        self.on_progress = on_progress
        self.on_info = on_info
        self.on_status = on_status
        self.log = log
        self._files: dict[str, tuple[int, int]] = {}
        self.skipped = 0
        self.video_sel = video_sel
        self.audio_sel = audio_sel
        self.audio_only = audio_only
        self.reserve_name = reserve_name

    def _format(self) -> tuple[str, bool]:
        """(format, çoklu_ses) döndürür."""
        a = self.audio_sel
        if not a:
            return self.fmt, False
        if self.audio_only:
            return (f"{a}/ba/b" if a != "all" else "ba/b"), False
        v = self.video_sel or "bv*"
        if a == "all":
            return f"{v}+mergeall[vcodec=none]/{v}+ba/b", True
        return f"{v}+{a}/{v}+ba/bv*+ba/b", False

    def _on_skip(self):
        self.skipped += 1

    def _hook(self, d):
        if self.cancel.is_set():
            raise DownloadCancelled()
        status = d.get("status")
        if status == "downloading":
            fname = d.get("tmpfilename") or d.get("filename") or "?"
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            self._files[fname] = (d.get("downloaded_bytes") or 0, int(total))
            downloaded = sum(v[0] for v in self._files.values())
            total_all = sum(v[1] for v in self._files.values())
            idx = list(self._files).index(fname) + 1
            info = d.get("info_dict") or {}
            kind = "ses" if info.get("vcodec") == "none" else "video"
            self.on_status(f"İndiriliyor ({kind}" + (f", dosya {idx}" if len(self._files) > 1 else "") + ")")
            self.on_progress(downloaded=downloaded, total=total_all, speed=d.get("speed") or 0)
        elif status == "finished":
            self.on_status("İşleniyor…")

    def _pp_hook(self, d):
        if d.get("status") == "started":
            names = {"Merger": "Ses ve video birleştiriliyor…",
                     "FFmpegEmbedSubtitle": "Altyazı gömülüyor…",
                     "FFmpegSubtitlesConvertor": "Altyazı dönüştürülüyor…"}
            self.on_status(names.get(d.get("postprocessor"), "İşleniyor…"))

    def run(self) -> str:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        opts = base_opts(self.headers, self.cookiefile, self.cookies_from_browser, self.log,
                         on_skip=self._on_skip)
        with yt_dlp.YoutubeDL(opts) as ydl:
            self.on_status("Analiz ediliyor…")
            info = ydl.extract_info(self.url, download=False)
            info = ydl.sanitize_info(info)

        if info.get("_type") in ("playlist", "multi_video"):
            raise RuntimeError("Bu bağlantı bir liste; lütfen bölümleri ekleme penceresinden seçin.")

        if not self.base_name:
            base = sanitize_filename(self.title or info.get("title") or "video")
            self.base_name = _unique_base(self.out_dir, base, self.reserve_name)
            self.on_info(base_name=self.base_name, filename=self.base_name)

        has_subs = bool(self.sub_langs or self.auto_sub_langs)
        pps = []
        if has_subs and self.sub_format in ("srt", "vtt"):
            pps.append({"key": "FFmpegSubtitlesConvertor", "format": self.sub_format, "when": "before_dl"})
        if has_subs and self.embed_subs:
            pps.append({"key": "FFmpegEmbedSubtitle", "already_have_subtitle": True})

        tmpl = str(self.out_dir / (self.base_name.replace("%", "%%") + ".%(ext)s"))
        fmt, multi_audio = self._format()
        opts.update({
            "format": fmt,
            "allow_multiple_audio_streams": multi_audio,
            "outtmpl": {"default": tmpl},
            "merge_output_format": "mkv" if (self.embed_subs or multi_audio) else "mp4/mkv",
            "concurrent_fragment_downloads": max(1, min(self.connections, MAX_HLS_CONNECTIONS)),
            "continuedl": True,
            "writesubtitles": bool(self.sub_langs),
            "writeautomaticsub": bool(self.auto_sub_langs),
            "subtitleslangs": self.sub_langs + self.auto_sub_langs,
            "subtitlesformat": "srt/vtt/best" if self.sub_format == "srt" else (
                "vtt/srt/best" if self.sub_format == "vtt" else "best"),
            "postprocessors": pps,
            "progress_hooks": [self._hook],
            "postprocessor_hooks": [self._pp_hook],
        })
        if self.speed_limit:
            opts["ratelimit"] = self.speed_limit * 1024

        with yt_dlp.YoutubeDL(opts) as ydl:
            result = ydl.process_ie_result(info, download=True)

        path = None
        downloads = (result or {}).get("requested_downloads") or []
        if downloads:
            path = downloads[0].get("filepath") or downloads[0].get("_filename")
        path = path or (result or {}).get("filepath") or (result or {}).get("_filename")
        if not path or not os.path.exists(path):
            for ext in MEDIA_EXTS:
                p = self.out_dir / f"{self.base_name}.{ext}"
                if p.exists():
                    path = str(p)
                    break
        if not path:
            raise RuntimeError("İndirme tamamlandı ancak çıktı dosyası bulunamadı.")
        return path
