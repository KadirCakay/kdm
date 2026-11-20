"""BigBlueButton kayıt motoru.

BBB "presentation" kayıtları tek bir video değildir:
  video/webcams.webm      -> kamera + SES
  deskshare/deskshare.webm-> ekran paylaşımı (sessiz, kaydın tamamı boyunca)
  shapes.svg              -> hangi zaman aralığında hangi slaytın gösterildiği
  deskshare.xml           -> ekran paylaşımı aralıkları
Bu motor parçaları indirir ve slayt + ekran paylaşımı + sesi tek MP4'te birleştirir.
"""
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from ..utils import ffmpeg_path, sanitize_filename, unique_path
from .http_engine import Cancelled, HttpEngine, make_session, probe_http

BBB_ID = re.compile(r"([0-9a-f]{40}-\d{13})")
W, H = 1280, 720
MEDIA = {
    "webcams": ["video/webcams.webm", "video/webcams.mp4"],
    "audio": ["audio/audio.webm", "audio/audio.ogg", "audio/audio.opus", "audio/audio.mp4"],
    "deskshare": ["deskshare/deskshare.webm", "deskshare/deskshare.mp4"],
}
MODES = {
    "full": "Sunum: slaytlar + ekran paylaşımı + ses (önerilen)",
    "full_cam": "Sunum + köşede kamera görüntüsü",
    "desk": "Yalnızca ekran paylaşımı + ses (en hızlı, slayt bölümleri boş)",
    "cam": "Yalnızca kamera + ses",
    "audio": "Yalnızca ses (m4a)",
}


def detect_bbb(url: str) -> str | None:
    """BBB oynatma veya medya adresinden kayıt kök adresini döndürür."""
    try:
        p = urlparse(url)
    except ValueError:
        return None
    m = BBB_ID.search(url)
    if not m or not p.scheme.startswith("http"):
        return None
    if "/playback/" in p.path or "/presentation/" in p.path or "meetingId=" in p.query:
        return f"{p.scheme}://{p.netloc}/presentation/{m.group(1)}"
    return None


def _xml(session, url):
    r = session.get(url, timeout=(15, 60))
    if r.status_code != 200:
        return None
    try:
        return ET.fromstring(r.content)
    except ET.ParseError:
        return None


def _exists(session, url) -> int | None:
    try:
        info = probe_http(url, session=session)
        if "html" in info["content_type"]:
            return None
        return info["size"] or 1
    except Exception:
        return None


def load_recording(base: str, headers=None, cookiefile=None) -> dict:
    s = make_session(headers, cookiefile)
    meta = _xml(s, base + "/metadata.xml")
    if meta is None:
        raise RuntimeError("BigBlueButton kaydı bulunamadı (metadata.xml okunamadı). "
                           "Kayıt silinmiş veya erişim için giriş gerekiyor olabilir.")
    name = (meta.findtext("meta/name") or "").strip()
    meeting = (meta.findtext("meta/meetingName") or "").strip()
    if not meeting and meta.find("meeting") is not None:
        meeting = (meta.find("meeting").get("name") or "").strip()
    start_ms = int(meta.findtext("start_time") or 0)
    duration = int(meta.findtext("playback/duration") or 0) / 1000.0
    date = datetime.fromtimestamp(start_ms / 1000).strftime("%d.%m.%Y") if start_ms else ""
    parts = [x for x in (meeting, name if name != meeting else "", date) if x]
    title = " - ".join(parts) or "BBB kaydı"

    media = {}
    for key, cands in MEDIA.items():
        for c in cands:
            size = _exists(s, f"{base}/{c}")
            if size:
                media[key] = {"url": f"{base}/{c}", "size": size if size > 1 else 0}
                break

    images = []
    svg = _xml(s, base + "/shapes.svg")
    if svg is not None:
        for el in svg.iter():
            if not el.tag.endswith("image"):
                continue
            href = el.get("{http://www.w3.org/1999/xlink}href") or el.get("href") or ""
            try:
                images.append({"in": float(el.get("in", 0)), "out": float(el.get("out", 0)), "href": href})
            except ValueError:
                continue
    desk_events = []
    dx = _xml(s, base + "/deskshare.xml")
    if dx is not None:
        for ev in dx.iter("event"):
            try:
                desk_events.append((float(ev.get("start_timestamp")), float(ev.get("stop_timestamp"))))
            except (TypeError, ValueError):
                pass
    captions = []
    try:
        r = s.get(base + "/captions.json", timeout=(15, 30))
        if r.status_code == 200:
            for c in r.json() or []:
                loc = c.get("locale")
                if loc:
                    captions.append({"url": f"{base}/caption_{loc}.vtt", "lang": loc.split("-")[0],
                                     "name": c.get("localeName") or loc})
    except Exception:
        pass
    if not duration and images:
        duration = max(i["out"] for i in images)
    return {"base": base, "title": title, "duration": duration, "media": media,
            "images": images, "desk_events": desk_events, "captions": captions}


