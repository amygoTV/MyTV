"""修复客户端配置里的直播入口指向（字符级精确替换，不重排 JSON）。

两个问题：
  ① 「(备)」条目指向 gcore 的 TVLives_v2.* —— gcore 边缘**不被 purge 覆盖**，
     而 TVLives_v2.* 每天由 Action 重建 → gcore 上永远是旧版（仍含旧污染源）。
     修复：gcore 只放**静态不变**的 TVLivesBackup.m3u。
  ② 「🎵抖音/平台直播🎵」指向 PlatformLive.txt —— 该文件 v1.4.5 已移除 → 404 死链。
     修复：删除该 lives 条目。

用法：python scripts/fix_lives_entries.py [--dry-run]
"""
import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')
ROOT = pathlib.Path(__file__).resolve().parent.parent

# gcore 上的「会变」文件 → 改为 gcore 上的静态备选源
GCORE_FIX = [
    ('https://gcore.jsdelivr.net/gh/amygoTV/MyTV@master/TVLives_v2.txt',
     'https://gcore.jsdelivr.net/gh/amygoTV/MyTV@master/TVLivesBackup.m3u'),
    ('https://gcore.jsdelivr.net/gh/amygoTV/MyTV@master/TVLives_v2.m3u',
     'https://gcore.jsdelivr.net/gh/amygoTV/MyTV@master/TVLivesBackup.m3u'),
]

# PlatformLive 条目：整个 JSON 对象删掉。
# 用「对象内的 url 含 PlatformLive」来定位，再从对象起始 { 到配对 } 整块删除，
# 不能用宽松正则（会跨对象贪婪匹配吃掉后面的条目）。
PL_URL = 'PlatformLive.txt'


def strip_pl_entries(raw):
    """删除所有 url 含 PlatformLive 的 lives 对象。返回 (新文本, 删除条数)。"""
    n = 0
    while True:
        u = raw.find(PL_URL)
        if u < 0:
            break
        # 往前找该 url 所属对象的起始 '{'
        ob = raw.rfind('{', 0, u)
        if ob < 0:
            break
        # 从 ob 起做花括号配对，找到对象结束
        depth = 0
        i = ob
        while i < len(raw):
            if raw[i] == '{':
                depth += 1
            elif raw[i] == '}':
                depth -= 1
                if depth == 0:
                    break
            i += 1
        if i >= len(raw):
            break
        end = i + 1
        # 连同后面的逗号与空白一起删（保留合法 JSON 结构）
        j = end
        while j < len(raw) and raw[j] in ' \t':
            j += 1
        if j < len(raw) and raw[j] == ',':
            end = j + 1
        else:
            # 没有尾逗号（是数组最后一项）→ 连同前置逗号一起删
            k = ob - 1
            while k >= 0 and raw[k] in ' \t\r\n':
                k -= 1
            if k >= 0 and raw[k] == ',':
                ob = k
        # 清掉对象前后多余空行
        pre = raw[:ob].rstrip()
        post = raw[end:].lstrip('\r\n')
        raw = pre + '\n' + post
        n += 1
    return raw, n

changed = []
for p in sorted(ROOT.rglob('*.json')):
    rel = p.relative_to(ROOT)
    if any(x in str(rel) for x in ('node_modules', 'package-lock', 'scripts/', '.git')):
        continue
    try:
        raw = p.read_text(encoding='utf-8', newline='')
    except Exception:
        continue
    if 'TVLives' not in raw and 'PlatformLive' not in raw:
        continue
    orig = raw
    n_g = 0
    for old, new in GCORE_FIX:
        n_g += raw.count(old)
        raw = raw.replace(old, new)
    n_p = 0
    if PL_URL in raw:
        raw, n_p = strip_pl_entries(raw)
    if raw != orig:
        # 必须仍是严格合法 JSON（首行不允许注释）
        try:
            json.loads(raw)
        except Exception as e:
            print('  ✗ %s 改后 JSON 非法，已跳过：%s' % (rel, e))
            continue
        p.write_text(raw, encoding='utf-8', newline='')
        changed.append((str(rel), n_g, n_p))
        print('  ✓ %-46s gcore改 %d  删PlatformLive %d' % (rel, n_g, n_p))

print('\n共修改 %d 个文件' % len(changed))
