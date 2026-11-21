@echo off
setlocal
set ELECTRON_RUN_AS_NODE=
set NODE_OPTIONS=
cd /d "%~dp0"
start "" "%~dp0electron.exe"
endlocal
