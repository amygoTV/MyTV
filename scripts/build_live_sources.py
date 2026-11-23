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
4. 广告/错台/静态录像/分组噪音过滤全部保留。
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
import live_groups
REPO = os.path.dirname(HERE)

UA_PLAYER = 'okHttp/Mursor-1.4.0.0'

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
AD_NAME_RE = re.compile(
    r'(支持作者|感谢|订阅|广告|推广|二维码|扫码|公众号|更多资源|获取资源|'
    r'请\s*user|请查看最新|请访问|请到|失效|版权|声明|免责|'
    r'列表更新时间|更新时间|维护中?|暫無|暂无主播|温馨|提示|'
    r'答疑|教程|招聘|兼职|赚钱|赚米|卖货|厂价|厂家|优惠|团购|工厂直销|'
    r'官方直播间|需求度|求购|招商|加盟|福利|抽奖|秒杀|特价|批发|货源|'
    r'下单|客服|咨询|办理|开户|彩票|贷款|回收|二手|装修|培训|招生|'
    r'年货|特卖|清仓|库存|拿货|正品|代购|微商|私信|加微信|福利彩票|'
    r'测试|測試|test|^\d+$|^\d{4}[-/]\d{1,2})', re.I)
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
    return u.split('#', 1)[0].strip()


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
    """影视轮播 / 体育频道分组：公网源每晚重新拉取并逐条实测，失效自动剔除。"""
    print('\n=== 构建 影视轮播 / 体育频道 分组 ===', flush=True)
    raw = []
    for url, ua in SPECIAL_SOURCES:
        try:
            got = parse_m3u(fetch(url, 30, ua))
            raw.extend(got)
            print('  拉取 %-40s %4d 条' % (url.split('/')[-1], len(got)), flush=True)
        except Exception as e:
            print('  拉取失败 %-40s %s' % (url.split('/')[-1], str(e)[:36]), flush=True)

    cand = []
    for group, name, url in raw:
        if GROUP_NOISE_RE.search(group) or AD_NAME_RE.search(name) or AD_HOST_RE.search(url):
            continue
        if STATIC_EXT_RE.search(url) or is_ipv6(url) or not norm_key(name):
            continue
        if is_blacklisted(url):
            continue
        if SPORTS_RE.search(name):
            cand.append(('sports', clean_name(name), url))
        elif MOVIE_RE.search(name):
            cand.append(('movie', clean_name(name), url))

    by = {}
    for kind, name, url in cand:
        key = (kind, name)
        by.setdefault(key, [])
        if url not in by[key] and len(by[key]) < 3:
            by[key].append(url)
    picks = [(kind, name, u) for (kind, name), urls in by.items() for u in urls]
    if probe_limit > 0 and len(picks) > probe_limit:
        picks = picks[:probe_limit]
    alive = set(probe_many([u for _, _, u in picks], workers, '影视/体育'))

    out = {'movie': {}, 'sports': {}}
    for kind, name, u in picks:
        if u not in alive:
            continue
        out[kind].setdefault(name, [])
        if u not in out[kind][name]:
            out[kind][name].append(u)
    print('  => 影视轮播 %d 频道 / 体育 %d 频道（公网存活 %d 条）' % (
        len(out['movie']), len(out['sports']),
        sum(1 for k in out for v in out[k].values() for u in v if not is_ipv6(u))), flush=True)
    return out


def build_tvlives(plan, special, out_dir, workers, probe_limit, max_per_source, prev_content=None):
    print('\n=== 构建 TVLives.txt（保底频道 + 参考分组） ===', flush=True)
    channels = plan['channels']

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
    for name, meta in channels.items():
        v4_all = [clean_url(u) for u in meta['ipv4'] if not is_ipv6(u)]
        alive = [u for u in v4_all if u in alive_urls]
        rest = [u for u in v4_all if u not in alive_urls]
        urls = [u for u in (alive + rest)[:3] + v6_map.get(name, [])[:2]
                if not is_blacklisted(u)]
        if len(urls) < 3:
            urls = [clean_url(u) for u in meta['ipv4'][:3] if not is_blacklisted(u)]
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
        if GROUP_NOISE_RE.search(group) or AD_NAME_RE.search(n) or AD_HOST_RE.search(u):
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
        if GROUP_NOISE_RE.search(group) or AD_NAME_RE.search(n) or AD_HOST_RE.search(u):
            continue
        if STATIC_EXT_RE.search(u) or is_ipv6(u) or not norm_key(n):
            continue
        if is_blacklisted(u):
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
    args = ap.parse_args()

    with open(os.path.join(HERE, 'channel_plan.json'), encoding='utf-8') as f:
        plan = json.load(f)

    # 影视轮播 / 体育：每晚重新拉取并实测（公网源易失效）
    special = build_special_lives(args.out_dir, args.workers, args.probe_limit)

    summary, failed, built = {}, [], []
    jobs = [
        ('TVLives.txt', lambda: build_tvlives(plan, special, args.out_dir, args.workers,
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
