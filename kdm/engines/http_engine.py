"""IDM tarzı çok bağlantılı HTTP indirme motoru.

- Dosyayı parçalara böler ve her parçayı ayrı bağlantıyla indirir.
- Dinamik bölme: biten bağlantı, en çok işi kalan parçanın yarısını devralır.
- Devam ettirme (resume): durum .kdm dosyasında saklanır.
"""
import json
import mimetypes
import os
import threading
import time
from pathlib import Path

import requests

from ..utils import (SpeedMeter, filename_from_disposition, filename_from_url,
                     load_cookie_jar, sanitize_filename, unique_path)

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
CHUNK = 64 * 1024
MIN_SEGMENT = 512 * 1024
MIN_SPLIT = 2 * 1024 * 1024
MAX_RETRIES = 15


class Cancelled(Exception):
    pass


class HttpStatusError(IOError):
    pass


def make_session(headers: dict | None, cookiefile=None) -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = DEFAULT_UA
    s.headers.update(headers or {})
    jar = load_cookie_jar(cookiefile)
    if jar is not None:
        s.cookies = jar  # type: ignore[assignment]
    return s


def probe_http(url: str, headers: dict | None = None, cookiefile=None, session=None) -> dict:
    s = session or make_session(headers, cookiefile)
    r = s.get(url, headers={"Range": "bytes=0-0"}, stream=True, timeout=(15, 30), allow_redirects=True)
    try:
        r.raise_for_status()
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        size, resumable = 0, False
        if r.status_code == 206:
            cr = r.headers.get("Content-Range", "")
            if "/" in cr and cr.rsplit("/", 1)[1].strip().isdigit():
                size = int(cr.rsplit("/", 1)[1])
                resumable = True
        elif r.headers.get("Content-Length", "").isdigit():
            size = int(r.headers["Content-Length"])
        name = filename_from_disposition(r.headers.get("Content-Disposition", "")) or filename_from_url(r.url)
        if "." not in name and ctype:
            ext = mimetypes.guess_extension(ctype)
            if ext:
                name += ext
        return {"final_url": r.url, "size": size, "resumable": resumable,
                "content_type": ctype, "filename": name}
    finally:
        r.close()


class Segment:
    __slots__ = ("start", "end", "pos")

    def __init__(self, start: int, end: int, pos: int | None = None):
        self.start, self.end = start, end
        self.pos = start if pos is None else pos

    @property
    def remaining(self) -> int:
        return max(0, self.end - self.pos + 1)

    def to_list(self):
        return [self.start, self.end, self.pos]


