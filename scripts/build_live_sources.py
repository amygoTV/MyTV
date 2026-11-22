#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一直播源筛选流水线 v2（权威频道表驱动）
==========================================

相对 v1 的核心变化（按用户 2026-11-22 需求）：
1. 权威频道表 scripts/channel_plan.json 驱动，保证「必须有的频道」永远存在：
   - 央视组：CCTV1-17 → 付费频道(CCTV5+) → CGTN 系列 → 中国教育1-4台
   - 卫视组：31 省级卫视 + 深圳卫视，按 2024-2025 黄金时段收视率排名
   - 每个频道最多 3 条 IPv4 + 2 条 IPv6
2. IPv4 逐条实测可播性；IPv6（移动 IPTV 2409:8087）无出口不探测，作为备用源保留。
3. 不再生成 PlatformLive（已移除）；地方频道全部剔除。
4. 广告/错台/静态录像/分组噪音过滤 + 跨文件 URL 去重全部保留。
5. 探测不足时保留上一版（防止 CI 上游抖动清空源文件）。

输出文件：TVLives.txt（央视/卫视 + 电影/体育附加组）、BiliLive.txt、LiveSports.txt

用法：
    python3 scripts/build_live_sources.py                       # 全量
    python3 scripts/build_live_sources.py --probe-limit 100      # 快速通道
    python3 scripts/build_live_sources.py --out-dir /tmp/x
