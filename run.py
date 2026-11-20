#!/usr/bin/env python3
"""KDM'yi başlatır:  python run.py  [--no-browser] [--port 9614]"""
import argparse
import socket
import sys
import threading
import webbrowser

from aiohttp import web

from kdm import APP_NAME, __version__
from kdm.config import DATA_DIR, Config
from kdm.server import create_app
from kdm.utils import ffmpeg_path


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def main():
    ap = argparse.ArgumentParser(description=f"{APP_NAME} - Kişisel İndirme Yöneticisi")
    ap.add_argument("--no-browser", action="store_true", help="Arayüzü tarayıcıda otomatik açma")
    ap.add_argument("--port", type=int, help="Port (varsayılan 9614; eklentide de aynı port olmalı)")
    args = ap.parse_args()

    config = Config()
    if args.port:
        config.update({"port": args.port})
    port = config["port"]
    url = f"http://127.0.0.1:{port}/"

    if port_in_use(port):
        print(f"{APP_NAME} zaten çalışıyor gibi görünüyor: {url}")
        if not args.no_browser:
            webbrowser.open(url)
        sys.exit(0)

    print(f"{APP_NAME} {__version__}  ->  {url}")
    print(f"Veri klasörü: {DATA_DIR}")
    print(f"İndirme klasörü: {config['download_dir']}")
    if not ffmpeg_path():
        print("UYARI: ffmpeg bulunamadı! Akış (HLS/DASH) birleştirme ve altyazı dönüştürme için gerekli.")
    print("Kapatmak için Ctrl+C")

    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    web.run_app(create_app(config), host="127.0.0.1", port=port, print=None)


if __name__ == "__main__":
    main()
