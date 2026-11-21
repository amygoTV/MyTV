@echo off
setlocal
set ELECTRON_RUN_AS_NODE=
set NODE_OPTIONS=
cd /d "%~dp0"
echo [1/3] Preparing stage...
if exist _stage rmdir /s /q _stage
mkdir _stage
for %%f in (app.js index.html main.js preload.js style.css package.json) do copy /y "%%f" "_stage\%%f" >nul
xcopy /e /i /y config "_stage\config" >nul
xcopy /e /i /y vendor "_stage\vendor" >nul
echo [2/3] Packing app.asar...
call "%~dp0node_modules\.bin\asar.cmd" pack _stage "..\MediaShellApp\resources\app.asar"
echo [3/3] Done. Output: ..\MediaShellApp\resources\app.asar
endlocal
