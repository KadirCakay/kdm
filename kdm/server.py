"""Yerel HTTP sunucusu: web arayüzü + tarayıcı eklentisi için API (yalnızca 127.0.0.1)."""
import asyncio
import time
import uuid
from pathlib import Path

from aiohttp import web

from . import APP_NAME, __version__
from .config import COOKIE_DIR, Config
from .engines.bbb_engine import detect_bbb, probe_bbb
from .engines.http_engine import make_session, probe_http
from .engines.ytdlp_engine import friendly_error, probe_media
from .manager import Manager
from .utils import (DIRECT_EXTS, MANIFEST_EXTS, clean_headers, ffmpeg_path, open_in_file_manager,
                    url_ext, write_cookie_file)

STATIC = Path(__file__).parent / "static"
CAPTURE_TTL = 3600


def do_probe(payload: dict, config: Config) -> dict:
    url = (payload.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("Geçerli bir http(s) adresi girin.")
    headers = clean_headers(payload.get("headers"))
    hint = payload.get("type") or ""
    cookiefile = None
    if payload.get("cookies"):
        cookiefile = write_cookie_file(payload["cookies"], COOKIE_DIR / f"probe_{uuid.uuid4().hex}.txt")
    cfb = "" if cookiefile else config["cookies_from_browser"]
    try:
        bbb = detect_bbb(url) or detect_bbb(payload.get("page_url") or "")
        if bbb:
            return probe_bbb(bbb, headers, cookiefile)
        ext = url_ext(url)

        def media():
            return probe_media(url, headers, cookiefile, cfb)

        def direct(info=None):
            info = info or probe_http(url, headers, cookiefile)
            return {"kind": "http", "title": info["filename"], "filename": info["filename"],
                    "size": info["size"], "resumable": info["resumable"],
                    "content_type": info["content_type"], "qualities": [], "subtitles": []}

        if ext in MANIFEST_EXTS or hint in ("hls", "dash"):
            return media()
        if ext in DIRECT_EXTS or hint == "file":
            try:
                return direct()
            except Exception:
                return media()
        try:
            info = probe_http(url, headers, cookiefile)
        except Exception:
            return media()
        ct = info["content_type"]
        if "html" in ct or "mpegurl" in ct or "dash+xml" in ct or "xml" in ct or not ct:
            return media()
        return direct(info)
    finally:
        if cookiefile:
            Path(cookiefile).unlink(missing_ok=True)


def inspect_hls(payload: dict) -> dict:
    """m3u8 içeriğine bakıp ana liste mi, alt liste mi, altyazı mı olduğunu söyler."""
    url = payload.get("url") or ""
    cookiefile = None
    if payload.get("cookies"):
        cookiefile = write_cookie_file(payload["cookies"], COOKIE_DIR / f"insp_{uuid.uuid4().hex}.txt")
    try:
        s = make_session(clean_headers(payload.get("headers")), cookiefile)
        r = s.get(url, timeout=(10, 20))
        r.raise_for_status()
        txt = r.text[:200000]
    finally:
        if cookiefile:
            Path(cookiefile).unlink(missing_ok=True)
    if "#EXT-X-STREAM-INF" in txt:
        import re
        heights = sorted({int(h) for h in re.findall(r"RESOLUTION=\d+x(\d+)", txt)}, reverse=True)
        media_lines = [ln for ln in txt.splitlines() if ln.startswith("#EXT-X-MEDIA:")]
        audios = sum("TYPE=AUDIO" in ln for ln in media_lines)
        subs = sum("TYPE=SUBTITLES" in ln for ln in media_lines)
        return {"kind": "master", "heights": heights, "audios": audios, "subs": subs}
    segs = [ln for ln in txt.splitlines() if ln and not ln.startswith("#")]
    if segs and all(x.split("?")[0].lower().endswith((".vtt", ".webvtt", ".srt")) for x in segs[:5]):
        return {"kind": "subtitle"}
    if segs and all(x.split("?")[0].lower().endswith((".aac", ".m4a", ".mp3")) for x in segs[:5]):
        return {"kind": "audio"}
    return {"kind": "media"}


def create_app(config: Config) -> web.Application:
    manager = Manager(config)
    captures: dict[str, tuple[float, dict]] = {}
    port = config["port"]
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    allowed_origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    @web.middleware
    async def guard(request: web.Request, handler):
        # DNS rebinding ve başka sitelerin yerel API'ye istek atmasını engelle
        if request.host not in allowed_hosts:
            return web.json_response({"error": "forbidden host"}, status=403)
        origin = request.headers.get("Origin")
        if origin and origin not in allowed_origins and not origin.startswith(
                ("chrome-extension://", "moz-extension://", "safari-web-extension://")):
            return web.json_response({"error": "forbidden origin"}, status=403)
        try:
            resp = await handler(request)
            resp.headers["Cache-Control"] = "no-cache"
            return resp
        except web.HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            return web.json_response({"error": friendly_error(e)}, status=400)

    app = web.Application(middlewares=[guard], client_max_size=20 * 1024 * 1024)
    r = app.router

    async def index(_):
        return web.FileResponse(STATIC / "index.html")

    async def add_page(_):
        return web.FileResponse(STATIC / "add.html")

    async def ping(_):
        return web.json_response({"app": APP_NAME, "version": __version__})

    async def info(_):
        return web.json_response({"app": APP_NAME, "version": __version__,
                                  "ffmpeg": bool(ffmpeg_path()), "settings": config.data})

    async def list_tasks(_):
        return web.json_response(manager.list_tasks())

    async def add_tasks(request):
        p = await request.json()
        if not p.get("url") and not p.get("entries"):
            raise ValueError("URL gerekli")
        tasks = manager.add(p)
        return web.json_response({"ids": [t.id for t in tasks], "duplicate": not tasks})

    async def batch_add(request):
        p = await request.json()
        urls = [u.strip() for u in (p.get("urls") or "").splitlines() if u.strip().startswith("http")]
        ids = []
        for u in urls:
            kind = "http" if url_ext(u) in DIRECT_EXTS else "media"
            ids += [t.id for t in manager.add({"url": u, "kind": kind, "format": p.get("format"),
                                                "out_dir": p.get("out_dir"),
                                                "sub_langs": p.get("sub_langs") or []})]
        return web.json_response({"ids": ids})

    async def task_action(request):
        tid, action = request.match_info["tid"], request.match_info["action"]
        t = manager.get(tid)
        if not t:
            raise web.HTTPNotFound()
        if action == "pause":
            manager.pause(tid)
        elif action in ("resume", "retry"):
            manager.resume(tid)
        elif action == "cancel":
            manager.cancel(tid)
        elif action == "open":
            open_in_file_manager(t.filepath or t.out_dir)
        elif action == "log":
            return web.json_response({"logs": t.logs})
        else:
            raise web.HTTPNotFound()
        return web.json_response({"ok": True})

    async def delete_task(request):
        delete_files = request.query.get("files") == "1"
        await asyncio.get_running_loop().run_in_executor(
            None, manager.remove, request.match_info["tid"], delete_files)
        return web.json_response({"ok": True})

    async def bulk(request):
        action = request.match_info["action"]
        if action == "pause_all":
            manager.pause_all()
        elif action == "resume_all":
            manager.resume_all()
        elif action == "clear_finished":
            manager.clear_finished()
        elif action == "open_folder":
            open_in_file_manager(config["download_dir"])
        return web.json_response({"ok": True})

    async def probe(request):
        p = await request.json()
        res = await asyncio.get_running_loop().run_in_executor(None, do_probe, p, config)
        return web.json_response(res)

    async def inspect(request):
        p = await request.json()
        try:
            res = await asyncio.get_running_loop().run_in_executor(None, inspect_hls, p)
        except Exception:
            res = {"kind": "unknown"}
        return web.json_response(res)

    async def capture(request):
        p = await request.json()
        now = time.time()
        for k in [k for k, (ts, _) in captures.items() if now - ts > CAPTURE_TTL]:
            captures.pop(k)
        cid = uuid.uuid4().hex
        captures[cid] = (now, p)
        return web.json_response({"id": cid, "url": f"http://127.0.0.1:{port}/add?capture={cid}"})

    async def get_capture(request):
        item = captures.get(request.match_info["cid"])
        if not item:
            raise web.HTTPNotFound()
        return web.json_response(item[1])

    async def settings(request):
        if request.method == "POST":
            config.update(await request.json())
            manager._schedule()
        return web.json_response(config.data)

    r.add_get("/", index)
    r.add_get("/add", add_page)
    r.add_get("/api/ping", ping)
    r.add_get("/api/info", info)
    r.add_get("/api/tasks", list_tasks)
    r.add_post("/api/tasks", add_tasks)
    r.add_post("/api/batch", batch_add)
    r.add_post("/api/tasks/{tid}/{action}", task_action)
    r.add_get("/api/tasks/{tid}/{action}", task_action)
    r.add_delete("/api/tasks/{tid}", delete_task)
    r.add_post("/api/bulk/{action}", bulk)
    r.add_post("/api/probe", probe)
    r.add_post("/api/capture", capture)
    r.add_post("/api/inspect", inspect)
    r.add_get("/api/capture/{cid}", get_capture)
    r.add_route("*", "/api/settings", settings)
    r.add_static("/static", STATIC)

    async def on_shutdown(_):
        manager.pause_all()
        manager.save()

    app.on_shutdown.append(on_shutdown)
    return app
