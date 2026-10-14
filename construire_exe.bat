@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
  echo L'installation des outils de compilation a echoue.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean FusionPDF-Editeur.spec
if errorlevel 1 (
  echo La compilation a echoue.
  pause
  exit /b 1
)
powershell -NoProfile -Command "if (Test-Path 'dist\FusionPDF-Editeur-sans-installation.zip') { Remove-Item 'dist\FusionPDF-Editeur-sans-installation.zip' -Force }; Compress-Archive -Path 'dist\FusionPDF-Editeur' -DestinationPath 'dist\FusionPDF-Editeur-sans-installation.zip' -CompressionLevel Optimal"
if errorlevel 1 (
  echo La creation de l'archive a echoue.
  pause
  exit /b 1
)
echo.
echo Version recommandee creee : dist\FusionPDF-Editeur-sans-installation.zip
echo Executable : dist\FusionPDF-Editeur\FusionPDF-Editeur.exe
pause
endlocal
