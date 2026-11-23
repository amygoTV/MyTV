"""教育台定向重建：只重算保底频道，保留影视/体育段落。

用法：python scripts/rebuild_edu_only.py
背景：build_live_sources.py 的全量重建要重拉 14 个源池（慢，数十分钟）。
本次只改了 channel_plan.json 里教育台（CETV-1~4）的线路 + ad_blacklist.txt，
没必要重拉影视/体育。本脚本复用现有 TVLives.txt 里「影视轮播」「体育频道」
两组的全部内容，只重新生成保底频道部分，然后重写 TVLives.txt/_v2.txt/_v2.m3u。
"""
import concurrent.futures
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

import build_live_sources as B
import live_groups

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = ROOT

with open(os.path.join(ROOT, 'scripts', 'channel_plan.json'), encoding='utf-8') as f:
    plan = json.load(f)

channels = plan['channels']
GROUP_MAP = live_groups.GROUP_MAP
groups_order = live_groups.groups_order(plan)

# 1) 读取现有 TVLives.txt，抽出影视轮播 / 体育频道 两组的内容
prev_path = os.path.join(REPO, 'TVLives.txt')
prev_lines = []
if os.path.exists(prev_path):
    with open(prev_path, encoding='utf-8-sig', newline='') as f:
        prev_lines = f.read().splitlines()

special_lines = {}   # group -> [lines]
cur = None
for ln in prev_lines:
    s = ln.strip()
    if not s:
        continue
    if s.endswith(',#genre#'):
        cur = s[:-len(',#genre#')]
        continue
    if cur in ('影视轮播', '体育频道'):
        special_lines.setdefault(cur, []).append(ln)

print('复用上一版：影视轮播 %d 行 / 体育频道 %d 行' % (
    len(special_lines.get('影视轮播', [])), len(special_lines.get('体育频道', []))), flush=True)

# 从上一版 m3u 里抽出影视轮播 / 体育频道两组的原始块（连 EXTINF 行一起保留）
special_m3u = {}
prev_m3u_path = os.path.join(REPO, 'TVLives_v2.m3u')
if os.path.exists(prev_m3u_path):
    with open(prev_m3u_path, encoding='utf-8', newline='') as f:
        m3u_prev = f.read().splitlines()
    cur = None
    for ln in m3u_prev:
        s = ln.strip()
        if s.startswith('#EXTINF'):
            g = s.split('group-title="', 1)[-1].split('"', 1)[0] if 'group-title="' in s else ''
            cur = g if g in ('影视轮播', '体育频道') else None
            if cur:
                special_m3u.setdefault(cur, []).append(ln)
            continue
        if s.startswith('#'):
            continue
        if cur:
            special_m3u.setdefault(cur, []).append(ln)
    print('复用上一版 m3u：影视轮播 %d 行 / 体育频道 %d 行' % (
        len(special_m3u.get('影视轮播', [])), len(special_m3u.get('体育频道', []))), flush=True)

# 2) 保底频道：IPv4 逐条实测
v4_tasks, v6_map = [], {}
for name, meta in channels.items():
    for u in meta['ipv4']:
        if not B.is_ipv6(u):
            v4_tasks.append((name, B.clean_url(u)))
    if meta['ipv6']:
        v6_map[name] = [B.clean_url(u) for u in meta['ipv6'][:2]]

alive_urls = set(B.probe_many([u for _, u in v4_tasks], 16, '保底IPv4'))

group_items = {g: [] for g in groups_order}
index = {}


def add(group, name, urls):
    if group not in group_items:
        return
    key = (group, B.canon(name))
    disp = B.display_name(name)
    if key in index:
        item = group_items[group][index[key]]
        for u in urls:
            if u and u not in item['urls']:
                item['urls'].append(u)
    else:
        index[key] = len(group_items[group])
        group_items[group].append({
            'name': disp, 'urls': [u for u in urls if u], 'order': index[key]})


for name, meta in channels.items():
    v4_all = [B.clean_url(u) for u in meta['ipv4'] if not B.is_ipv6(u)]
    alive = [u for u in v4_all if u in alive_urls]
    rest = [u for u in v4_all if u not in alive_urls]
    urls = [u for u in (alive + rest)[:3] + v6_map.get(name, [])[:2]
            if not B.is_blacklisted(u)]
    if len(urls) < 3:
        urls = [B.clean_url(u) for u in meta['ipv4'][:3] if not B.is_blacklisted(u)]
    add(GROUP_MAP.get(meta['group'], meta['group']), name, urls)

# 3) 保底部分逐组渲染
lines = []
for g in groups_order:
    if g in ('影视轮播', '体育频道'):
        continue
    items = group_items.get(g, [])
    if not items:
        continue
    lines.append('%s,#genre#' % g)
    for it in sorted(items, key=lambda x: x['order']):
        nm = it['name'].replace(',', '，')
        for u in it['urls']:
            lines.append('%s,%s' % (nm, u))

# 4) 拼回影视/体育（保持原分组位置：按 groups_order 插入）
final = []
for g in groups_order:
    if g in ('影视轮播', '体育频道'):
        final.append('%s,#genre#' % g)
        final.extend(special_lines.get(g, []))
    else:
        items = group_items.get(g, [])
        if not items:
            continue
        final.append('%s,#genre#' % g)
        for it in sorted(items, key=lambda x: x['order']):
            nm = it['name'].replace(',', '，')
            for u in it['urls']:
                final.append('%s,%s' % (nm, u))

B.write_txt(os.path.join(REPO, 'TVLives.txt'), final)
B.write_txt(os.path.join(REPO, 'TVLives_v2.txt'), final)

# 5) M3U：同样复用影视/体育
m3u = ['#EXTM3U']
for g in groups_order:
    if g in ('影视轮播', '体育频道'):
        m3u.extend(special_m3u.get(g, []))
        continue
    items = sorted(group_items.get(g, []), key=lambda x: x['order'])
    if not items:
        continue
    for it in items:
        m3u.append('#EXTINF:-1 group-title="%s",%s'
                   % (g, it['name'].replace(',', '，').replace('"', '')))
        m3u.extend(it['urls'])
for fn in ('TVLives.m3u', 'TVLives_v2.m3u'):
    with open(os.path.join(REPO, fn), 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(m3u).rstrip('\n') + '\n')

chans = sum(len(group_items.get(g, [])) for g in groups_order)
total = sum(len(it['urls']) for g in groups_order for it in group_items.get(g, []))
print('=> TVLives.txt：%d 频道 / %d 线路' % (chans, total), flush=True)
