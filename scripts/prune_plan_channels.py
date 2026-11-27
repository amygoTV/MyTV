#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 channel_plan.json 删除指定频道（字符级，保持原缩进/换行风格）。

v1.6.44 需求：
- 删除全部 CGTN 频道（6 个：CGTN / CGTN纪录 / 俄语 / 法语 / 西语 / 阿语）
- 删除「央视付费」组（9 个剧场/专题频道，已并入 movie_channels.json 的影视轮播组，
  目的是消除与影视组 怀旧剧场/第一剧场/风云剧场 的同名重复）

删除语义（关键，v1.6.44 踩坑记录）：
JSON 对象里每个成员形如
    "name": { ... },\n
最后一个成员则是
    "name": { ... }\n
所以删块必须分两种情况处理逗号，否则会留下尾逗号：
  A. 块后有 ','  -> 删「块 + 其后的 ',' + 换行」；块前的 ',' 保留给前一项
  B. 块是对象最后一项（块后无 ','）-> 删「块前紧邻的 ',' 」+ 块 + 换行
先在内存中全部删完再一次性校验 JSON，避免中途写坏文件。

用法：
    python3 scripts/prune_plan_channels.py --names CGTN CGTN纪录 ...
    python3 scripts/prune_plan_channels.py --group 央视付费
    python3 scripts/prune_plan_channels.py --group 央视付费 --prune-group-order
"""
import argparse
import json
import re
import sys
from pathlib import Path

PLAN = Path('scripts/channel_plan.json')


def find_block(raw, name):
    """定位顶层 "name": { ... } 块的起止（返回 start, end，end 为 '}' 之后）。"""
    m = re.search(r'\n[^\S\n]*"%s"[^\S\n]*:[^\S\n]*\{' % re.escape(name), raw)
    if not m:
        return None
    start = m.start() + 1
    brace = raw.index('{', start)
    depth, in_str, esc = 0, False, False
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
                return start, i + 1
    raise ValueError('未找到对象结尾 ' + name)


def drop_block(raw, name):
    """删掉一个顶层成员块，正确处理逗号。"""
    span = find_block(raw, name)
    if not span:
        raise ValueError('未找到频道块 ' + name)
    start, end = span

    # 块后：跳过空白看下一个字符
    probe = end
    while probe < len(raw) and raw[probe] in ' \t':
        probe += 1
    if probe < len(raw) and raw[probe] == ',':
        # A. 后面还有兄弟项 -> 连同这个逗号和后面的换行一起删
        tail = probe + 1
        if tail < len(raw) and raw[tail] == '\r':
            tail += 1
        if tail < len(raw) and raw[tail] == '\n':
            tail += 1
        return raw[:start] + raw[tail:], 'after'

    # B. 块是对象最后一个成员 -> 向前删掉前一项结尾的逗号
    #    原文形如：  ...    },\n    "风云音乐": { ... }\n  },
    #    前一项的 ',' 位于 '}' 之后、'\n' 之前，必须跨过换行才能找到。
    head = start
    while head > 0 and raw[head - 1] in ' \t\r\n':
        head -= 1
    if head > 0 and raw[head - 1] == ',':
        head -= 1
    # 保留块后的换行（下一层是 '  },' 或 '  "key": ...'）
    return raw[:head] + raw[end:], 'last'


def prune_names(raw, names):
    removed = []
    for n in names:
        raw, how = drop_block(raw, n)
        removed.append((n, how))
    return raw, removed


def prune_group_order(raw, group):
    """从 groups_order 数组里去掉某个分组名（字符级，不重排其它项）。"""
    m = re.search(r'"groups_order"[^\S\n]*:', raw)
    if not m:
        return raw, False
    a = raw.index('[', m.end())
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
                b = i
                break
    block = raw[a:b + 1]
    items = re.findall(r'"([^"]+)"', block)
    if group not in items:
        return raw, False
    keep = [x for x in items if x != group]
    nl = '\r\n' if '\r\n' in raw else '\n'
    m2 = re.search(r'\[\s*%s([ \t]*)"' % nl, block)
    indent = m2.group(1) if m2 else '    '
    close = re.search(r'(%s)([ \t]*)\]$' % nl, block)
    close_indent = close.group(2) if close else ''
    new_block = '[' + nl + (',' + nl).join(
        indent + json.dumps(x, ensure_ascii=False) for x in keep
    ) + nl + close_indent + ']'
    return raw[:a] + new_block + raw[b + 1:], True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--names', nargs='*', help='要删除的频道名')
    ap.add_argument('--group', help='要删除该分组的全部频道')
    ap.add_argument('--prune-group-order', action='store_true',
                    help='同时从 groups_order 移除该分组')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    raw = PLAN.read_text('utf-8')
    before = json.loads(raw)
    names = list(args.names or [])

    if args.group:
        grp = args.group
        names += [n for n, m in before['channels'].items() if m.get('group') == grp]
    if not names:
        print('未指定要删除的频道')
        return

    print('待删除 %d 个频道：%s' % (len(names), '、'.join(names)))
    raw, removed = prune_names(raw, names)
    for n, how in removed:
        print('  删除 %-12s (%s)' % (n, '块后有兄弟项' if how == 'after' else '对象最后一项'))

    if args.prune_group_order and args.group:
        raw, ok = prune_group_order(raw, args.group)
        print('  groups_order 移除 %s: %s' % (args.group, '是' if ok else '未找到'))

    after = json.loads(raw)  # 严格校验
    print('校验通过：channels %d -> %d，groups_order=%s'
          % (len(before['channels']), len(after['channels']), after['groups_order']))
    if args.dry_run:
        print('（dry-run，未写盘）')
        return
    PLAN.write_text(raw, 'utf-8')
    print('已写盘 %s' % PLAN)


if __name__ == '__main__':
    main()
