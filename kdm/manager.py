"""İndirme kuyruğu: görevleri saklar, eşzamanlılığı yönetir, motorları çalıştırır."""
import glob
import json
import os
import re
import shutil
import threading
import time
import traceback
import uuid
from pathlib import Path

from .config import COOKIE_DIR, TASKS_FILE, Config
from .engines.bbb_engine import BbbEngine
from .engines.http_engine import Cancelled, HttpEngine
from .engines.ytdlp_engine import YtdlpEngine, friendly_error
from .subtitles import download_extra_subtitles, embed_subtitles
from .utils import clean_headers, write_cookie_file

try:
    from yt_dlp.utils import DownloadCancelled
except Exception:  # pragma: no cover
    DownloadCancelled = Cancelled

PERSIST_FIELDS = [
    "id", "url", "page_url", "kind", "title", "filename", "filepath", "base_name", "out_dir",
    "status", "status_text", "downloaded", "total", "error", "created", "finished", "opts",
    "cookiefile", "logs",
]
ACTIVE = ("running",)
AUTO_RETRIES = 3


class Task:
    def __init__(self, **kw):
        self.id = kw.get("id") or uuid.uuid4().hex[:12]
        self.url = kw["url"]
        self.page_url = kw.get("page_url") or ""
        self.kind = kw.get("kind") or "media"         # http | media
        self.title = kw.get("title") or ""
        self.filename = kw.get("filename") or ""
        self.filepath = kw.get("filepath") or ""
        self.base_name = kw.get("base_name") or ""
        self.out_dir = kw.get("out_dir") or ""
        self.status = kw.get("status") or "queued"    # queued running paused completed error canceled
        self.status_text = kw.get("status_text") or ""
        self.downloaded = kw.get("downloaded") or 0
        self.total = kw.get("total") or 0
        self.error = kw.get("error") or ""
        self.created = kw.get("created") or time.time()
        self.finished = kw.get("finished") or 0
        self.opts = kw.get("opts") or {}
        self.cookiefile = kw.get("cookiefile") or ""
        self.logs = kw.get("logs") or []
        self.speed = 0.0
        self.progress_pct = None   # dönüştürme gibi bayt dışı aşamalarda ilerleme
        self.cancel_event = threading.Event()
        self.stop_reason = ""
        self.auto_retries = 0
        self.thread: threading.Thread | None = None

    def log(self, msg: str):
        line = time.strftime("%H:%M:%S ") + str(msg)
        self.logs = (self.logs + [line])[-60:]

    def to_dict(self, full=False):
        d = {k: getattr(self, k) for k in PERSIST_FIELDS}
        d["speed"] = self.speed
        d["eta"] = int((self.total - self.downloaded) / self.speed) if self.speed > 0 and self.total else None
        if self.progress_pct is not None and self.status == "running":
            d["progress"] = round(self.progress_pct, 1)
            d["eta"] = None
        else:
            d["progress"] = round(self.downloaded * 100 / self.total, 1) if self.total else None
        if not full:
            d.pop("cookiefile", None)
            d["opts"] = {k: v for k, v in self.opts.items() if k != "headers"}
        return d


