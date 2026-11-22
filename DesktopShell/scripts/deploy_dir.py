#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""目录版部署脚本：把 win-unpacked 部署到指定目录，并把主程序改名 + 注入图标。

electron-builder 的目录版产物里主程序叫 electron.exe（带 Electron 默认图标）。
用户期望看到的是「影视舱 MediaShell」自己的图标，所以这里：
  1) electron.exe → MediaShell.exe
  2) 用本机缓存的 rcedit 给 MediaShell.exe 注入 build/icon.ico
  3) resources/app.asar 一并复制
  4) 生成 Start MediaShell.bat（纯 ASCII + CRLF）

用法：python scripts/deploy_dir.py <目标目录> <win-unpacked 目录>
"""
import os
import shutil
import struct
import subprocess
import sys

FF = r'C:\Users\1\AppData\Local\FluxDown\bin\ffmpeg.exe'   # 仅用于占位，实际不用
CACHE = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'electron-builder', 'Cache', 'winCodeSign')


def find_rcedit():
    if not os.path.isdir(CACHE):
        return None
    for name in sorted(os.listdir(CACHE)):
        for exe in ('rcedit-x64.exe', 'rcedit-ia32.exe'):
            p = os.path.join(CACHE, name, exe)
            if os.path.exists(p):
                return p
    return None


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    dest = sys.argv[1]
    src = sys.argv[2]
    icon = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'build', 'icon.ico')

    os.makedirs(dest, exist_ok=True)
    # 复制除主程序外的所有文件
    for name in os.listdir(src):
        s = os.path.join(src, name)
        d = os.path.join(dest, name)
        if name.lower() == 'electron.exe':
            continue
        if os.path.isdir(s):
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)

    # 主程序改名 + 注入图标
    old = os.path.join(dest, 'electron.exe')
    new = os.path.join(dest, 'MediaShell.exe')
    if os.path.exists(old):
        if os.path.exists(new):
            os.remove(new)
        os.rename(old, new)

    rcedit = find_rcedit()
    if rcedit and os.path.exists(icon) and os.path.exists(new):
        r = subprocess.run([rcedit, new, '--set-icon', icon],
                           capture_output=True, text=True)
        print('  rcedit:', 'OK' if r.returncode == 0 else (r.stderr or '')[:160])
    else:
        print('  跳过图标注入:', 'rcedit 未找到' if not rcedit else 'icon.ico 缺失')

    # 启动脚本（纯 ASCII + CRLF）
    bat = os.path.join(dest, 'Start MediaShell.bat')
    with open(bat, 'wb') as f:
        f.write(b'@echo off\r\nsetlocal\r\nset ELECTRON_RUN_AS_NODE=\r\nset NODE_OPTIONS=\r\n'
                b'cd /d "%~dp0"\r\nstart "" "%~dp0MediaShell.exe"\r\nendlocal\r\n')
    print('  启动脚本:', bat)
    print('  主程序:', new, os.path.getsize(new), 'bytes')
    return 0


if __name__ == '__main__':
    sys.exit(main())
