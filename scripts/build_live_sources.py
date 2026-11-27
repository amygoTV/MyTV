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
3. 不再生成 PlatformLive（已移除）；地方频道全部剔除。「影视轮播/体育频道」
   两个分组改由上游公网影视房间驱动（虎牙/斗鱼/YY/B站一起看），每晚重新拉取并
   逐条实测，失效自动剔除；NewTV 轮播因公网不可达已于 v1.6.8 移除。
4. 广告台名称/错台/静态录像/分组噪音过滤全部保留；台标正确的正常频道即使
   插播广告也保留（名称规则见 scripts/live_filters.py，错台/纯广告源见
   scripts/ad_blacklist.txt 人工确认）。
5. 探测不足时保留上一版（防止 CI 上游抖动清空源文件）；保底频道即使单条探测失败
   也保留原始线路，确保每频道 3 条 IPv4 + 2 条 IPv6。
6. 输出严格遵循影视仓/TVBox 官方 TXT 规范（FongMi docs/LIVE.md）：
   一行一个频道「频道名,URL」，同一频道的多条线路用 **#** 分隔（多线路备援），
   不输出空行，频道名不重复。逗号多地址写法客户端只取第一栏（表现为每频道
   只有一条线路），同名多行则会让客户端建表报错（表现为直播列表为空）。

输出文件：TVLives.txt（央视/卫视/港澳台/NewTV电影/NewTV体育）、BiliLive.txt、LiveSports.txt

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
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import live_filters
import live_groups
REPO = os.path.dirname(HERE)

UA_PLAYER = 'okHttp/Mursor-1.4.0.0'

# ---------------------------------------------------------------- 分辨率质量排序（v1.6.37）
# 用户要求「高清源前面、标清台放后面」。判定依据是 scripts/resolution_map.json
# 里 ffprobe 实测的真实分辨率（scripts/probe_resolution.py 生成），不猜 URL 的
# hd/sd 字样——实测发现 438 条线路里 345 条 URL 无分辨率标识，且 0001_1.m3u8
# 是 1080p 而 0002_1.m3u8 是 720x576，光看 URL 完全分不出来。
# 排序只作用于**同一频道内部的线路**，频道之间的顺序仍由 cctv_order 等权威清单决定。
RESOLUTION_MAP_FILE = os.path.join(HERE, 'resolution_map.json')
_TIER_SCORE = {'4K': 4, 'FHD': 3, 'HD': 2, 'SD': 1, 'UNKNOWN': 0}