def probe_bbb(base, headers=None, cookiefile=None) -> dict:
    rec = load_recording(base, headers, cookiefile)
    m = rec["media"]
    has_audio = "webcams" in m or "audio" in m
    if not has_audio:
        raise RuntimeError("Kayıtta ses/kamera dosyası bulunamadı.")
    modes = ["full"]
    if "webcams" in m:
        modes.append("full_cam")
    if "deskshare" in m:
        modes.append("desk")
    if "webcams" in m:
        modes.append("cam")
    modes.append("audio")
    size = sum(v["size"] for v in m.values())
    slides = len({i["href"] for i in rec["images"] if "deskshare" not in i["href"]})
    return {
        "kind": "bbb", "title": rec["title"], "duration": rec["duration"], "extractor": "BigBlueButton",
        "size": size, "qualities": [{"id": k, "label": MODES[k], "format": k} for k in modes],
        "subtitles": [], "extra_subtitles": rec["captions"],
        "note": f"{slides} slayt, {len(rec['desk_events'])} ekran paylaşımı bölümü"
                + ("" if "deskshare" in m else " (ekran paylaşımı yok)"),
    }


# ----------------------------------------------------------------- zaman çizelgesi

def _override(segs, a, b, src):
    out = []
    for s0, s1, ss in segs:
        if s1 <= a or s0 >= b:
            out.append([s0, s1, ss])
            continue
        if s0 < a:
            out.append([s0, a, ss])
        if s1 > b:
            out.append([b, s1, ss])
    out.append([a, b, src])
    return sorted(out, key=lambda x: x[0])


def build_timeline(rec, fps, has_desk) -> list[tuple[int, int, str]]:
    D = rec["duration"]
    segs = []
    for img in sorted(rec["images"], key=lambda i: i["in"]):
        a, b = max(0.0, img["in"]), min(D, img["out"])
        if b <= a:
            continue
        src = "desk" if "deskshare" in img["href"] else img["href"]
        segs = _override(segs, a, b, src)
    for a, b in rec["desk_events"]:
        a, b = max(0.0, a), min(D, b)
        if b > a:
            segs = _override(segs, a, b, "desk")
    # boşlukları doldur
    filled, t = [], 0.0
    gap_src = "desk" if has_desk else "black"
    for s0, s1, src in segs:
        if s0 > t:
            filled.append([t, s0, gap_src])
        filled.append([s0, s1, src])
        t = max(t, s1)
    if t < D:
        filled.append([t, D, gap_src])
    # kare ızgarasına oturt, komşu aynıları birleştir
    out = []
    for s0, s1, src in filled:
        if src == "desk" and not has_desk:
            src = "black"
        f0, f1 = round(s0 * fps), round(s1 * fps)
        if f1 <= f0:
            continue
        if out and out[-1][2] == src and out[-1][1] == f0:
            out[-1] = (out[-1][0], f1, src)
        else:
            out.append((f0, f1, src))
    return out


# ----------------------------------------------------------------- slayt çizimi

def _strip_svg_size(svg_text: str) -> str:
    def fix(m):
        tag = re.sub(r'\s(width|height)="[^"]*"', "", m.group(0))
        return tag
    return re.sub(r"<svg\b[^>]*>", fix, svg_text, count=1)


def render_slide(session, url: str, dest: Path, log) -> bool:
    r = session.get(url, timeout=(15, 120))
    if r.status_code != 200:
        return False
    if url.lower().split("?")[0].endswith(".svg") or b"<svg" in r.content[:2000]:
        try:
            import resvg_py
        except ImportError:
            log("resvg-py kurulu değil; slaytlar düşük çözünürlüklü küçük resimlerden alınacak")
            return False
        try:
            png = resvg_py.svg_to_bytes(svg_string=_strip_svg_size(r.content.decode("utf-8", "ignore")),
                                        width=W, background="#ffffff")
            dest.write_bytes(bytes(png))
            return True
        except Exception as e:  # noqa: BLE001
            log(f"Slayt çizilemedi ({url.rsplit('/', 1)[-1]}): {e}")
            return False
    dest.write_bytes(r.content)
    return True


def _thumb_url(base, href):
    m = re.search(r"(presentation/[^/]+)/svgs/slide(\d+)\.svg", href)
    if m:
        return f"{base}/{m.group(1)}/thumbnails/thumb-{m.group(2)}.png"
    return None


# ----------------------------------------------------------------- motor

