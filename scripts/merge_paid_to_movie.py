#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.6.44：消除「央视付费」组与「影视轮播」组的同名频道重复。

问题：channel_plan.json 的「央视付费」组有 9 个 CCTV 剧场/专题频道
（兵器科技/央视台球/女性时尚/怀旧剧场/文化精品/电视指南/第一剧场/风云剧场/风云音乐），
与 movie_channels.json「影视轮播」组的 怀旧剧场/第一剧场/风云剧场 同名。
产物里同一频道名出现在两个分组 → 客户端按频道名建表会冲突（项目铁律：
同名频道重复即视为缺陷）。

处理：把付费组 9 个频道整体并入 movie_channels.json（影视轮播），
源去重后按「速度 > 分辨率」排序；再从 channel_plan.json 删除付费组频道
并清空 groups_order 里的「央视付费」。

字符级操作，保持各文件原缩进与换行风格。
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_live_sources import (  # noqa: E402
    load_resolution_map, load_speed_map, sort_by_quality, clean_url,
)

PLAN = Path('scripts/channel_plan.json')
MOVIE = Path('scripts/movie_channels.json')


def find_top_arr(raw, key):
    """定位顶层 "key": [ ... ] 的数组边界（同行空白，避免跨行误配）。"""
    m = re.search(r'"%s"[^\S\n]*:[^\S\n]*\[' % re.escape(key), raw)
    if not m:
        raise ValueError('未找到 key ' + key)
    a = m.end() - 1
    depth, in_str, esc = 0, False, False
    for i in range(a, len(raw)):
        ch = raw[i]
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                return a, i
    raise ValueError('未找到数组结尾 ' + key)


def rebuild_arr(raw, key, urls):
    """用新 URL 列表整体替换某顶层数组内容，保持缩进风格。

    key 不存在时（付费组独有频道）则在顶层对象末尾追加新 key。
    """
    nl = '\r\n' if '\r\n' in raw else '\n'
    try:
        a, b = find_top_arr(raw, key)
    except ValueError:
        # 新增顶层 key：插到最后一个顶层 "key": [...] 之后
        matches = list(re.finditer(r'"[^"]+"[^\S\n]*:[^\S\n]*\[', raw))
        if not matches:
            raise
        last = matches[-1]
        _, lb = find_top_arr(raw, re.match(r'"([^"]+)"', last.group(0)).group(1))
        # 在该数组闭合 ']' 之后插入 "key": [ ... ],
        pos = lb + 1
        while pos < len(raw) and raw[pos] in ' \t':
            pos += 1
        if pos < len(raw) and raw[pos] == ',':
            pos += 1
        if pos < len(raw) and raw[pos] == '\r':
            pos += 1
        if pos < len(raw) and raw[pos] == '\n':
            pos += 1
        items = [json.dumps(u, ensure_ascii=False) for u in urls]
        block = ' %s: [' % json.dumps(key, ensure_ascii=False) + nl + \
            (',' + nl).join('  ' + x for x in items) + nl + ' ],' + nl
        return raw[:pos] + block + raw[pos:]
    block = raw[a:b + 1]
    m2 = re.search(r'\[\s*%s([ \t]*)"' % nl, block)
    indent = m2.group(1) if m2 else '    '
    close = re.search(r'(%s)([ \t]*)\]$' % nl, block)
    close_indent = close.group(2) if close else ''
    items = [json.dumps(u, ensure_ascii=False) for u in urls]
    new_block = '[' + nl + (',' + nl).join(indent + x for x in items) + nl + close_indent + ']'
    return raw[:a] + new_block + raw[b + 1:]


