import os
import re
import shutil
import subprocess
import sys
import time
from collections import deque
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from urllib.parse import unquote, urlparse

# macOS'ta uygulama Finder'dan (çift tıkla) açılınca Homebrew klasörleri PATH'te olmayabilir;
# ffmpeg'in her durumda bulunması için bilinen klasörleri PATH'e ekle.
for _d in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/snap/bin"):
    if os.path.isdir(_d) and _d not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + _d

INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

DIRECT_EXTS = {
    # video / ses
    "mp4", "m4v", "mkv", "webm", "mov", "avi", "flv", "wmv", "mpg", "mpeg", "3gp", "ogv",
    "mp3", "m4a", "aac", "ogg", "oga", "opus", "wav", "flac", "wma",
    # diğer
    "zip", "rar", "7z", "tar", "gz", "bz2", "xz", "iso", "img", "dmg", "exe", "msi", "pkg",
    "deb", "rpm", "apk", "pdf", "epub", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
    "jpg", "jpeg", "png", "gif", "webp", "srt", "vtt", "ass", "torrent", "bin",
}
MANIFEST_EXTS = {"m3u8", "mpd", "ism", "f4m"}
SUBTITLE_EXTS = {"vtt", "srt", "ass", "ssa", "ttml", "dfxp", "webvtt", "sbv"}


def sanitize_filename(name: str, max_len: int = 180) -> str:
    name = INVALID_CHARS.sub("_", name or "").strip().strip(".")
    name = re.sub(r"\s+", " ", name)
    if len(name.encode("utf-8")) > max_len:
        name = name.encode("utf-8")[:max_len].decode("utf-8", "ignore").rstrip()
    return name or "indirme"


def url_ext(url: str) -> str:
    path = urlparse(url).path
    base = path.rsplit("/", 1)[-1]
    if "." not in base:
        return ""
    return base.rsplit(".", 1)[-1].lower()


def filename_from_url(url: str) -> str:
    base = unquote(urlparse(url).path.rsplit("/", 1)[-1])
    return sanitize_filename(base) if base else "indirme"


def filename_from_disposition(value: str):
    if not value:
        return None
    m = re.search(r"filename\*\s*=\s*([^']*)'[^']*'([^;]+)", value, re.I)
    if m:
        try:
            return sanitize_filename(unquote(m.group(2).strip().strip('"'), encoding=m.group(1) or "utf-8"))
        except LookupError:
            return sanitize_filename(unquote(m.group(2).strip().strip('"')))
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', value, re.I)
    if m:
        return sanitize_filename(m.group(1).strip())
    return None


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    i = 1
    while True:
        cand = path.with_name(f"{stem} ({i}){suffix}")
        if not cand.exists() and not Path(str(cand) + ".part").exists():
            return cand
        i += 1


def write_cookie_file(cookies: list, path: Path) -> Path | None:
    """Tarayıcı eklentisinden gelen çerezleri Netscape formatında yazar."""
    if not cookies:
        return None
    lines = ["# Netscape HTTP Cookie File", ""]
    seen = set()
    for c in cookies:
        try:
            domain = c.get("domain") or ""
            name = c.get("name") or ""
            key = (domain, c.get("path", "/"), name)
            if not domain or key in seen:
                continue
            seen.add(key)
            host_only = c.get("hostOnly", False)
            if not host_only and not domain.startswith("."):
                domain = "." + domain
            if host_only:
                domain = domain.lstrip(".")
            include_sub = "FALSE" if host_only else "TRUE"
            secure = "TRUE" if c.get("secure") else "FALSE"
            expiry = int(c.get("expirationDate") or 0) or int(time.time()) + 86400
            value = str(c.get("value", "")).replace("\t", " ").replace("\n", " ")
            prefix = "#HttpOnly_" if c.get("httpOnly") else ""
            lines.append("\t".join([prefix + domain, include_sub, c.get("path", "/") or "/",
                                    secure, str(expiry), name, value]))
        except Exception:
            continue
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", "utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def load_cookie_jar(path) -> MozillaCookieJar | None:
    if not path or not Path(path).exists():
        return None
    jar = MozillaCookieJar(str(path))
    jar.load(ignore_discard=True, ignore_expires=True)
    return jar


SKIP_HEADERS = {
    "range", "host", "content-length", "accept-encoding", "connection", "cookie",
    "if-range", "if-none-match", "if-modified-since", "upgrade-insecure-requests",
    "priority", "te", "pragma", "cache-control",
}


def clean_headers(headers: dict | None) -> dict:
    out = {}
    for k, v in (headers or {}).items():
        lk = k.lower()
        if lk in SKIP_HEADERS or lk.startswith("sec-") or lk.startswith(":"):
            continue
        out[k] = v
    return out


class SpeedMeter:
    def __init__(self, window: float = 4.0):
        self.window = window
        self.samples = deque()

    def update(self, total_bytes: int) -> float:
        now = time.monotonic()
        self.samples.append((now, total_bytes))
        while len(self.samples) > 2 and now - self.samples[0][0] > self.window:
            self.samples.popleft()
        if len(self.samples) < 2:
            return 0.0
        (t0, b0), (t1, b1) = self.samples[0], self.samples[-1]
        return max(0.0, (b1 - b0) / (t1 - t0)) if t1 > t0 else 0.0


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def ffprobe_path() -> str | None:
    return shutil.which("ffprobe")


def run_quiet(cmd: list, timeout: int = 3600) -> subprocess.CompletedProcess:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=timeout, **kwargs)


def open_in_file_manager(path: str):
    p = Path(path)
    if sys.platform == "win32":
        if p.is_file():
            subprocess.Popen(f'explorer /select,"{p}"')
        else:
            os.startfile(str(p if p.exists() else p.parent))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        if p.is_file():
            subprocess.Popen(["open", "-R", str(p)])
        else:
            subprocess.Popen(["open", str(p if p.exists() else p.parent)])
    else:
        subprocess.Popen(["xdg-open", str(p.parent if p.is_file() else p)])
