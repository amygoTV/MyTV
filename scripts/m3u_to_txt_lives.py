#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把所有 TVBox 配置 lives 字段里的自有直播源从 .m3u 换成 .txt。

用户需求（v1.6.46）：线路里的直播源都用 txt 那个格式的。

映射规则（只改自有产物，不动第三方源）：
    TVLives_v2.m3u      -> TVLives_v2.txt
    TVLivesBackup.m3u   -> TVLivesBackup.txt
    TVLives.m3u         -> TVLives.txt
    BiliLive_v2.m3u     -> BiliLive_v2.txt
    BiliLive.m3u        -> BiliLive.txt
    LiveSports_v2.m3u   -> LiveSports_v2.txt
    LiveSports.m3u      -> LiveSports.txt
第三方源（sub.ottiptv.cc 的虎牙/斗鱼/歪歪等）保持不变。

字符级替换（只动 URL 里的文件名），保持各文件原缩进与换行风格。
"""
import json
import os
import re
from pathlib import Path

# 自有直播产物：m3u 文件名 -> txt 文件名
MAP = {
    'TVLives_v2.m3u': 'TVLives_v2.txt',
    'TVLivesBackup.m3u': 'TVLivesBackup.txt',
    'TVLives.m3u': 'TVLives.txt',
    'BiliLive_v2.m3u': 'BiliLive_v2.txt',
    'BiliLive.m3u': 'BiliLive.txt',
    'LiveSports_v2.m3u': 'LiveSports_v2.txt',
    'LiveSports.m3u': 'LiveSports.txt',
}

# 需要处理的配置文件（lives 里带自有直播源的）
FILES = [
    'YSCv3/YSCSites.json',
    'YSCv3/YSCSites_v2.json',
    'YSCSites.json',
    'YSCv2/YSCSites.json',
    'TVBoxDesktop.json',
    'fty/api.json',
    'feimao/api.json',
    'xiaomi/api.json',
    'moyuer/api.json',
    'niaoshu/tongyong.json',
    'PG/api.json',
    'DesktopShell/config/YSCSites.json',
    'DesktopShell/config/TVBoxDesktop.json',
    'DesktopShell/seed/subscription.json',
]

# 点播/教育类配置里的 lives 也统一替换
for base in ('YSCv3', 'YSCv2', 'YSC'):
    d = Path(base)
    if not d.is_dir():
        continue
    for p in sorted(d.glob('*.json')):
        if p.name in ('YSCSites.json', 'YSCSites_v2.json'):
            continue
        FILES.append(str(p).replace('\\', '/'))


def replace_in_text(raw):
    """字符级替换 URL 中的 m3u 文件名 -> txt。返回 (新文本, 替换次数)。"""
    n = 0
    for m3u, txt in MAP.items():
        # 只替换出现在 URL 路径里的文件名（前面有 / 或 " 开头）
        pattern = re.compile(r'(?<=/)' + re.escape(m3u) + r'(?=["\s])')
        raw, c = pattern.subn(txt, raw)
        n += c
    return raw, n


def main():
    total_files = 0
    total_hits = 0
    missing = []
    for f in FILES:
        p = Path(f)
        if not p.exists():
            missing.append(f)
            continue
        raw = p.read_text('utf-8')
        new, n = replace_in_text(raw)
        if n == 0:
            continue
        # 严格 JSON 校验
        try:
            d = json.loads(new)
        except Exception as e:
            print('  !! %s 替换后 JSON 非法: %s' % (f, e))
            continue
        # 校验 lives 里已无自有 m3u 引用
        leftover = []
        for l in d.get('lives', []) or []:
            u = str(l.get('url', ''))
            for m3u in MAP:
                if m3u in u:
                    leftover.append(u)
        if leftover:
            print('  !! %s 仍有 m3u 残留: %s' % (f, leftover[:3]))
            continue
        p.write_text(new, 'utf-8')
        total_files += 1
        total_hits += n
        print('  %-42s 替换 %d 处' % (f, n))

    if missing:
        print('跳过（不存在）: %s' % ', '.join(missing))
    print('完成：%d 个文件，%d 处替换' % (total_files, total_hits))


if __name__ == '__main__':
    main()