class Manager:
    def __init__(self, config: Config):
        self.config = config
        self.lock = threading.RLock()
        self.tasks: dict[str, Task] = {}
        self._dirty = False
        self._load()
        threading.Thread(target=self._saver, daemon=True).start()

    # ------------------------------------------------------------ persistence
    def _load(self):
        if not TASKS_FILE.exists():
            return
        try:
            for d in json.loads(TASKS_FILE.read_text("utf-8")):
                t = Task(**d)
                if t.status in ("running", "queued"):
                    t.status, t.status_text = "paused", "Duraklatıldı"
                self.tasks[t.id] = t
        except Exception:
            traceback.print_exc()

    def save(self):
        with self.lock:
            data = [t.to_dict(full=True) for t in self.tasks.values()]
            for d in data:
                d.pop("speed", None)
                d.pop("eta", None)
                d.pop("progress", None)
        tmp = TASKS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
        os.replace(tmp, TASKS_FILE)

    def _saver(self):
        while True:
            time.sleep(3)
            if self._dirty:
                self._dirty = False
                try:
                    self.save()
                except Exception:
                    traceback.print_exc()

    def _touch(self):
        self._dirty = True

    # ------------------------------------------------------------------ API
    def list_tasks(self):
        with self.lock:
            return [t.to_dict() for t in sorted(self.tasks.values(), key=lambda t: t.created)]

    def add(self, p: dict) -> list[Task]:
        """p: url, kind, title, filename, out_dir, format, audio_only, sub_langs, auto_sub_langs,
        extra_subs, embed_subs, headers, cookies, page_url, entries"""
        out_dir = p.get("out_dir") or self.config["download_dir"]
        headers = clean_headers(p.get("headers"))
        common = {
            "format": p.get("format") or "bv*+ba/b",
            "video_sel": p.get("video_sel") or "",
            "audio_sel": p.get("audio_sel") or "",
            "audio_only": bool(p.get("audio_only")),
            "sub_langs": list(p.get("sub_langs") or []),
            "auto_sub_langs": list(p.get("auto_sub_langs") or []),
            "extra_subs": list(p.get("extra_subs") or []),
            "embed_subs": bool(p.get("embed_subs", self.config["embed_subtitles"])),
            "headers": headers,
        }
        entries = p.get("entries") or []
        if entries:
            # Dizi / liste: her bölüm ayrı görev, isteğe bağlı alt klasör
            sub = p.get("folder_name")
            if sub:
                from .utils import sanitize_filename
                out_dir = str(Path(out_dir) / sanitize_filename(sub))
            items = [{"url": e["url"], "title": e.get("title") or ""} for e in entries]
            kind = "media"
            common["extra_subs"] = []
        else:
            items = [{"url": p["url"], "title": p.get("title") or p.get("filename") or ""}]
            kind = p.get("kind") or "media"

        created = []
        with self.lock:
            busy = {(x.url, x.opts.get("format")) for x in self.tasks.values()
                    if x.status in ("queued", "running", "paused")}
            for it in items:
                if (it["url"], common["format"]) in busy:
                    continue  # aynı video zaten listede (çift tıklama vb.)
                t = Task(url=it["url"], page_url=p.get("page_url"), kind=kind, title=it["title"],
                         out_dir=out_dir, opts=dict(common))
                if p.get("cookies"):
                    cf = write_cookie_file(p["cookies"], COOKIE_DIR / f"{t.id}.txt")
                    t.cookiefile = str(cf) if cf else ""
                t.status_text = "Sırada"
                t.log(f"Eklendi: {t.url}")
                self.tasks[t.id] = t
                created.append(t)
        self._touch()
        self._schedule()
        return created

    def reserve_name(self, task: Task, out_dir: str, base: str) -> bool:
        """Aynı klasörde başka bir görev bu adı kullanmıyorsa adı bu göreve ayırır."""
        with self.lock:
            for x in self.tasks.values():
                if x is not task and x.base_name == base and os.path.normcase(x.out_dir) == os.path.normcase(out_dir):
                    return False
            task.base_name = base
            return True

    def work_dir(self, t: Task) -> str:
        return os.path.join(t.out_dir, f".kdm-{t.id}")

    def get(self, tid) -> Task | None:
        return self.tasks.get(tid)

    def pause(self, tid):
        t = self.tasks.get(tid)
        if not t:
            return
        with self.lock:
            if t.status == "running":
                t.stop_reason = "pause"
                t.cancel_event.set()
                t.status_text = "Duraklatılıyor…"
            elif t.status == "queued":
                t.status, t.status_text = "paused", "Duraklatıldı"
        self._touch()

    def resume(self, tid):
        t = self.tasks.get(tid)
        if not t:
            return
        with self.lock:
            if t.status in ("paused", "error", "canceled"):
                t.status, t.status_text, t.error = "queued", "Sırada", ""
                t.auto_retries = 0
        self._touch()
        self._schedule()

    def cancel(self, tid):
        t = self.tasks.get(tid)
        if not t:
            return
        with self.lock:
            if t.status == "running":
                t.stop_reason = "cancel"
                t.cancel_event.set()
            elif t.status in ("queued", "paused"):
                t.status, t.status_text = "canceled", "İptal edildi"
        self._touch()

    def remove(self, tid, delete_files=False):
        t = self.tasks.get(tid)
        if not t:
            return
        if t.status == "running":
            t.stop_reason = "remove"
            t.cancel_event.set()
            if t.thread:
                t.thread.join(10)
        with self.lock:
            self.tasks.pop(tid, None)
        if delete_files:
            self._delete_files(t)
        if t.cookiefile:
            Path(t.cookiefile).unlink(missing_ok=True)
        self._touch()

    def clear_finished(self):
        with self.lock:
            for tid in [k for k, t in self.tasks.items() if t.status == "completed"]:
                self.tasks.pop(tid)
        self._touch()

    def pause_all(self):
        for tid in list(self.tasks):
            self.pause(tid)

    def resume_all(self):
        with self.lock:
            for t in self.tasks.values():
                if t.status == "paused":
                    t.status, t.status_text = "queued", "Sırada"
        self._touch()
        self._schedule()

    # ------------------------------------------------------------ internals
    def _delete_files(self, t: Task):
        paths = set()
        if t.filepath:
            paths |= {t.filepath, t.filepath + ".part", t.filepath + ".kdm"}
        if t.base_name and t.out_dir:
            pat = os.path.join(glob.escape(t.out_dir), glob.escape(t.base_name) + ".*")
            for p in glob.glob(pat):
                name = os.path.basename(p)
                if (".part" in name or name.endswith(".ytdl") or re.search(r"\.f[\w-]+\.\w+$", name)
                        or name.endswith((".srt", ".vtt", ".ass", ".temp"))):
                    paths.add(p)
        for p in paths:
            try:
                Path(p).unlink(missing_ok=True)
            except OSError:
                pass
        if t.out_dir:
            shutil.rmtree(self.work_dir(t), ignore_errors=True)

    def _retryable(self, t: Task, msg: str) -> bool:
        if t.auto_retries >= AUTO_RETRIES:
            return False
        low = msg.lower()
        return not any(k in low for k in ("drm", "bulunamadı", "unsupported", "(401)", "ffmpeg gerekli",
                                           "no space", "disk"))

    def _auto_resume(self, t: Task):
        with self.lock:
            if self.tasks.get(t.id) is t and t.status == "paused" and t.status_text.startswith("Hata,"):
                t.status, t.status_text = "queued", "Sırada"
        self._touch()
        self._schedule()

    def _schedule(self):
        with self.lock:
            running = sum(1 for t in self.tasks.values() if t.status == "running")
            queued = sorted((t for t in self.tasks.values() if t.status == "queued"), key=lambda t: t.created)
            for t in queued:
                if running >= self.config["max_concurrent"]:
                    break
                t.status, t.status_text, t.error = "running", "Başlatılıyor…", ""
                t.cancel_event = threading.Event()
                t.stop_reason = ""
                t.thread = threading.Thread(target=self._run, args=(t,), daemon=True)
                t.thread.start()
                running += 1
        self._touch()

    def _run(self, t: Task):
        cfg = self.config
        o = t.opts

        unset = object()

        def on_progress(downloaded=None, total=None, speed=None, pct=unset):
            if downloaded is not None:
                t.downloaded = downloaded
            if total is not None:
                t.total = total
            if speed is not None:
                t.speed = speed
            if pct is not unset:
                t.progress_pct = pct
                t.speed = 0

        def on_info(**kw):
            for k, v in kw.items():
                setattr(t, k, v)
            self._touch()

        def on_status(text):
            t.status_text = text

        t.progress_pct = None
        eng = None
        try:
            if t.kind == "bbb":
                eng = BbbEngine(url=t.url, headers=o.get("headers"), cookiefile=t.cookiefile or None,
                                out_dir=t.out_dir, work_dir=self.work_dir(t), title=t.title or None,
                                filepath=t.filepath or None, mode=o.get("format") or "full",
                                connections=cfg["connections"], cancel_event=t.cancel_event,
                                on_progress=on_progress, on_info=on_info, on_status=on_status,
                                log=t.log, speed_limit=cfg["speed_limit_kb"])
            elif t.kind == "http":
                t.status_text = "İndiriliyor"
                eng = HttpEngine(url=t.url, headers=o.get("headers"), cookiefile=t.cookiefile or None,
                                 out_dir=t.out_dir, filename=t.title or None, filepath=t.filepath or None,
                                 connections=cfg["connections"], cancel_event=t.cancel_event,
                                 on_progress=on_progress, on_info=on_info,
                                 speed_limit=cfg["speed_limit_kb"], log=t.log)
            else:
                eng = YtdlpEngine(url=t.url, headers=o.get("headers"), cookiefile=t.cookiefile or None,
                                  cookies_from_browser="" if t.cookiefile else cfg["cookies_from_browser"],
                                  out_dir=t.out_dir, title=t.title or None, base_name=t.base_name or None,
                                  fmt=o.get("format"), sub_langs=o.get("sub_langs"),
                                  auto_sub_langs=o.get("auto_sub_langs"), sub_format=cfg["subtitle_format"],
                                  embed_subs=o.get("embed_subs"), connections=cfg["connections"],
                                  speed_limit=cfg["speed_limit_kb"], cancel_event=t.cancel_event,
                                  on_progress=on_progress, on_info=on_info, on_status=on_status, log=t.log,
                                  video_sel=o.get("video_sel") or None, audio_sel=o.get("audio_sel") or None,
                                  audio_only=o.get("audio_only"),
                                  reserve_name=lambda b: self.reserve_name(t, t.out_dir, b))
            path = eng.run()
            t.filepath = path
            t.filename = os.path.basename(path)

            if o.get("extra_subs"):
                t.status_text = "Altyazılar indiriliyor…"
                subs = download_extra_subtitles(path, o["extra_subs"], o.get("headers") or {},
                                                t.cookiefile or None, cfg["subtitle_format"], t.log)
                if subs and o.get("embed_subs"):
                    t.status_text = "Altyazılar gömülüyor…"
                    t.filepath = embed_subtitles(path, subs, t.log)
                    t.filename = os.path.basename(t.filepath)

            try:
                t.total = t.downloaded = os.path.getsize(t.filepath)
            except OSError:
                pass
            t.status, t.status_text, t.speed, t.progress_pct = "completed", "Tamamlandı", 0, None
            t.finished = time.time()
            t.auto_retries = 0
            skipped = getattr(eng, "skipped", 0)
            if skipped:
                t.status_text = f"Tamamlandı ({skipped} parça atlandı)"
                t.log(f"Uyarı: sunucu {skipped} parçayı vermedi; videoda birkaç saniyelik boşluk olabilir")
            t.log("Tamamlandı: " + t.filepath)
            if t.cookiefile:
                Path(t.cookiefile).unlink(missing_ok=True)
                t.cookiefile = ""
        except (Cancelled, DownloadCancelled):
            t.speed = 0
            if t.stop_reason == "pause":
                t.status, t.status_text = "paused", "Duraklatıldı"
            else:
                t.status, t.status_text = "canceled", "İptal edildi"
        except Exception as e:  # noqa: BLE001
            t.speed = 0
            if t.cancel_event.is_set():
                t.status = "paused" if t.stop_reason == "pause" else "canceled"
                t.status_text = "Duraklatıldı" if t.status == "paused" else "İptal edildi"
            else:
                msg = friendly_error(e)
                t.log("HATA: " + str(e))
                traceback.print_exc()
                if self._retryable(t, msg):
                    # geçici sunucu/ağ hatası: kaldığı yerden otomatik devam et
                    t.auto_retries += 1
                    wait = 10 * t.auto_retries
                    t.status, t.status_text = "paused", f"Hata, {wait} sn sonra yeniden denenecek ({t.auto_retries}/{AUTO_RETRIES})"
                    t.log(t.status_text)
                    threading.Timer(wait, self._auto_resume, args=(t,)).start()
                else:
                    t.status, t.status_text = "error", "Hata"
                    t.error = msg
        finally:
            self._touch()
            self._schedule()
