"""Tarayıcı eklentisinin yakaladığı harici altyazıları indirir, dönüştürür ve isterse gömer."""
import os
import re
from pathlib import Path
from urllib.parse import urljoin

from .engines.http_engine import make_session
from .utils import ffmpeg_path, ffprobe_path, run_quiet, sanitize_filename, url_ext


def _detect_ext(url: str, text: str) -> str:
    head = text.lstrip("\ufeff \r\n")[:200]
    if head.startswith("WEBVTT"):
        return "vtt"
    if head.startswith("[Script Info]"):
        return "ass"
    if head.startswith("<?xml") or "<tt" in head:
        return "ttml"
    if re.search(r"\d\d:\d\d:\d\d,\d{3}\s*-->", text[:2000]):
        return "srt"
    ext = url_ext(url)
    return ext if ext in ("vtt", "srt", "ass", "ssa", "ttml", "dfxp") else "vtt"


def _fetch_text(session, url: str) -> str:
    r = session.get(url, timeout=(15, 60))
    r.raise_for_status()
    r.encoding = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else "utf-8"
    return r.text


def _fetch_subtitle(session, url: str) -> tuple[str, str]:
    text = _fetch_text(session, url)
    if text.lstrip().startswith("#EXTM3U"):
        # Parçalı WebVTT (HLS altyazı listesi): parçaları birleştir
        seg_urls = [urljoin(url, ln.strip()) for ln in text.splitlines()
                    if ln.strip() and not ln.startswith("#")]
        if seg_urls and seg_urls[0].split("?")[0].endswith(".m3u8"):
            return _fetch_subtitle(session, seg_urls[0])
        parts = ["WEBVTT", ""]
        for su in seg_urls:
            body = _fetch_text(session, su)
            lines = [ln for ln in body.splitlines()
                     if not ln.startswith("WEBVTT") and not ln.startswith("X-TIMESTAMP-MAP")]
            parts.append("\n".join(lines).strip())
            parts.append("")
        return "\n".join(parts), "vtt"
    return text, _detect_ext(url, text)


def download_extra_subtitles(video_path: str, subs: list, headers: dict, cookiefile,
                             sub_format: str, log) -> list[tuple[str, str]]:
    """Her altyazıyı video ile aynı isimde kaydeder: video.tr.srt gibi. [(yol, dil)] döndürür."""
    if not subs:
        return []
    session = make_session(headers, cookiefile)
    base = os.path.splitext(video_path)[0]
    ff = ffmpeg_path()
    out = []
    used = set()
    for s in subs:
        url = s.get("url")
        if not url:
            continue
        lang = sanitize_filename(s.get("lang") or "und", 20).replace(" ", "_")
        tag = lang
        i = 2
        while tag in used:
            tag = f"{lang}{i}"
            i += 1
        used.add(tag)
        try:
            text, ext = _fetch_subtitle(session, url)
            path = Path(f"{base}.{tag}.{ext}")
            text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
            path.write_bytes(text.encode("utf-8"))
            if sub_format == "srt" and ext != "srt" and ff:
                srt = path.with_suffix(".srt")
                res = run_quiet([ff, "-y", "-loglevel", "error", "-i", str(path), str(srt)], timeout=300)
                if res.returncode == 0 and srt.exists() and srt.stat().st_size > 0:
                    path.unlink(missing_ok=True)
                    path = srt
                else:
                    srt.unlink(missing_ok=True)
                    log("Altyazı srt'ye dönüştürülemedi, orijinal biçimde bırakıldı")
            out.append((str(path), lang))
            log(f"Altyazı kaydedildi: {path.name}")
        except Exception as e:  # noqa: BLE001
            log(f"Altyazı indirilemedi ({lang}): {e}")
    return out


def embed_subtitles(video_path: str, subs: list[tuple[str, str]], log) -> str:
    """Altyazıları MKV içine gömer. Yeni dosya yolunu döndürür."""
    ff = ffmpeg_path()
    if not subs or not ff:
        if subs and not ff:
            log("ffmpeg bulunamadı, altyazılar gömülemedi (ayrı dosya olarak duruyor)")
        return video_path
    existing = 0
    fp = ffprobe_path()
    if fp:
        res = run_quiet([fp, "-v", "error", "-select_streams", "s", "-show_entries", "stream=index",
                         "-of", "csv=p=0", video_path], timeout=60)
        existing = len([ln for ln in res.stdout.decode(errors="ignore").splitlines() if ln.strip()])
    src = Path(video_path)
    tmp = src.with_name(src.stem + ".kdmtmp.mkv")
    cmd = [ff, "-y", "-loglevel", "error", "-i", str(src)]
    for p, _ in subs:
        cmd += ["-i", p]
    cmd += ["-map", "0"]
    for i in range(len(subs)):
        cmd += ["-map", str(i + 1)]
    cmd += ["-c", "copy", "-c:s", "srt"]
    for i, (_, lang) in enumerate(subs):
        cmd += [f"-metadata:s:s:{existing + i}", f"language={lang}"]
    cmd.append(str(tmp))
    res = run_quiet(cmd)
    if res.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        log("Altyazı gömme başarısız: " + res.stderr.decode(errors="ignore")[-300:])
        return video_path
    final = src.with_suffix(".mkv")
    src.unlink()
    os.replace(tmp, final)
    log("Altyazılar videoya gömüldü (MKV)")
    return str(final)
