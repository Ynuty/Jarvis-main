@echo off
rem Запуск J.A.R.V.I.S. из исходников (режим разработки).
rem Данные профиля — в папке .devhome рядом (там уже скачаны модели).
cd /d "%~dp0shell"
set ELECTRON_RUN_AS_NODE=
set JARVIS_DEV=1
set JARVIS_HOME=%~dp0.devhome
start "" "%~dp0shell\node_modules\electron\dist\electron.exe" .
