#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 NSIS portable 外壳 exe 注入图标，且保留尾部 payload(overlay)。

背景（重要踩坑）：
  electron-builder 的 portable 目标产物 = NSIS 自解压 stub(PE) + 尾部 payload(overlay)。
  直接对最终 exe 跑 rcedit --set-icon 会重写 PE 并把 overlay 全部丢掉，
  exe 从 ~66MB 缩水到 ~400KB，程序再也无法自解压运行。

用法：
  python scripts/inject_icon_keep_overlay.py <exe> <icon.ico> [--rcedit PATH]

步骤：
  1) 记录 exe 的 overlay 起点（最后节末尾 = PE 主体结束处）与其字节。
  2) 复制一份 PE 主体（不含 overlay）到临时文件，用 rcedit 给它注入图标。
  3) 校验注入后的临时文件仍是合法 PE（节数一致）。
  4) 把原 overlay 原样拼回注入后的 PE 主体，写回目标 exe。
  5) 校验最终文件 overlay 与原始逐字节一致。
"""
import hashlib
import os
import shutil
import struct
import subprocess
import sys
import tempfile


def pe_info(d):
    """返回 (pe_off, 节表偏移, [(va, raw_off, raw_size)...], 最后节末尾)。"""
    pe = struct.unpack_from('<I', d, 0x3c)[0]
    if d[pe:pe+4] != b'PE\x00\x00':
        raise ValueError('不是合法 PE 文件')
    nsec = struct.unpack_from('<H', d, pe + 6)[0]
    sizeopt = struct.unpack_from('<H', d, pe + 20)[0]
    opt = pe + 24
    sec_table = opt + sizeopt
    secs = []
    max_end = 0
    for i in range(nsec):
        o = sec_table + i * 40
        vsize, vaddr, rsize, raddr = struct.unpack_from('<IIII', d, o + 8)
        end = raddr + rsize
        max_end = max(max_end, end)
        secs.append((vaddr, raddr, rsize))
    return pe, sec_table, secs, max_end


def find_rcedit(explicit=None):
    if explicit and os.path.exists(explicit):
        return explicit
    roots = [
        os.environ.get('ELECTRON_BUILDER_CACHE'),
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'electron-builder', 'Cache'),
        os.path.join(os.path.expanduser('~'), '.cache', 'electron-builder'),
    ]
    for root in filter(None, roots):
        sign = os.path.join(root, 'winCodeSign')
        if not os.path.isdir(sign):
            continue
        for name in sorted(os.listdir(sign)):
            for exe in ('rcedit-x64.exe', 'rcedit-ia32.exe'):
                p = os.path.join(sign, name, exe)
                if os.path.exists(p):
                    return p
    return None


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    exe = os.path.abspath(sys.argv[1])
    icon = os.path.abspath(sys.argv[2])
    rcedit = None
    if '--rcedit' in sys.argv:
        rcedit = sys.argv[sys.argv.index('--rcedit') + 1]

    raw = open(exe, 'rb').read()
    pe, sec_table, secs, overlay_off = pe_info(raw)
    overlay = raw[overlay_off:]
    print('原 exe: %d 字节, PE 主体=%d, overlay=%d' % (len(raw), overlay_off, len(overlay)))
    if len(overlay) == 0:
        print('⚠️ 没有 overlay（可能已经被 rcedit 破坏过），中止')
        return 2

    rc = find_rcedit(rcedit)
    if not rc:
        print('找不到 rcedit')
        return 3

    tmp_dir = tempfile.mkdtemp(prefix='mshell-icon-')
    try:
        # 只把 PE 主体写到临时文件，让 rcedit 注入图标（此时没有 overlay 可丢）
        body_tmp = os.path.join(tmp_dir, 'body.exe')
        with open(body_tmp, 'wb') as f:
            f.write(raw[:overlay_off])

        r = subprocess.run([rc, body_tmp, '--set-icon', icon], capture_output=True, text=True)
        if r.returncode != 0:
            print('rcedit 注入失败:', (r.stderr or r.stdout or '')[:200])
            return 4

        body_new = open(body_tmp, 'rb').read()
        # 校验注入后仍是合法 PE 且节数一致
        _, _, secs_new, _ = pe_info(body_new)
        if len(secs_new) != len(secs):
            print('⚠️ 注入后节数变化 %d -> %d，中止以免破坏结构' % (len(secs), len(secs_new)))
            return 5
        print('rcedit 注入完成: PE 主体 %d -> %d 字节' % (overlay_off, len(body_new)))

        # 拼回 overlay
        final = body_new + overlay
        backup = exe + '.bak-iconfix'
        if not os.path.exists(backup):
            shutil.copy2(exe, backup)
            print('已备份原文件:', backup)
        with open(exe, 'wb') as f:
            f.write(final)

        # 校验最终文件
        _, _, _, final_overlay_off = pe_info(final)
        final_overlay = final[final_overlay_off:]
        ok = (len(final_overlay) == len(overlay) and
              hashlib.md5(final_overlay).hexdigest() == hashlib.md5(overlay).hexdigest())
        print('最终 exe: %d 字节, overlay %d 字节, payload 完整性: %s' %
              (len(final), len(final_overlay), 'OK' if ok else '❌ 不一致'))
        return 0 if ok else 6
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