class BbbEngine:
    def __init__(self, *, url, headers, cookiefile, out_dir, work_dir, title=None, filepath=None,
                 mode="full", connections=8, cancel_event: threading.Event, on_progress, on_info,
                 on_status, log, speed_limit=0):
        self.base = detect_bbb(url)
        if not self.base:
            raise RuntimeError("BigBlueButton adresi tanınamadı")
        self.headers = headers or {}
        self.cookiefile = cookiefile
        self.out_dir = Path(out_dir)
        self.work = Path(work_dir)
        self.title = title
        self.filepath = Path(filepath) if filepath else None
        self.mode = mode if mode in MODES else "full"
        self.connections = connections
        self.cancel = cancel_event
        self.on_progress = on_progress
        self.on_info = on_info
        self.on_status = on_status
        self.log = log
        self.speed_limit = speed_limit
        self.ff = ffmpeg_path()

    def _check(self):
        if self.cancel.is_set():
            raise Cancelled()

    # -- indirme
    def _download_all(self, rec, keys):
        items = [(k, rec["media"][k]) for k in keys if k in rec["media"]]
        total = sum(v["size"] for _, v in items)
        done_before = 0
        paths = {}
        for k, v in items:
            ext = v["url"].rsplit(".", 1)[-1]
            dest = self.work / f"{k}.{ext}"
            paths[k] = dest
            if dest.exists() and (not v["size"] or dest.stat().st_size == v["size"]):
                done_before += v["size"]
                continue
            self.on_status(f"İndiriliyor: {k}")
            offset = done_before

            def prog(downloaded=0, total=0, speed=0, _o=offset, _all=total):
                self.on_progress(downloaded=_o + downloaded, total=_all, speed=speed)

            HttpEngine(url=v["url"], headers=self.headers, cookiefile=self.cookiefile, out_dir=self.work,
                       filepath=dest, connections=self.connections, cancel_event=self.cancel,
                       on_progress=prog, on_info=lambda **kw: None, speed_limit=self.speed_limit,
                       log=self.log).run()
            done_before += v["size"] or dest.stat().st_size
        self.on_progress(downloaded=done_before, total=total or done_before, speed=0)
        return paths

    # -- ffmpeg
    def _ffmpeg(self, args, total_frames=0, label="", frame_offset=0, grand_total=0, duration=0):
        cmd = [self.ff, "-y", "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1"] + args
        kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             encoding="utf-8", errors="ignore", **kw)
        err_lines = []
        threading.Thread(target=lambda: err_lines.extend(p.stderr), daemon=True).start()
        last = 0.0
        try:
            for line in p.stdout:
                if self.cancel.is_set():
                    p.kill()
                    raise Cancelled()
                if line.startswith("frame=") and grand_total:
                    try:
                        f = frame_offset + int(line.split("=", 1)[1])
                    except ValueError:
                        continue
                    if time.monotonic() - last > 0.5:
                        last = time.monotonic()
                        pct = min(99.9, f * 100.0 / grand_total)
                        self.on_status(f"{label} %{pct:.0f}")
                        self.on_progress(pct=pct)
                elif line.startswith("out_time_us=") and duration:
                    try:
                        sec = int(line.split("=", 1)[1]) / 1e6
                    except ValueError:
                        continue
                    if time.monotonic() - last > 0.5:
                        last = time.monotonic()
                        pct = max(0.0, min(99.9, sec * 100.0 / duration))
                        self.on_status(f"{label} %{pct:.0f}")
                        self.on_progress(pct=pct)
            p.wait()
        finally:
            if p.poll() is None:
                p.kill()
        if p.returncode != 0:
            raise RuntimeError("ffmpeg hatası: " + "".join(err_lines)[-500:])

    def _final_path(self, ext):
        if self.filepath and self.filepath.suffix == "." + ext:
            return self.filepath
        name = sanitize_filename(self.title or "BBB kaydı")
        self.out_dir.mkdir(parents=True, exist_ok=True)
        p = unique_path(self.out_dir / f"{name}.{ext}")
        self.filepath = p
        self.on_info(filename=p.name, filepath=str(p))
        return p

    def run(self) -> str:
        if not self.ff:
            raise RuntimeError("Bu işlem için ffmpeg gerekli.")
        self.work.mkdir(parents=True, exist_ok=True)
        self.on_status("Kayıt bilgileri okunuyor…")
        rec = load_recording(self.base, self.headers, self.cookiefile)
        if not self.title:
            self.title = rec["title"]
        audio_key = "webcams" if "webcams" in rec["media"] else "audio"
        mode = self.mode
        if mode in ("cam", "full_cam") and "webcams" not in rec["media"]:
            mode = "full"
        if mode == "desk" and "deskshare" not in rec["media"]:
            mode = "full"

        if mode == "cam":
            paths = self._download_all(rec, ["webcams"])
            src = paths["webcams"]
            out = self._final_path(src.suffix.lstrip("."))
            shutil.move(str(src), out)
            return self._done(out)

        if mode == "audio":
            paths = self._download_all(rec, [audio_key])
            out = self._final_path("m4a")
            self.on_status("Ses dönüştürülüyor…")
            self._ffmpeg(["-i", str(paths[audio_key]), "-vn", "-c:a", "aac", "-b:a", "128k", str(out) + ".tmp.m4a"],
                         label="Ses dönüştürülüyor", duration=rec["duration"])
            Path(str(out) + ".tmp.m4a").replace(out)
            return self._done(out)

        if mode == "desk":
            paths = self._download_all(rec, ["deskshare", audio_key])
            out = self._final_path("mkv")
            self.on_status("Birleştiriliyor…")
            self._ffmpeg(["-i", str(paths["deskshare"]), "-i", str(paths[audio_key]), "-map", "0:v:0",
                          "-map", "1:a:0", "-c", "copy", str(out) + ".tmp.mkv"])
            Path(str(out) + ".tmp.mkv").replace(out)
            return self._done(out)

        # ---- tam sunum
        cam = mode == "full_cam"
        keys = [k for k in ("deskshare", audio_key, "webcams" if cam else None) if k]
        paths = self._download_all(rec, list(dict.fromkeys(keys)))
        has_desk = "deskshare" in paths
        fps = 15 if cam else 5
        timeline = build_timeline(rec, fps, has_desk)
        if not timeline:
            raise RuntimeError("Kayıt zaman çizelgesi boş.")

        # slaytlar
        session = make_session(self.headers, self.cookiefile)
        slide_files = {}
        hrefs = sorted({src for _, _, src in timeline if src not in ("desk", "black")})
        for i, href in enumerate(hrefs, 1):
            self._check()
            self.on_status(f"Slaytlar hazırlanıyor ({i}/{len(hrefs)})")
            dest = self.work / f"slide_{i:04d}.png"
            if not dest.exists():
                ok = render_slide(session, urljoin(self.base + "/", href), dest, self.log)
                if not ok:
                    t = _thumb_url(self.base, href)
                    ok = bool(t) and render_slide(session, t, dest, self.log)
                if not ok:
                    self.log(f"Slayt alınamadı, siyah ekran kullanılacak: {href}")
                    continue
            slide_files[href] = dest

        fit = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
               f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=%s,setsar=1,fps={fps},format=yuv420p")
        total_frames = sum(f1 - f0 for f0, f1, _ in timeline)
        done_frames = 0
        seg_list = []
        enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-g", str(fps * 10),
               "-pix_fmt", "yuv420p", "-video_track_timescale", "90000", "-an"]
        for idx, (f0, f1, src) in enumerate(timeline):
            self._check()
            n = f1 - f0
            seg = self.work / f"seg_{idx:05d}.mp4"
            okf = self.work / f"seg_{idx:05d}.ok"
            seg_list.append(seg)
            if seg.exists() and okf.exists():
                done_frames += n
                continue
            start = f0 / fps
            args = []
            if src == "desk":
                args += ["-ss", f"{start:.3f}", "-i", str(paths["deskshare"])]
                color = "black"
            elif src in slide_files:
                args += ["-loop", "1", "-framerate", str(fps), "-i", str(slide_files[src])]
                color = "white"
            else:
                args += ["-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={fps}"]
                color = "black"
            if cam:
                args += ["-ss", f"{start:.3f}", "-i", str(paths["webcams"])]
                args += ["-filter_complex",
                         f"[0:v]{fit % color}[bg];[1:v]scale=320:-2,fps={fps}[c];"
                         f"[bg][c]overlay=W-w-12:H-h-12:eof_action=pass,format=yuv420p[v]",
                         "-map", "[v]"]
            else:
                args += ["-vf", fit % color]
            args += ["-frames:v", str(n)] + enc + [str(seg)]
            self._ffmpeg(args, label="Video oluşturuluyor", frame_offset=done_frames, grand_total=total_frames)
            okf.write_text("ok")
            done_frames += n

        lst = self.work / "list.txt"
        lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in seg_list), "utf-8")
        out = self._final_path("mp4")
        tmp = Path(str(out) + ".tmp.mp4")
        self.on_status("Ses ekleniyor…")
        self._ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(paths[audio_key]),
                      "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                      "-shortest", "-movflags", "+faststart", str(tmp)],
                     label="Ses ekleniyor", duration=rec["duration"])
        tmp.replace(out)
        return self._done(out)

    def _done(self, out: Path) -> str:
        shutil.rmtree(self.work, ignore_errors=True)
        self.on_progress(pct=None)
        return str(out)
