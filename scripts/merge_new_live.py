#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把已核验的 FHD 候选并入 channel_plan.json / movie_channels.json。

- 只并入 GOOD 清单（实测1920x1080 + 台标正确 + 无广告 + 不重复）
- 字符级操作：在对应频道 ipv4 数组头部整块插入，保持 JSON 其余格式/换行
- CCTV2：两条 FHD 插到最前，原 720p/SD 源自动后移
- 幂等：已存在的 URL 跳过
"""
import json
import re
from pathlib import Path

# 人工核验通过的 FHD 线路（编号 -> 频道名），来自看台标结论
GOOD = {
    '008': '内蒙古卫视', '017': '四川卫视', '019': '天津卫视', '020': '天津卫视',
    '021': '天津卫视', '023': '安徽卫视', '025': '山东卫视', '027': '山西卫视',
    '029': '广东卫视', '034': '江苏卫视', '040': '江西卫视', '042': '河北卫视',
    '043': '浙江卫视', '044': '浙江卫视', '051': '湖北卫视', '052': '湖北卫视',
    '054': '湖南卫视', '055': '湖南卫视', '060': '贵州卫视', '062': '陕西卫视',
    '071': 'CCTV10', '073': 'CCTV12', '084': 'CCTV17', '086': 'CCTV2',
    '087': 'CCTV2', '089': 'CCTV4', '094': 'CCTV7',
    '097': 'CHC动作电影', '098': 'CHC动作电影', '099': 'CHC动作电影',
    '100': 'CHC家庭影院', '101': 'CHC家庭影院',
    '103': '凤凰中文', '105': '凤凰资讯',
}
MOVIE_NAMES = {'CHC动作电影', 'CHC家庭影院'}

PLAN = Path('scripts/channel_plan.json')
MOVIE = Path('scripts/movie_channels.json')
CAND = Path('scripts/_new_cand_map.json')


def find_key_arr(raw, key_name, arr_field):
    """定位 script JSON 中某 key 对象的数组字段 [..] 边界。"""
    m = re.search(r'"%s"\s*:\s*\{' % re.escape(key_name), raw)
    if not m:
        raise ValueError('未找到 key ' + key_name)
    # 正则本身已吃掉 '{'，m.end() 指向其后；若再 index('{') 会跳到**下一个**频道的
    # '{'，导致线路被插进相邻频道的数组（v1.6.44 修复）。
    brace = m.end() - 1
    fpos = raw.index('"%s"' % arr_field, brace)
    a = raw.index('[', fpos)
    depth, in_str, esc = 0, False, False
    for i in range(a, len(raw)):
        ch = raw[i]
        if in_str:
            if esc: esc = False
            elif ch == '\\': esc = True
            elif ch == '"': in_str = False
            continue
        if ch == '"': in_str = True
        elif ch == '[': depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                return a, i
    raise ValueError('未找到数组结尾')


def insert_head(raw, key_name, urls, arr_field='ipv4'):
    """在数组头部插入 urls（去重、保序），返回新文本。"""
    a, b = find_key_arr(raw, key_name, arr_field)
    block = raw[a:b + 1]
    existing = json.loads(block)
    add = [u for u in urls if u not in existing]
    if not add:
        return raw, 0
    nl = '\r\n' if '\r\n' in raw else '\n'
    # 推断缩进：取现有元素行缩进
    m = re.search(r'\[\s*%s([ \t]*)"' % nl, block)
    indent = m.group(1) if m else '      '
    items = [json.dumps(u, ensure_ascii=False) for u in add + existing]
    # 保留原数组是否单行
    if nl not in block:
        new_block = '[' + ', '.join(items) + ']'
    else:
        close = re.search(r'(%s)([ \t]*)\]$' % nl, block)
        close_indent = close.group(2) if close else ''
        new_block = '[' + nl + (',' + nl).join(indent + x for x in items) + nl + close_indent + ']'
    return raw[:a] + new_block + raw[b + 1:], len(add)


def main():
    cand = json.loads(CAND.read_text('utf-8'))
    # 按频道聚合新 URL（保持编号顺序）
    bych = {}
    for tag, name in sorted(GOOD.items()):
        u = cand[tag]['url']
        bych.setdefault(name, [])
        if u not in bych[name]:
            bych[name].append(u)

    # ---- channel_plan.json ----
    raw = PLAN.read_text('utf-8')
    total = 0
    for name, urls in sorted(bych.items()):
        if name in MOVIE_NAMES:
            continue
        raw, n = insert_head(raw, name, urls, 'ipv4')
        total += n
        print('  plan %-10s 插入 %d 条' % (name, n))
    # 校验
    d = json.loads(raw)
    assert len(d['sites']) if 'sites' in d else True
    for name, urls in bych.items():
        if name in MOVIE_NAMES: continue
        cur = d['channels'][name]['ipv4']
        assert all(u in cur for u in urls), '并入失败 ' + name
    PLAN.write_text(raw, encoding='utf-8')
    print('channel_plan.json 共插入 %d 条' % total)

    # ---- movie_channels.json ----
    raw = MOVIE.read_text('utf-8')
    total2 = 0
    for name in MOVIE_NAMES:
        urls = bych.get(name, [])
        if not urls: continue
        # movie 是顶层 key: "CHC动作电影": [ ... ]
        # v1.6.44：原正则的 \s* 会跨行匹配到**下一个** key 的 '['，导致数组边界取错、
        # 新线路被插到相邻频道。限定为同行空白 [^\S\n]*。
        m = re.search(r'"%s"[^\S\n]*:[^\S\n]*\[' % re.escape(name), raw)
        if not m:
            raise ValueError('未找到 movie key ' + name)
        a = m.end() - 1
        depth, in_str, esc = 0, False, False
        for i in range(a, len(raw)):
            ch = raw[i]
            if in_str:
                if esc: esc = False
                elif ch == '\\': esc = True
                elif ch == '"': in_str = False
                continue
            if ch == '"': in_str = True
            elif ch == '[': depth += 1
            elif ch == ']':
                depth -= 1
                if depth == 0:
                    b = i; break
        block = raw[a:b + 1]
        existing = json.loads(block)
        add = [u for u in urls if u not in existing]
        if add:
            nl = '\r\n' if '\r\n' in raw else '\n'
            items = [json.dumps(u, ensure_ascii=False) for u in add + existing]
            m2 = re.search(r'\[\s*%s([ \t]*)"' % nl, block)
            indent = m2.group(1) if m2 else '    '
            close = re.search(r'(%s)([ \t]*)\]$' % nl, block)
            close_indent = close.group(2) if close else ''
            new_block = '[' + nl + (',' + nl).join(indent + x for x in items) + nl + close_indent + ']'
            raw = raw[:a] + new_block + raw[b + 1:]
            total2 += len(add)
            print('  movie %-10s 插入 %d 条' % (name, len(add)))
    d2 = json.loads(raw)
    for name in MOVIE_NAMES:
        for u in bych.get(name, []):
            assert u in d2[name], 'movie 并入失败 ' + name
    MOVIE.write_text(raw, encoding='utf-8')
    print('movie_channels.json 共插入 %d 条' % total2)


if __name__ == '__main__':
    main()
