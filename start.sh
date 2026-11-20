#!/usr/bin/env bash
# KDM - macOS / Linux başlatıcı
set -e
cd "$(dirname "$0")"

find_python() {
  for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$c" >/dev/null 2>&1 &&
       "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      echo "$c"; return 0
    fi
  done
  for c in /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    if [ -x "$c" ] && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
      echo "$c"; return 0
    fi
  done
  return 1
}

if [ ! -x .venv/bin/python ]; then
  PY="$(find_python)" || {
    echo "[KDM] HATA: Python 3.10 veya daha yenisi bulunamadı."
    echo "      macOS:  brew install python      Linux: sudo apt install python3 python3-venv"
    exit 1
  }
  echo "[KDM] İlk kurulum yapılıyor ($("$PY" --version))..."
  "$PY" -m venv .venv
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/python -m pip install -r requirements.txt
  cp requirements.txt .venv/kdm.stamp
elif ! cmp -s requirements.txt .venv/kdm.stamp; then
  echo "[KDM] Bağımlılıklar güncelleniyor..."
  .venv/bin/python -m pip install -r requirements.txt
  cp requirements.txt .venv/kdm.stamp
fi

command -v ffmpeg >/dev/null 2>&1 || [ -x /opt/homebrew/bin/ffmpeg ] || [ -x /usr/local/bin/ffmpeg ] ||
  echo "[KDM] UYARI: ffmpeg yok. macOS: brew install ffmpeg   Linux: sudo apt install ffmpeg"

exec .venv/bin/python run.py "$@"
