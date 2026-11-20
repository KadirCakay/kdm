#!/usr/bin/env bash
# KDM - güncelleme (macOS / Linux): kodu GitHub'dan çeker, yt-dlp ve diğer paketleri günceller
set -e
cd "$(dirname "$0")"
if [ -d .git ]; then
  echo "[KDM] Kod güncelleniyor..."
  git pull --ff-only
fi
if [ -x .venv/bin/python ]; then
  echo "[KDM] Paketler güncelleniyor (yt-dlp dahil)..."
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/python -m pip install --upgrade -r requirements.txt
  cp requirements.txt .venv/kdm.stamp
else
  echo "[KDM] Henüz kurulum yapılmamış; önce ./start.sh çalıştırın."
fi
echo "[KDM] Tamam. KDM açıksa kapatıp yeniden başlatın; eklenti değiştiyse tarayıcıda eklentiyi yenileyin."
