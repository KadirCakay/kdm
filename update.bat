@echo off
rem KDM - guncelleme (Windows): kodu GitHub dan ceker, yt-dlp ve diger paketleri gunceller
cd /d "%~dp0"
if exist ".git" (
  echo [KDM] Kod guncelleniyor...
  git pull --ff-only
)
if exist ".venv\Scripts\python.exe" (
  echo [KDM] Paketler guncelleniyor ^(yt-dlp dahil^)...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install --upgrade -r requirements.txt
  copy /y requirements.txt .venv\kdm.stamp >nul
) else (
  echo [KDM] Henuz kurulum yapilmamis; once start.bat calistirin.
)
echo [KDM] Tamam. KDM aciksa kapatip yeniden baslatin; eklenti degistiyse tarayicida eklentiyi yenileyin.
pause