"""
import argparse
import concurrent.futures
import html
import json
import os
import re
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

UA_PLAYER = 'okHttp/Mursor-1.4.0.0'

# ---------------------------------------------------------------- 上游源
# 电影/体育为「能找到就要」的附加组，其余正规台由权威频道表保底
EXTRA_SOURCES = [
    ('电影频道', [
        ('https://peterhchina.github.io/iptv/IPTV-V4.m3u', UA_PLAYER),
    ]),
    ('体育频道', [
        ('https://peterhchina.github.io/iptv/huyayqk.m3u', UA_PLAYER),
        ('https://peterhchina.github.io/iptv/douyuyqk.m3u', UA_PLAYER),
    ]),
]
BILI_SOURCES = [
    ('https://peterhchina.github.io/iptv/bililive.m3u', UA_PLAYER),
]
SPORTS_SOURCES = [
    'https://peterhchina.github.io/iptv/huyayqk.m3u',
    'https://peterhchina.github.io/iptv/douyuyqk.m3u',
    'https://peterhchina.github.io/iptv/yylunbo.m3u',
    'https://peterhchina.github.io/iptv/CNTV-V4.m3u',
]

# ---------------------------------------------------------------- 过滤规则
AD_NAME_RE = re.compile(
    r'(支持作者|感谢|订阅|广告|推广|二维码|扫码|公众号|更多资源|获取资源|'
    r'请\s*user|请查看最新|请访问|请到|失效|版权|声明|免责|'
    r'列表更新时间|更新时间|维护中?|暫無|暂无主播|温馨|提示|'
    r'测试|測試|test|^\d+$|^\d{4}[-/]\d{1,2})', re.I)
AD_HOST_RE = re.compile(
    r'(vd\d*\.bdstatic\.com|bdstatic\.com|\.upic\.|\.kwimgs\.com|'
    r'pan\.|aliyundrive|alipan|baidupcs)', re.I)
STATIC_EXT_RE = re.compile(r'\.(mp4|flv|mp3|aac|m4a|mkv|avi)(\?|$)', re.I)
GROUP_NOISE_RE = re.compile(r'(列表更新时间|更新时间|4K频道|溫馨|温馨|提示|维护)')
NORM_RE = re.compile(r'[\s\-_—·・]+')
SUFFIX_RE = re.compile(r'(高清|超清|蓝光|超高清|HD|FHD|4K|1080P|720P|标清|标高清)+$', re.I)
SPORTS_RE = re.compile(r'(体育|足球|篮球|NBA|CCTV-?5|赛事|奥运|网球|羽毛球|F1|赛车|排球|乒乓|台球|游泳|田径|西甲|英超|中超|欧冠)', re.I)
MOVIE_RE = re.compile(r'(电影|影院|影厅|剧场|CCTV-?6|动作片|喜剧片|经典电影|影视)', re.I)


def norm_key(name):
    s = NORM_RE.sub('', html.unescape(name or '')).upper()
    s = SUFFIX_RE.sub('', s)
    s = re.sub(r'^(CCTV|CETV)\s*(\d+)$', r'\1\2', s)
    return s.strip()


def is_ipv6(url):
    return bool(re.match(r'https?://\[[0-9a-fA-F:]+\]', url))


def fetch(url, timeout=30, ua=UA_PLAYER, tries=3):
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': ua, 'Accept': '*/*'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode('utf-8', 'ignore')
        except Exception as e:
            last = e
            time.sleep(1.2)
    raise last


ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')


def parse_m3u(text):
    """-> [(group, name, url)]"""
    out, group, name, tvg = [], '', '', ''
    for raw in text.split('\n'):
        line = raw.strip()
        if not line:
            continue
        if line.startswith('#EXTINF'):
            attrs = dict(ATTR_RE.findall(line))
            group = (attrs.get('group-title') or '').strip()
            tvg = (attrs.get('tvg-name') or '').strip()
            idx = line.rfind(',')
            name = html.unescape(line[idx + 1:].strip()) if idx > 0 else ''
            continue
        if line.startswith('#'):
            continue
        if line.startswith('http'):
            out.append((group, tvg or name, line))
    return out


def playable(url, timeout=8):
    if is_ipv6(url):
        return False
    url = url.split('#', 1)[0]
    req = urllib.request.Request(url, headers={
        'User-Agent': UA_PLAYER, 'Accept': '*/*', 'Range': 'bytes=0-8191'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status not in (200, 206):
                return False
            body = r.read(8192)
            if b'#EXTM3U' in body:
                return True
            return ('mpegurl' in str(r.headers.get('Content-Type', '')).lower()) and len(body) > 40
    except Exception:
        return False


def probe_many(urls, workers, label=''):
    """探测一组 URL，返回可播的 URL 集合（保序去重）。"""
    uniq = list(dict.fromkeys(u.split('#', 1)[0] for u in urls))
    alive = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(playable, u): u for u in uniq}
        for f in concurrent.futures.as_completed(futs):
            u = futs[f]
            try:
                if f.result():
                    alive.append(u)
            except Exception:
                pass
    order = {u: i for i, u in enumerate(uniq)}
    alive.sort(key=lambda u: order[u])
    if label:
        print('    [%s] 可播 %d/%d' % (label, len(alive), len(uniq)), flush=True)
    return alive


def clean_name(n):
    return re.sub(r'[\s]+', '', re.sub(r'[（(].*?[）)]', '', n or ''))


def build_tvlives(plan, out_dir, workers, probe_limit, max_per_source, prev_content=None):
    print('\n=== 构建 TVLives.txt（权威频道表驱动） ===', flush=True)
    channels = plan['channels']
    groups_order = plan['groups_order']

    # 1) 拉取上游，收集「附加组」候选（电影/体育）——正规台不依赖上游，避免上游抖动
    upstream = []
    src_budget = {}
    for grp, sources in EXTRA_SOURCES:
        for url, ua in sources:
            try:
                txt = fetch(url, 30, ua)
                got = parse_m3u(txt)
                upstream.extend((grp, n, u) for (g, n, u) in got)
                src_budget[url] = len(got)
                print('  拉取 %-40s %4d 条' % (url.split('/')[-1], len(got)), flush=True)
            except Exception as e:
                print('  拉取失败 %-40s %s' % (url.split('/')[-1], str(e)[:36]), flush=True)

    # 过滤 + 分类候选到附加组
    movie_cand, sports_cand = [], []
    for grp, name, url in upstream:
        if GROUP_NOISE_RE.search(grp) or AD_NAME_RE.search(name) or AD_HOST_RE.search(url):
            continue
        if STATIC_EXT_RE.search(url) or is_ipv6(url) or not norm_key(name):
            continue
        if '赛事' in grp or '体育' in grp or SPORTS_RE.search(name):
            sports_cand.append((name, url))
        elif '电影' in grp or MOVIE_RE.search(name):
            movie_cand.append((name, url))

    # 2) 权威表：对每个必需频道的 IPv4 探测（IPv6 不探测，直接作为备用）
    v4_tasks, v6_map = [], {}
    for name, meta in channels.items():
        for u in meta['ipv4']:
            if not is_ipv6(u):
                v4_tasks.append((name, u.split('#', 1)[0]))
        if meta['ipv6']:
            v6_map[name] = meta['ipv6'][:2]

    # 探测预算控制
    if probe_limit > 0 and len(v4_tasks) > probe_limit:
        v4_tasks = v4_tasks[:probe_limit]
    alive_by_name = {}
    alive_urls = probe_many([u for _, u in v4_tasks], workers, '保底IPv4')

    # 3) 附加组探测（能找到就要），按频道聚合
    def build_extra(cands, label, limit=40):
        by = {}
        for name, url in cands:
            k = clean_name(name)
            if not k:
                continue
            by.setdefault(k, {'name': name, 'urls': []})
            if url not in by[k]['urls']:
                by[k]['urls'].append(url)
        # 每个候选频道取前若干条探测
        picked = []
        for k, it in list(by.items())[:limit]:
            for u in it['urls'][:3]:
                picked.append((k, it['name'], u))
        if probe_limit > 0 and len(picked) > probe_limit:
            picked = picked[:probe_limit]
        alive = probe_many([u for _, _, u in picked], workers, label)
        alive_set = set(alive)
        result = {}
        for k, name, u in picked:
            if u in alive_set:
                result.setdefault(k, {'name': name, 'urls': []})
                if u not in result[k]['urls']:
                    result[k]['urls'].append(u)
        return result

    movie = build_extra(movie_cand, '电影频道', limit=30)
    sports = build_extra(sports_cand, '体育频道', limit=30)

    # 4) 组装输出：严格按 group_order + order 排序
    group_items = {g: [] for g in groups_order}
    for name, meta in channels.items():
        v4 = [u for u in meta['ipv4'] if not is_ipv6(u) and u.split('#', 1)[0] in alive_urls]
        v6 = v6_map.get(name, [])
        urls = v4[:3] + v6[:2]     # 3 IPv4 + 2 IPv6
        if not urls:
            # 保底频道即使全部探测失败也要出现（保留原始 IPv4 保底，CI 常无出口）
            urls = [u.split('#', 1)[0] for u in meta['ipv4'][:3]]
        if not urls:
            continue
        group_items[meta['group']].append({'name': name, 'urls': urls, 'order': meta['order']})

    for k, it in movie.items():
        if it['urls']:
            group_items['电影频道'].append({'name': it['name'], 'urls': it['urls'][:3], 'order': 1000})
    for k, it in sports.items():
        if it['urls']:
            group_items['体育频道'].append({'name': it['name'], 'urls': it['urls'][:3], 'order': 1000})

    # 组内去重 URL（同一流只归属一个频道）
    used = set()
    lines = []
    for g in groups_order:
        items = sorted(group_items.get(g, []), key=lambda x: x['order'])
        if not items:
            continue
        lines.append('%s,#genre#' % g)
        lines.append('')
        for it in items:
            urls = [u for u in it['urls'] if not (u in used or used.add(u))]
            if not urls:
                continue
            lines.append('%s,%s' % (it['name'].replace(',', '，'), ','.join(urls)))
            lines.append('')

    path = os.path.join(out_dir, 'TVLives.txt')
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines).rstrip('\n') + '\n')

    chans = sum(len(group_items.get(g, [])) for g in groups_order)
    total_urls = sum(len(it['urls']) for g in groups_order for it in group_items.get(g, []))
    print('  => TVLives.txt：%d 频道 / %d 组 / %d 线路 / %d bytes' % (
        chans, len([g for g in groups_order if group_items.get(g)]), total_urls,
        os.path.getsize(path)), flush=True)
    return {'file': 'TVLives.txt', 'channels': chans, 'lines': total_urls}


def build_simple(name, sources, out_dir, workers, probe_limit, max_per_source,
                 filter_fn=None, prev_content=None):
    print('\n=== 构建 %s ===' % name, flush=True)
    raw = []
    for url, ua in sources:
        try:
            got = parse_m3u(fetch(url, 30, ua))
            raw.extend(got)
            print('  拉取 %-40s %4d 条' % (url.split('/')[-1], len(got)), flush=True)
        except Exception as e:
            print('  拉取失败 %-40s %s' % (url.split('/')[-1], str(e)[:36]), flush=True)

    kept = []
    for group, n, u in raw:
        if GROUP_NOISE_RE.search(group) or AD_NAME_RE.search(n) or AD_HOST_RE.search(u):
            continue
        if STATIC_EXT_RE.search(u) or is_ipv6(u) or not norm_key(n):
            continue
        if filter_fn and not filter_fn(n, u):
            continue
        kept.append((n, u))
    if probe_limit > 0 and len(kept) > probe_limit:
        kept = kept[:probe_limit]
    alive = probe_many([u for _, u in kept], workers, name)
    alive_set = set(alive)

    by = {}
    for n, u in kept:
        if u not in alive_set:
            continue
        k = clean_name(n)
        by.setdefault(k, {'name': n, 'urls': []})
        if u not in by[k]['urls']:
            by[k]['urls'].append(u)

    # .group header is required by CI validation & client parser
    gname = 'B站直播' if name.startswith('Bili') else '直播'
    lines, used = ['%s,#genre#' % gname, ''], set()
    for k, it in by.items():
        urls = [u for u in it['urls'][:5] if not (u in used or used.add(u))]
        if urls:
            lines.append('%s,%s' % (it['name'].replace(',', '，'), ','.join(urls)))
            lines.append('')
    path = os.path.join(out_dir, name)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines).rstrip('\n') + '\n')
    print('  => %s：%d 频道 / %d bytes' % (name, len(by), os.path.getsize(path)), flush=True)
    return {'file': name, 'channels': len(by), 'lines': sum(len(v['urls']) for v in by.values())}


def build_live_sports(out_dir, workers, probe_limit):
    """赛事 M3U 聚合（本地文件，供客户端读取）"""
    print('\n=== 构建 LiveSports.txt（赛事聚合） ===', flush=True)
    raw = []
    for url in SPORTS_SOURCES:
        try:
            got = parse_m3u(fetch(url, 30, UA_PLAYER))
            raw.extend(got)
            print('  拉取 %-30s %4d 条' % (url.split('/')[-1], len(got)), flush=True)
        except Exception as e:
            print('  拉取失败 %-30s %s' % (url.split('/')[-1], str(e)[:36]), flush=True)
    kept = []
    for group, n, u in raw:
        if GROUP_NOISE_RE.search(group) or AD_NAME_RE.search(n) or AD_HOST_RE.search(u):
            continue
        if STATIC_EXT_RE.search(u) or is_ipv6(u) or not norm_key(n):
            continue
        kept.append((clean_name(n), n, u))
    if probe_limit > 0 and len(kept) > probe_limit:
        kept = kept[:probe_limit]
    alive = probe_many([u for _, _, u in kept], workers, '赛事')
    alive_set = set(alive)
    by = {}
    for k, name, u in kept:
        if u not in alive_set:
            continue
        by.setdefault(k, {'name': name, 'urls': []})
        if u not in by[k]['urls']:
            by[k]['urls'].append(u)
    lines, used = ['赛事直播,#genre#', ''], set()
    for k, it in by.items():
        urls = [u for u in it['urls'][:5] if not (u in used or used.add(u))]
        if urls:
            lines.append('%s,%s' % (it['name'].replace(',', '，'), ','.join(urls)))
            lines.append('')
    path = os.path.join(out_dir, 'LiveSports.txt')
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines).rstrip('\n') + '\n')
    print('  => LiveSports.txt：%d 频道 / %d bytes' % (len(by), os.path.getsize(path)), flush=True)
    return {'file': 'LiveSports.txt', 'channels': len(by), 'lines': sum(len(v['urls']) for v in by.values())}


def load_prev(out_dir, name):
    p = os.path.join(out_dir, name)
    if os.path.exists(p):
        try:
            with open(p, encoding='utf-8', newline='') as f:
                return f.read()
        except Exception:
            pass
    return None


def restore(out_dir, name, content):
    if content is None:
        return
    with open(os.path.join(out_dir, name), 'w', encoding='utf-8', newline='\n') as f:
        f.write(content)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-dir', default=REPO)
    ap.add_argument('--probe-limit', type=int, default=0)
    ap.add_argument('--workers', type=int, default=16)
    ap.add_argument('--max-per-source', type=int, default=400)
    ap.add_argument('--min-channels', type=int, default=40)
    args = ap.parse_args()

    with open(os.path.join(HERE, 'channel_plan.json'), encoding='utf-8') as f:
        plan = json.load(f)

    summary, failed, built = {}, [], []
    jobs = [
        ('TVLives.txt', lambda: build_tvlives(plan, args.out_dir, args.workers,
                        args.probe_limit, args.max_per_source)),
        ('BiliLive.txt', lambda: build_simple('BiliLive.txt', BILI_SOURCES, args.out_dir,
                        args.workers, args.probe_limit, args.max_per_source)),
        ('LiveSports.txt', lambda: build_live_sports(args.out_dir, args.workers, args.probe_limit)),
    ]
    for name, fn in jobs:
        prev = load_prev(args.out_dir, name)
        res = fn()
        if res['channels'] < args.min_channels:
            print('  ⚠ %s 仅 %d 频道（低于下限 %d），保留上一版' % (
                name, res['channels'], args.min_channels), flush=True)
            failed.append(name)
            restore(args.out_dir, name, prev)
            summary[name] = {'file': name, 'channels': 'kept-previous', 'kept': True}
        else:
            built.append(name)
            summary[name] = res

    print('\n=== 汇总 ===')
    for k, v in summary.items():
        print('  %-18s %s' % (k, '保留上一版' if v.get('kept') else
                              '%4d 频道 %4d 线路' % (v['channels'], v['lines'])))
    if failed:
        print('注意：%s 本次结果不足，已保留上一版' % ', '.join(failed))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