class HttpEngine:
    def __init__(self, *, url, headers, cookiefile, out_dir, filename=None, filepath=None,
                 connections=8, cancel_event: threading.Event, on_progress, on_info,
                 speed_limit=0, log=print):
        self.url = url
        self.headers = headers or {}
        self.cookiefile = cookiefile
        self.out_dir = Path(out_dir)
        self.filename = filename
        self.filepath = Path(filepath) if filepath else None
        self.connections = max(1, connections)
        self.cancel = cancel_event
        self.on_progress = on_progress
        self.on_info = on_info
        self.speed_limit = speed_limit
        self.log = log
        self.lock = threading.Lock()
        self.downloaded = 0
        self.total = 0
        self.error: Exception | None = None
        self.meter = SpeedMeter()
        self._tb_start = time.monotonic()
        self._tb_bytes = 0

    # ------------------------------------------------------------------ public
    def run(self) -> str:
        session = make_session(self.headers, self.cookiefile)
        info = probe_http(self.url, session=session)
        self.url = info["final_url"]
        self.total = info["size"]
        if not self.filepath:
            name = sanitize_filename(self.filename) if self.filename else info["filename"]
            if "." not in name and "." in info["filename"]:
                name += "." + info["filename"].rsplit(".", 1)[1]
            self.out_dir.mkdir(parents=True, exist_ok=True)
            self.filepath = unique_path(self.out_dir / name)
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self.on_info(filename=self.filepath.name, filepath=str(self.filepath), total=self.total)

        part = Path(str(self.filepath) + ".part")
        state = Path(str(self.filepath) + ".kdm")
        if info["resumable"] and self.total > 0:
            self._segmented(part, state)
        else:
            self._single(session, part)
        os.replace(part, self.filepath)
        state.unlink(missing_ok=True)
        return str(self.filepath)

    # ----------------------------------------------------------------- helpers
    def _report(self):
        speed = self.meter.update(self.downloaded)
        self.on_progress(downloaded=self.downloaded, total=self.total, speed=speed)

    def _throttle(self, n: int):
        if not self.speed_limit:
            return
        limit = self.speed_limit * 1024
        with self.lock:
            now = time.monotonic()
            if now - self._tb_start > 5:
                self._tb_start, self._tb_bytes = now, 0
            self._tb_bytes += n
            delay = self._tb_bytes / limit - (now - self._tb_start)
        if delay > 0:
            time.sleep(min(delay, 2))

    # ------------------------------------------------------------- single conn
    def _single(self, session, part: Path):
        for attempt in range(1, 4):
            self.downloaded = 0
            try:
                with session.get(self.url, stream=True, timeout=(15, 60)) as r:
                    r.raise_for_status()
                    with open(part, "wb") as f:
                        last = 0.0
                        for chunk in r.iter_content(CHUNK):
                            if self.cancel.is_set():
                                raise Cancelled()
                            f.write(chunk)
                            self.downloaded += len(chunk)
                            self._throttle(len(chunk))
                            if time.monotonic() - last > 0.5:
                                last = time.monotonic()
                                self._report()
                if self.total and self.downloaded < self.total:
                    raise IOError("Bağlantı erken kapandı")
                self._report()
                return
            except Cancelled:
                raise
            except Exception as e:  # noqa: BLE001
                if attempt == 3:
                    raise
                self.log(f"Hata, yeniden deneniyor ({attempt}): {e}")
                time.sleep(2 * attempt)

    # ------------------------------------------------------------- segmented
    def _load_state(self, part: Path, state: Path):
        if not (part.exists() and state.exists()):
            return None
        try:
            data = json.loads(state.read_text("utf-8"))
            if data.get("size") != self.total or part.stat().st_size != self.total:
                return None
            return [Segment(*s) for s in data["segments"]]
        except Exception:
            return None

    def _save_state(self, state: Path, segs):
        with self.lock:
            data = {"url": self.url, "size": self.total, "segments": [s.to_list() for s in segs]}
        tmp = state.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), "utf-8")
        os.replace(tmp, state)

    def _segmented(self, part: Path, state: Path):
        segs = self._load_state(part, state)
        if segs is None:
            n = max(1, min(self.connections, self.total // MIN_SEGMENT))
            size = self.total // n
            segs = [Segment(i * size, (i + 1) * size - 1 if i < n - 1 else self.total - 1) for i in range(n)]
            with open(part, "wb") as f:
                f.truncate(self.total)
        else:
            self.log("Kaldığı yerden devam ediliyor")
        self.downloaded = sum(s.pos - s.start for s in segs)

        threads: dict[Segment, threading.Thread] = {}
        last_save = time.monotonic()

        def start(seg: Segment):
            t = threading.Thread(target=self._worker_wrap, args=(seg, part), daemon=True)
            threads[seg] = t
            t.start()

        while True:
            if self.error:
                self.cancel.set()
                for t in threads.values():
                    t.join(5)
                self._save_state(state, segs)
                raise self.error
            if self.cancel.is_set():
                for t in threads.values():
                    t.join(5)
                self._save_state(state, segs)
                raise Cancelled()
            for seg, t in list(threads.items()):
                if not t.is_alive():
                    del threads[seg]
            for seg in segs:
                if seg.remaining and seg not in threads and len(threads) < self.connections:
                    start(seg)
            while len(threads) < self.connections:
                new = self._split(segs, threads)
                if not new:
                    break
                segs.append(new)
                start(new)
            if not threads and all(s.remaining == 0 for s in segs):
                break
            self._report()
            if time.monotonic() - last_save > 2:
                self._save_state(state, segs)
                last_save = time.monotonic()
            time.sleep(0.3)
        self._report()

    def _split(self, segs, threads):
        with self.lock:
            busy = [s for s in segs if s in threads and s.remaining >= MIN_SPLIT]
            if not busy:
                return None
            big = max(busy, key=lambda s: s.remaining)
            mid = big.pos + big.remaining // 2
            new = Segment(mid, big.end)
            big.end = mid - 1
            return new

    def _worker_wrap(self, seg: Segment, part: Path):
        try:
            self._worker(seg, part)
        except Cancelled:
            pass
        except Exception as e:  # noqa: BLE001
            self.error = e

    def _worker(self, seg: Segment, part: Path):
        session = make_session(self.headers, self.cookiefile)
        attempts = 0
        with open(part, "r+b") as f:
            while seg.remaining and not self.cancel.is_set():
                with self.lock:
                    start, end = seg.pos, seg.end
                try:
                    with session.get(self.url, headers={"Range": f"bytes={start}-{end}"},
                                     stream=True, timeout=(15, 60)) as r:
                        if r.status_code != 206:
                            raise HttpStatusError(f"Sunucu parçalı indirmeyi reddetti (HTTP {r.status_code})")
                        for chunk in r.iter_content(CHUNK):
                            if self.cancel.is_set():
                                return
                            with self.lock:
                                allowed = seg.end - seg.pos + 1
                                if allowed <= 0:
                                    break
                                chunk = chunk[:allowed]
                                offset = seg.pos
                                seg.pos += len(chunk)
                                self.downloaded += len(chunk)
                            f.seek(offset)
                            f.write(chunk)
                            attempts = 0
                            self._throttle(len(chunk))
                except Exception as e:  # noqa: BLE001
                    if self.cancel.is_set():
                        return
                    attempts += 1
                    if attempts > MAX_RETRIES:
                        raise
                    if isinstance(e, HttpStatusError) and attempts > 3:
                        # 403/404 gibi: muhtemelen link süresi doldu
                        raise
                    time.sleep(min(2 ** attempts, 15))