def main():
    res_map = load_resolution_map()
    speed_map = load_speed_map()

    plan_raw = PLAN.read_text('utf-8')
    plan = json.loads(plan_raw)
    paid = {n: meta for n, meta in plan['channels'].items()
            if meta.get('group') == '央视付费'}
    if not paid:
        print('付费组为空，无需处理')
        return
    print('付费组 %d 个频道：%s' % (len(paid), '、'.join(paid)))

    # ---- 1) 并入 movie_channels.json ----
    movie_raw = MOVIE.read_text('utf-8')
    movie = json.loads(movie_raw)
    for name, meta in paid.items():
        urls = [clean_url(u) for u in meta.get('ipv4', [])]
        if name in movie:
            merged = list(dict.fromkeys(list(movie[name]) + urls))
        else:
            merged = urls
        merged = sort_by_quality(merged, res_map, speed_map)
        movie_raw = rebuild_arr(movie_raw, name, merged)
        print('  movie %-8s %d 条' % (name, len(merged)))
    MOVIE.write_text(movie_raw, 'utf-8')

    # ---- 2) 从 plan 删除付费组频道 ----
    raw = plan_raw
    for name in paid:
        m = re.search(r'\n[^\S\n]*"%s"[^\S\n]*:[^\S\n]*\{' % re.escape(name), raw)
        if not m:
            raise ValueError('未找到付费频道块 ' + name)
        block_start = m.start() + 1
        brace = raw.index('{', block_start)
        depth, in_str, esc = 0, False, False
        end = None
        for i in range(brace, len(raw)):
            ch = raw[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == '\\':
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        # 删块。逗号处理：
        #   - 块后还有内容 -> 删块 + 块后的逗号（块前逗号留给前一项）
        #   - 块是对象最后一项 -> 删块 + 块前的逗号（否则留下尾逗号）
        tail = end + 1
        probe = tail
        while probe < len(raw) and raw[probe] in ' \t':
            probe += 1
        # 块后是逗号 -> 说明后面还有兄弟项：删掉「块 + 块后逗号」，
        # 块前逗号保留给前一项（成为新尾项）。
        if probe < len(raw) and raw[probe] == ',':
            tail = probe + 1
        else:
            # 块是对象最后一项：向前吃掉块前的逗号与缩进，避免留下尾逗号
            head = block_start
            while head > 0 and raw[head - 1] in ' \t':
                head -= 1
            if head > 0 and raw[head - 1] == ',':
                head -= 1
            block_start = head
        if tail < len(raw) and raw[tail] == '\r':
            tail += 1
        if tail < len(raw) and raw[tail] == '\n':
            tail += 1
        raw = raw[:block_start] + raw[tail:]
        print('  plan  删除 %s' % name)
    json.loads(raw)  # 断言仍是合法 JSON
    PLAN.write_text(raw, 'utf-8')

    # ---- 3) groups_order 去掉「央视付费」 ----
    plan2 = json.loads(raw)
    if '央视付费' in plan2.get('groups_order', []):
        plan2['groups_order'] = [g for g in plan2['groups_order'] if g != '央视付费']
        raw2 = re.sub(r'("groups_order"[^\S\n]*:[^\S\n]*\[)(.*?)(\])',
                      lambda mm: mm.group(1)
                      + '\n' + ',\n'.join('    %s' % json.dumps(g, ensure_ascii=False)
                                           for g in plan2['groups_order'])
                      + '\n  ' + mm.group(3),
                      raw, count=1, flags=re.S)
        # 校验仍是合法 JSON
        json.loads(raw2)
        PLAN.write_text(raw2, 'utf-8')
        raw = raw2
    print('groups_order ->', json.loads(raw)['groups_order'])

    # ---- 4) 校验 ----
    p2 = json.loads(PLAN.read_text('utf-8'))
    m2 = json.loads(MOVIE.read_text('utf-8'))
    assert not any(x.get('group') == '央视付费' for x in p2['channels'].values())
    assert '央视付费' not in p2['groups_order']
    dup = set(m2) & set(p2['channels'])
    assert not dup, '仍有重名频道: %s' % dup
    print('校验通过：plan %d 频道 / movie %d 频道，无重名'
          % (len(p2['channels']), len(m2)))


if __name__ == '__main__':
    main()
