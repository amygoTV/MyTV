@echo off
setlocal
set ELECTRON_RUN_AS_NODE=
set NODE_OPTIONS=
cd /d "%~dp0"
echo [1/3] Preparing stage...
if exist _stage rmdir /s /q _stage
mkdir _stage
rem 注意：package.json 不从源码复制 —— 源码那份含 dependencies.electron，
rem electron-builder 会拒绝打包。这里用 package.build.json（精简 + 版本号固定）。
for %%f in (app.js index.html main.js preload.js style.css) do copy /y "%%f" "_stage\%%f" >nul
copy /y "package.build.json" "_stage\package.json" >nul
xcopy /e /i /y config "_stage\config" >nul
xcopy /e /i /y vendor "_stage\vendor" >nul
if exist "build\icon.png" copy /y "build\icon.png" "_stage\icon.png" >nul
echo [2/3] Packing app.asar...
call "%~dp0node_modules\.bin\asar.cmd" pack _stage "..\MediaShellApp\resources\app.asar"
echo [3/3] Done. Output: ..\MediaShellApp\resources\app.asar
endlocal
