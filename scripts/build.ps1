# Сборка установщика Windows: интерфейс → ядро (PyInstaller, без CUDA) → Electron NSIS.
# Результат: dist\JARVIS Setup <версия>.exe   Запуск: powershell -File scripts\build.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue

Push-Location "$root\app";  npm run build;  Pop-Location
Push-Location $root
& core\.venv\Scripts\pyinstaller --noconfirm --clean --distpath build --workpath build\pyi scripts\jarvis-core.spec
Pop-Location
Push-Location "$root\shell"; npx electron-builder --win nsis; Pop-Location

Get-ChildItem "$root\dist\*.exe" | Select-Object Name, @{n="МБ"; e={[math]::Round($_.Length / 1MB)}}
