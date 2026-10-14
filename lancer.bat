@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Installation initiale de Fusion PDF...
  py -m venv .venv
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 (
    echo L'installation a echoue. Verifiez votre connexion Internet.
    pause
    exit /b 1
  )
)
start "" ".venv\Scripts\pythonw.exe" app.py
endlocal