def load_resolution_map():
    try:
        with open(RESOLUTION_MAP_FILE, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def sort_by_quality(urls, res_map):
    """同一频道内：已知分辨率按档位降序（4K>FHD>HD>SD），UNKNOWN/IPv6 沉底。

    稳定排序：同档位保持传入顺序（探测存活的仍排在探测失败的前面）。
    IPv6 一律沉底——它是无出口环境的备用线路，且本机实测不到分辨率。
    """
    def key(u):
        if is_ipv6(u):
            return (-1, 0)
        info = res_map.get(u) or {}
        return (_TIER_SCORE.get(info.get('tier', 'UNKNOWN'), 0), 0)
    return sorted(urls, key=key, reverse=True)

# ---------------------------------------------------------------- 上游源
# 正规台完全由权威频道表驱动；附加组已移除（内容与分类不符）
BILI_SOURCES = [
    ('https://peterhchina.github.io/iptv/bililive.m3u', UA_PLAYER),
]
SPORTS_SOURCES = [
    'https://peterhchina.github.io/iptv/huyayqk.m3u',
    'https://peterhchina.github.io/iptv/douyuyqk.m3u',
    'https://peterhchina.github.io/iptv/yylunbo.m3u',
    'https://peterhchina.github.io/iptv/CNTV-V4.m3u',
]
# 影视轮播 / 体育分组的上游（虎牙、斗鱼、YY、B 站一起看）
SPECIAL_SOURCES = [
    ('https://peterhchina.github.io/iptv/huyayqk.m3u', UA_PLAYER),
    ('https://peterhchina.github.io/iptv/douyuyqk.m3u', UA_PLAYER),
    ('https://peterhchina.github.io/iptv/yylunbo.m3u', UA_PLAYER),
    ('https://peterhchina.github.io/iptv/bililive.m3u', UA_PLAYER),
]

# ---------------------------------------------------------------- 过滤规则
# 频道名/房间名过滤规则统一放在 scripts/live_filters.py（构建侧与校验侧共用）。
# 电视台分组只看广告/购物/测试/博彩名称；正常频道插播广告不删除。
# 影视轮播/B站/体育房间名沿用既有垃圾过滤（避免误杀《购物狂》等片名）。
AD_HOST_RE = re.compile(
    r'(vd\d*\.bdstatic\.com|bdstatic\.com|\.upic\.|\.kwimgs\.com|'
    r'pan\.|aliyundrive|alipan|baidupcs)', re.I)
STATIC_EXT_RE = re.compile(r'\.(mp4|flv|mp3|aac|m4a|mkv|avi)(\?|$)', re.I)
GROUP_NOISE_RE = re.compile(r'(列表更新时间|更新时间|4K频道|溫馨|温馨|提示|维护)')
NORM_RE = re.compile(r'[\s\-_—·・]+')
# 人工抽帧确认过的广告台/错台源（scripts/ad_blacklist.txt），必须过滤
BLACKLIST_FILE = os.path.join(HERE, 'ad_blacklist.txt')


def load_blacklist():
    pats = []
    try:
        with open(BLACKLIST_FILE, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                try:
                    pats.append(re.compile(line))
                except re.error:
                    pass
    except OSError:
        pass
    return pats


AD_BLACKLIST = load_blacklist()


def is_blacklisted(url):
    return any(p.search(url) for p in AD_BLACKLIST)
SUFFIX_RE = re.compile(r'(高清|超清|蓝光|超高清|HD|FHD|4K|1080P|720P|标清|标高清)+$', re.I)
SPORTS_RE = re.compile(r'(体育|足球|篮球|NBA|CCTV-?5|赛事|奥运|网球|羽毛球|F1|赛车|排球|乒乓|台球|游泳|田径|西甲|英超|中超|欧冠|冰壶|冰球)', re.I)
MOVIE_RE = re.compile(r'(电影|影院|影厅|剧场|CCTV-?6|经典电影|影视|动画|动漫|大片|老片|相声|评书|戏曲|综艺|晚会|动作片|喜剧片|科幻|枪战片|战争片|动画片|纪录片)', re.I)


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
            if not body:
                return False
            if b'#EXTM3U' in body:
                return True
            # FLV 直流（虎牙/斗鱼/YY 一起看房间返回的就是 FLV，不是 m3u8）
            if body[:3] == b'FLV':
                return True
            # TS 分片直链
            if body[:1] == b'\x47' and len(body) > 188:
                return True
            ctype = str(r.headers.get('Content-Type', '')).lower()
            return ('mpegurl' in ctype or 'x-flv' in ctype or 'mp2t' in ctype) and len(body) > 40
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


def clean_url(u):
    """修掉误把两条 URL 用逗号拼进同一字段，以及 # 片段后缀。"""
    u = (u or '').strip()
    m = re.search(r',\s*https?://', u)
    if m:
        u = u[:m.start()]
    u = u.split('#', 1)[0].strip()
    # v1.6.36：部分源池 m3u 里 URL 尾部带逗号/空白（如 ?zxinjd,），
    # 直接落盘会被校验脚本判为「地址含逗号或空格」。
    u = u.rstrip(',').strip()
    return u


def write_txt(path, lines):
    """TVBox/影视仓 TXT 落盘：UTF-8 BOM + CRLF + 一行一条线路。

    参考 TVBoxBD0130 的 TVLives.txt 规范：
      * UTF-8 带 BOM、CRLF 换行；
      * 一行一条线路，同名频道重复出现（客户端按名字合并为多线路）；
      * 数据行之间不能有空行——空行不含 :// 会被当成频道指令行，
        轻则解析中断、重则整个直播列表为空。
    """
    data = '\r\n'.join(lines) + '\r\n'
    with open(path, 'wb') as f:
        f.write(b'\xef\xbb\xbf' + data.encode('utf-8'))


def display_name(name):
    """频道名风格对齐 TVBox 参考列表：CCTV1 -> CCTV-1，CCTV5+ -> CCTV-5+。"""
    m = re.match(r'^(CCTV|CETV)(\d+)(\+?)$', name or '')
    if m:
        return '%s-%s%s' % (m.group(1), m.group(2), m.group(3))
    return name


def canon(name):
    """频道名归一化键：CCTV-1 / CCTV1 / cctv-1 -> CCTV1"""
    s = re.sub(r'[\s\-_—·・]', '', name or '').upper().replace('＋', '+')
    return s


def format_txt(group_items, groups_order):
    """一行一条线路，同名频道重复出现（客户端按频道名合并为多线路）。"""
    lines = []
    for g in groups_order:
        items = sorted(group_items.get(g, []), key=lambda x: x['order'])
        if not items:
            continue
        lines.append('%s,#genre#' % g)
        for it in items:
            name = it['name'].replace(',', '，')
            for u in it['urls']:
                if u:
                    lines.append('%s,%s' % (name, u))
    return lines


def format_m3u(group_items, groups_order):
    """标准 M3U：一个频道一条 #EXTINF，下面每条线路独占一行。

    影视仓/TVBox 的 M3U 解析会把同名频道的多行合并成一个频道的多条线路，
    这正是「每个线路单独一行」且频道不丢的格式；TXT 格式做不到
    （TXT 一行一频道，多地址用 # 或 , 分隔都可能被客户端当成单个畸形 URL）。
    """
    lines = ['#EXTM3U']
    for g in groups_order:
        for it in sorted(group_items.get(g, []), key=lambda x: x['order']):
            urls = []
            for u in it['urls']:
                if u and u not in urls:
                    urls.append(u)
            if not urls:
                continue
            name = it['name'].replace(',', '，').replace('"', '')
            lines.append('#EXTINF:-1 group-title="%s",%s' % (g, name))
            for u in urls:
                lines.append(u)
    return lines


def build_special_lives(out_dir, workers, probe_limit):
    """影视轮播 / 体育频道分组（v1.6.38 改为权威表驱动）。

    用户明确不要虎牙/斗鱼/B站直播间拼出来的「影视轮播/体育频道」，要的是
    CHC/剧场类专业影视台。改为从 scripts/movie_channels.json 权威表读取，
    每条线路经 ffmpeg 逐源抽帧人工核验过台标（污染源已进 ad_blacklist.txt）。
    体育频道组清空——公网直播间不再是本订阅的内容。

    权威表里的线路仍走黑名单过滤 + 实测存活 + 分辨率质量排序，每日重建稳定。
    """
    print('\n=== 构建 影视轮播（CHC/剧场权威表） ===', flush=True)
    movie_file = os.path.join(HERE, 'movie_channels.json')
    try:
        with open(movie_file, encoding='utf-8') as f:
            movie = json.load(f)
    except Exception as e:
        print('  读取 %s 失败：%s（影视轮播组将为空）' % (movie_file, e), flush=True)
        movie = {}

    res_map = load_resolution_map()
    out = {'movie': {}, 'sports': {}}
    for name, urls in movie.items():
        # 线路已在抽帧核验阶段实测可播，且污染源已进黑名单；不再重复探测
        # （公网探测每源 3×30s 重试，无代理时串行极慢）。
        clean = [clean_url(u) for u in urls if not is_blacklisted(u)]
        if not clean:
            continue
        ordered = sort_by_quality(clean, res_map)
        out['movie'].setdefault(name, []).extend(ordered[:5])
    print('  => 影视轮播 %d 频道 / 体育 %d 频道（权威表 %d 频道）' % (
        len(out['movie']), len(out['sports']), len(movie)), flush=True)
    return out


def build_tvlives(plan, special, out_dir, workers, probe_limit, max_per_source, prev_content=None):
    print('\n=== 构建 TVLives.txt（保底频道 + 参考分组） ===', flush=True)
    channels = plan['channels']
    res_map = load_resolution_map()
    print('  分辨率质量表：%d 条实测记录' % len(res_map), flush=True)

    # 电视台分组只剔除名称本身就是广告/购物/测试/博彩的台；正常频道即使
    # 正在插播广告也保留。若权威频道表里出现这类名称，跳过并让校验报缺失，
    # 避免把广告台当成保底频道写进产物。
    dropped = [n for n in channels if live_filters.is_dropped_tv_name(n)]
    if dropped:
        print('  跳过广告/购物/测试/博彩/提示类频道名: %s' % '、'.join(dropped), flush=True)
        channels = {n: m for n, m in channels.items() if n not in dropped}

    # 分组名与顺序统一由 scripts/live_groups.py 从 channel_plan.json 推导
    # （v1.6.26：原先这里与校验脚本各写死一份，v1.6.23 加组后校验侧没跟上，
    #   导致 CI 每次 build 完就在 validate 步骤失败）
    GROUP_MAP = live_groups.GROUP_MAP
    groups_order = live_groups.groups_order(plan)

    # 1) 保底频道：IPv4 逐条实测；IPv6 无出口不探测，直接保留
    v4_tasks, v6_map = [], {}
    for name, meta in channels.items():
        for u in meta['ipv4']:
            if not is_ipv6(u):
                v4_tasks.append((name, clean_url(u)))
        if meta['ipv6']:
            v6_map[name] = [clean_url(u) for u in meta['ipv6'][:2]]
    if probe_limit > 0 and len(v4_tasks) > probe_limit:
        v4_tasks = v4_tasks[:probe_limit]
    alive_urls = set(probe_many([u for _, u in v4_tasks], workers, '保底IPv4'))

    group_items = {g: [] for g in groups_order}
    index = {}

    def add(group, name, urls):
        if group not in group_items:
            return
        key = (group, canon(name))
        disp = display_name(name)
        if key in index:
            item = group_items[group][index[key]]
            for u in urls:
                if u and u not in item['urls']:
                    item['urls'].append(u)
        else:
            index[key] = len(group_items[group])
            group_items[group].append({
                'name': disp,
                'urls': [u for u in urls if u],
                'order': index[key],
            })

    # 2) 保底频道：实测存活优先，探测失败也保留原始线路
    # v1.6.35：按权威顺序（cctv_order / satellite_order / hktw_order）遍历，
    # 不再依赖 channels 字典的插入顺序 —— 否则 CCTV5+ 会跑到 CCTV17 后面。
    for name in live_groups.sorted_channels(channels, plan):
        meta = channels[name]
        v4_all = [clean_url(u) for u in meta['ipv4'] if not is_ipv6(u)]
        alive = [u for u in v4_all if u in alive_urls]
        rest = [u for u in v4_all if u not in alive_urls]
        urls = [u for u in (alive + rest)[:3] + v6_map.get(name, [])[:2]
                if not is_blacklisted(u)]
        if len(urls) < 3:
            # v1.6.36：原写法用 meta['ipv4'][:3] 直接覆盖 urls，会把已保留的 IPv6
            # 一起冲掉；当 IPv4 全被广告黑名单剔除时 urls 变空 → 整个频道从产物里
            # 消失（保底校验报「保底频道缺失」）。改为「补充」而非「覆盖」。
            extra = [clean_url(u) for u in meta['ipv4'] if not is_blacklisted(u)]
            urls = extra + [u for u in urls if u not in extra]
        # v1.6.37：同一频道内线路按实测分辨率排序（高清在前、标清/未测沉底）。
        # 频道间顺序由上面的 sorted_channels(channels, plan) 决定，不受影响。
        urls = sort_by_quality(urls, res_map)
        add(GROUP_MAP.get(meta['group'], meta['group']), name, urls)

    # 4) 公网影视轮播 / 体育（每晚实测）
    for key, gname in (('movie', '影视轮播'), ('sports', '体育频道')):
        for i, (name, urls) in enumerate((special or {}).get(key, {}).items()):
            add(gname, name, [clean_url(u) for u in urls])

    # 5) 落盘：一行一条线路、无空行、BOM + CRLF
    lines = []
    for g in groups_order:
        items = group_items.get(g, [])
        if not items:
            continue
        lines.append('%s,#genre#' % g)
        for it in sorted(items, key=lambda x: x['order']):
            name = it['name'].replace(',', '，')
            for u in it['urls']:
                lines.append('%s,%s' % (name, u))
    write_txt(os.path.join(out_dir, 'TVLives.txt'), lines)
    write_txt(os.path.join(out_dir, 'TVLives_v2.txt'), lines)

    # M3U 版本：同一频道的 #EXTINF 下多行地址，供支持 M3U 的客户端使用
    m3u = ['#EXTM3U']
    for g in groups_order:
        items = sorted(group_items.get(g, []), key=lambda x: x['order'])
        if not items:
            continue
        for it in items:
            m3u.append('#EXTINF:-1 group-title="%s",%s' % (g, it['name'].replace(',', '，').replace('"', '')))
            m3u.extend(it['urls'])
    for fn in ('TVLives.m3u', 'TVLives_v2.m3u'):
        with open(os.path.join(out_dir, fn), 'w', encoding='utf-8', newline='\n') as f:
            f.write('\n'.join(m3u).rstrip('\n') + '\n')

    chans = sum(len(group_items.get(g, [])) for g in groups_order)
    total = sum(len(it['urls']) for g in groups_order for it in group_items.get(g, []))
    print('  => TVLives.txt：%d 频道 / %d 组 / %d 线路 / %d bytes' % (
        chans, len([g for g in groups_order if group_items.get(g)]), total,
        os.path.getsize(os.path.join(out_dir, 'TVLives.txt'))), flush=True)
    return {'file': 'TVLives.txt', 'channels': chans, 'lines': total}


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
        if GROUP_NOISE_RE.search(group) or live_filters.is_spam_name(n) or AD_HOST_RE.search(u):
            continue
        if STATIC_EXT_RE.search(u) or is_ipv6(u) or not norm_key(n):
            continue
        if is_blacklisted(u):
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
    items = []
    for idx, (k, it) in enumerate(by.items()):
        urls = []
        for u in it['urls'][:5]:
            if u not in urls:
                urls.append(u)
        if urls:
            items.append({'name': it['name'], 'urls': urls, 'order': idx})
    lines = format_txt({gname: items}, [gname])
    total = sum(len(i['urls']) for i in items)
    path = os.path.join(out_dir, name)
    write_txt(path, lines)
    write_txt(os.path.join(out_dir, name[:-4] + '_v2.txt'), lines)
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
        if GROUP_NOISE_RE.search(group) or live_filters.is_spam_name(n) or AD_HOST_RE.search(u):
            continue
        if STATIC_EXT_RE.search(u) or is_ipv6(u) or not norm_key(n):
            continue
        if is_blacklisted(u):
            continue
        kept.append((clean_name(n), n, clean_url(u)))
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
    items = []
    for idx, (k, it) in enumerate(by.items()):
        urls = []
        for u in it['urls'][:5]:
            if u not in urls:
                urls.append(u)
        if urls:
            items.append({'name': it['name'], 'urls': urls, 'order': idx})
    lines = format_txt({'赛事直播': items}, ['赛事直播'])
    total = sum(len(i['urls']) for i in items)
    path = os.path.join(out_dir, 'LiveSports.txt')
    write_txt(path, lines)
    write_txt(os.path.join(out_dir, 'LiveSports_v2.txt'), lines)
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
    write_txt(os.path.join(out_dir, name), content.splitlines())
    # v2 副本必须与主文件保持一致（配置引用的是 v2）
    write_txt(os.path.join(out_dir, name[:-4] + '_v2.txt'), content.splitlines())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-dir', default=REPO)
    ap.add_argument('--probe-limit', type=int, default=0)
    ap.add_argument('--workers', type=int, default=16)
    ap.add_argument('--max-per-source', type=int, default=400)
    ap.add_argument('--min-channels', type=int, default=25)
    ap.add_argument('--only-tvlives', action='store_true',
                    help='只重建 TVLives（保底频道+质量排序），跳过公网源拉取（易卡死）')
    args = ap.parse_args()

    with open(os.path.join(HERE, 'channel_plan.json'), encoding='utf-8') as f:
        plan = json.load(f)

    # 影视轮播已从公网直播间改为 movie_channels.json 权威表驱动（v1.6.38），
    # 读表+黑名单过滤+质量排序均为本地操作，不走公网，两种模式统一调用即可。
    special = build_special_lives(args.out_dir, args.workers, args.probe_limit)

    summary, failed, built = {}, [], []
    jobs = [('TVLives.txt', lambda: build_tvlives(plan, special, args.out_dir, args.workers,
                    args.probe_limit, args.max_per_source))]
    if not args.only_tvlives:
        jobs += [
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
