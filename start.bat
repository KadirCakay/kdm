@echo off
rem KDM - Windows baslatici
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [KDM] Ilk kurulum yapiliyor...
  py -3 -m venv .venv 2>nul || python -m venv .venv
  if not exist ".venv\Scripts\python.exe" (
    echo [KDM] HATA: Python 3.10+ bulunamadi. https://www.python.org/downloads/ adresinden kurun
    echo       ve kurulumda "Add python.exe to PATH" kutusunu isaretleyin.
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  copy /y requirements.txt .venv\kdm.stamp >nul
) else (
  fc /b requirements.txt .venv\kdm.stamp >nul 2>&1 || (
    echo [KDM] Bagimliliklar guncelleniyor...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    copy /y requirements.txt .venv\kdm.stamp >nul
  )
)
".venv\Scripts\python.exe" run.py %*
pause
