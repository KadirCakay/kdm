import json
import os
import threading
from pathlib import Path

DATA_DIR = Path(os.environ.get("KDM_DATA_DIR") or (Path.home() / ".kdm"))
COOKIE_DIR = DATA_DIR / "cookies"
CONFIG_FILE = DATA_DIR / "config.json"
TASKS_FILE = DATA_DIR / "tasks.json"

DEFAULTS = {
    "download_dir": str(Path.home() / "Downloads" / "KDM"),
    "max_concurrent": 3,          # aynı anda kaç indirme
    "connections": 8,             # dosya başına bağlantı / paralel parça
    "port": 9614,
    "subtitle_format": "srt",     # srt | vtt | original
    "embed_subtitles": False,     # altyazıyı videonun içine göm (mkv)
    "cookies_from_browser": "",   # elle eklenen URL'ler için: chrome, firefox, edge, brave...
    "speed_limit_kb": 0,          # 0 = sınırsız (KB/s, indirme başına)
}


class Config:
    def __init__(self):
        self._lock = threading.Lock()
        self.data = dict(DEFAULTS)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        COOKIE_DIR.mkdir(parents=True, exist_ok=True)
        if CONFIG_FILE.exists():
            try:
                self.data.update(json.loads(CONFIG_FILE.read_text("utf-8")))
            except Exception:
                pass
        self.save()

    def __getitem__(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def update(self, values: dict):
        with self._lock:
            for k, v in values.items():
                if k not in DEFAULTS:
                    continue
                default = DEFAULTS[k]
                if isinstance(default, bool):
                    v = bool(v)
                elif isinstance(default, int):
                    v = int(v)
                else:
                    v = str(v)
                self.data[k] = v
            self.data["max_concurrent"] = max(1, min(16, self.data["max_concurrent"]))
            self.data["connections"] = max(1, min(32, self.data["connections"]))
        self.save()

    def save(self):
        with self._lock:
            CONFIG_FILE.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), "utf-8")
