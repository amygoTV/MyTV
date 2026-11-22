#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一直播源筛选流水线
=====================

流程：多上游拉取 → 解析 → 规则过滤（广告/错台/噪音）→ 逐条实测可播性
      → 频道名归一 → 同名合并多线路 → 输出 TVBox TXT（三份）

设计要点（均为实测得出）：
1. 上游源会随时失效/被拍卖，必须每次重新拉取并**逐条探测**，
   只保留真正返回 m3u8 且有内容的线路。
2. 广告台特征（实测）：
   - 频道名含「支持作者/请user查看/扫码/公众号…」等提示语
   - URL 指向静态 mp4/flv 结尾且不在白名单（春晚录像、广告位等）
   - 域名是已知广告/网盘域名（vd2.bdstatic.com 等）
3. 错台特征（实测）：同一个 URL 被多个不同台名引用 → 只保留第一个（按优先级）。
4. 同一 URL 出现在多个源 → 去重，但保留同名频道的多条不同线路。
5. 名称归一：去掉「高清/超清/HD/4K」后缀做去重键，但保留原始名显示。

用法：
    python3 scripts/build_live_sources.py                 # 全量构建
    python3 scripts/build_live_sources.py --probe-limit 60 # 快速探测（CI 快速通道）
    python3 scripts/build_live_sources.py --out-dir /tmp/x
"""
import argparse
import concurrent.futures
import html
import json
import os
import re
import ssl
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

UA_PLAYER = 'okHttp/Mursor-1.4.0.0'
UA_BROWSER = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

# ---------------------------------------------------------------- 上游源
# (输出文件, 分组名, 上游 URL)
# 实测可播率：huyayqk 94% / douyuyqk 95% / yylunbo 95% / IPTV-V4 85% / CNTV-V4 82%
# / bililive 15% / Live.m3u 0%（咪咕系全 403，已剔除）
SOURCES = [
    # TVLives：只收央视/卫视/教育台等「正规台」，上游取 CNTV-V4（央视+卫视+地方+电影）
    ('TVLives.txt', '央视', [
        ('https://peterhchina.github.io/iptv/CNTV-V4.m3u', UA_PLAYER),
    ]),
    # PlatformLive：综合台（地方/电影/纪录/春晚/儿童等），上游取 IPTV-V4
    ('PlatformLive.txt', '综合', [
        ('https://peterhchina.github.io/iptv/IPTV-V4.m3u', UA_PLAYER),
    ]),
    ('BiliLive.txt', 'B站', [
        ('https://peterhchina.github.io/iptv/bililive.m3u', UA_PLAYER),
    ]),
]

# 央视/卫视「保底线路」：上游源缺失 CCTV6 等频道时用（实测这几条长期可播）
BACKUP_CCTV = {
    'CCTV1':  ['http://74.91.26.218:82/live/cctv1hd.m3u8'],
    'CCTV2':  ['http://192.151.150.154/live/cctv2hd.m3u8',
               'http://74.91.26.218:82/live/cctv2hd.m3u8',
               'http://204.12.221.218:8181/3m1080p/cctv2.m3u8'],
    'CCTV3':  ['http://107.150.60.122/live/cctv3hd.m3u8',
               'http://74.91.26.218:82/live/cctv3hd.m3u8',
               'http://63.141.230.178:82/gslb/zbdq5.m3u8?id=cctv3hd'],
    'CCTV4':  ['http://74.91.26.218:82/live/cctv4hd.m3u8',
               'http://107.150.60.122/live/cctv4hd.m3u8'],
    'CCTV5':  ['http://107.150.60.122/live/cctv5hd.m3u8'],
    'CCTV6':  ['http://74.91.26.218:82/live/cctv6hd.m3u8',
               'http://107.150.60.122/live/cctv6hd.m3u8',
               'http://63.141.230.178:82/gslb/zbdq5.m3u8?id=cctv6hd',
               'http://192.151.150.154/live/cctv6hd.m3u8',
               'http://204.12.221.218:8181/3m1080p/cctv6.m3u8'],
    'CCTV7':  ['http://74.91.26.218:82/live/cctv7hd.m3u8',
               'http://107.150.60.122/live/cctv7hd.m3u8',
               'http://63.141.230.178:82/gslb/zbdq5.m3u8?id=cctv7hd'],
    'CCTV8':  ['http://74.91.26.218:82/live/cctv8hd.m3u8',
               'http://63.141.230.178:82/gslb/zbdq5.m3u8?id=cctv8hd'],
    'CCTV9':  ['http://107.150.60.122/live/cctv9hd.m3u8',
               'http://192.151.150.154/live/cctv9hd.m3u8',
               'http://74.91.26.218:82/live/cctv9hd.m3u8'],
    'CCTV11': ['http://74.91.26.218:82/live/cctv11hd.m3u8',
               'http://63.141.230.178:82/gslb/zbdq5.m3u8?id=cctv11hd'],
    'CCTV12': ['http://74.91.26.218:82/live/cctv12hd.m3u8',
               'http://63.141.230.178:82/gslb/zbdq5.m3u8?id=cctv12hd'],
    'CCTV13': ['http://74.91.26.218:82/live/cctv13hd.m3u8',
               'http://63.141.230.178:82/gslb/zbdq5.m3u8?id=cctv13hd'],
    'CCTV14': ['http://74.91.26.218:82/live/cctv14hd.m3u8',
               'http://63.141.230.178:82/gslb/zbdq5.m3u8?id=cctv14hd'],
    'CCTV15': ['http://74.91.26.218:82/live/cctv15hd.m3u8',
               'http://63.141.230.178:82/gslb/zbdq5.m3u8?id=cctv15hd'],
    'CCTV17': ['http://74.91.26.218:82/live/cctv17hd.m3u8',
               'http://63.141.230.178:82/gslb/zbdq5.m3u8?id=cctv17hd'],
    'CETV1':  ['http://38.75.136.137:98/gslb/dsdqpub/cetv1hd.m3u8?auth=testpub',
               'http://198.204.228.26/live/cetv1hd.m3u8'],
    'CETV3':  ['http://107.150.60.122/live/cetv3.m3u8'],
    '东方卫视': ['http://bp-resource-dfl.bestv.cn/148/3/video.m3u8'],
    '湖南卫视': ['http://hlsal-ldvt.qing.mgtv.com/nn_live/nn_x64/'
                 'Y2RuZXhfaWQ9YWxfaGxzX2xkdnQmZT02OTE0NjA0JnY9MSZpZD1ITldTWkdTVCZzPTcwN2RiYTc2YzJjNmJmMTQ4MmUyZGYzOWU2NWM3YWFi/'
                 'HNWSZGST.m3u8'],
    '浙江卫视': ['http://ali-xwl.cztv.com/live/channel011080Plxw.m3u8'],
}

# ---------------------------------------------------------------- 过滤规则

# 广告/提示类频道名
AD_NAME_RE = re.compile(
    r'(支持作者|感谢|订阅|广告|推广|二维码|扫码|公众号|更多资源|获取资源|'
    r'请\s*user|请查看最新|请访问|请到|失效|版权|声明|免责|'
    r'列表更新时间|更新时间|维护中?|暫無|暂无主播|温馨|提示|'
    r'测试|測試|test|^\d+$|^\d{4}[-/]\d{1,2})', re.I)

# 已知广告/网盘/图床域名
AD_HOST_RE = re.compile(
    r'(vd\d*\.bdstatic\.com|bdstatic\.com|\.upic\.|\.kwimgs\.com|'
    r'pan\.|aliyundrive|alipan|baidupcs)', re.I)

# 静态媒体（录像/广告位）——不当作直播流
STATIC_EXT_RE = re.compile(r'\.(mp4|flv|mp3|aac|m4a|mkv|avi)(\?|$)', re.I)

# 常见分组噪音
GROUP_NOISE_RE = re.compile(r'(列表更新时间|更新时间|4K频道|溫馨|温馨|提示|维护)')

# 名称归一（去重键）
NORM_RE = re.compile(r'[\s\-_—·・]+')
SUFFIX_RE = re.compile(r'(高清|超清|蓝光|超高清|HD|FHD|4K|1080P|720P|标清|标高清)+$', re.I)


def norm_key(name):
    """归一化频道名用于去重：去空白/连字符、去画质后缀、统一 CCTV-6→CCTV6。"""
    s = NORM_RE.sub('', html.unescape(name or '')).upper()
    s = SUFFIX_RE.sub('', s)
    # CCTV-6 / CCTV 6 / CCTV6 → CCTV6；CETV-1 → CETV1
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
            time.sleep(1.5)
    raise last


ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')


def parse_m3u(text):
    """-> [(group, name, url)]"""
    out = []
    group = ''
    name = ''
    tvg = ''
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
            # tvg-name 通常比显示名更规范，优先用它做名称（实测上游显示名常带画质后缀）
            disp = tvg or name
            out.append((group, disp, line))
    return out


def playable(url, timeout=8):
    """实测：是否真的返回 m3u8 内容。"""
    if is_ipv6(url):
        return False
    req = urllib.request.Request(url, headers={
        'User-Agent': UA_PLAYER, 'Accept': '*/*', 'Range': 'bytes=0-8191'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status not in (200, 206):
                return False
            body = r.read(8192)
            if b'#EXTM3U' in body:
                return True
            ct = str(r.headers.get('Content-Type', '')).lower()
            # 无扩展名但 content-type 是 mpegurl 也算
            return ('mpegurl' in ct) and len(body) > 40
    except Exception:
        return False


def build_one(out_name, sources, backup, out_dir, probe_limit, workers):
    print('\n=== 构建 %s ===' % out_name, flush=True)
    raw = []
    for url, ua in sources:
        try:
            txt = fetch(url, 30, ua)
            got = parse_m3u(txt)
            raw.extend(got)
            print('  拉取 %-58s %4d 条' % (url.split('/')[-1], len(got)), flush=True)
        except Exception as e:
            print('  拉取失败 %-58s %s' % (url.split('/')[-1], str(e)[:40]), flush=True)

    # 规则过滤
    kept = []
    dropped = collections.Counter() if False else {}
    dropped = {}
    for group, name, url in raw:
        if GROUP_NOISE_RE.search(group or ''):
            dropped['分组噪音'] = dropped.get('分组噪音', 0) + 1
            continue
        if AD_NAME_RE.search(name or ''):
            dropped['广告台名'] = dropped.get('广告台名', 0) + 1
            continue
        if AD_HOST_RE.search(url):
            dropped['广告域名'] = dropped.get('广告域名', 0) + 1
            continue
        if STATIC_EXT_RE.search(url):
            dropped['静态录像'] = dropped.get('静态录像', 0) + 1
            continue
        if not norm_key(name):
            dropped['空名称'] = dropped.get('空名称', 0) + 1
            continue
        kept.append((group, name, url))

    # 补保底线路（央视/卫视）
    for ch, urls in (backup or {}).items():
        g = '央视频道' if re.match(r'^(CCTV|CETV)', ch, re.I) else '卫视频道'
        for u in urls:
            kept.append((g, ch, u))

    # URL 去重 + 错台检测
    # 关键：同一 URL 若被标注为不同台名，说明上游存在「一条流多台名」的错台
    # （实测「浙江民生」与「浙江民生休闲」、「绍兴电视台公共」与「绍兴公共」
    #   都指向同一条流）。播放器里出现两个名字播同一个台，就是用户说的「源对不上」。
    # 保留优先级：保底线路(央视频道/卫视频道) > 上游首个出现。
    def alias_key(n):
        """台名别名归一：去掉地域修饰后的通用后缀，用于判断是否同一台。
        实测「浙江民生」vs「浙江民生休闲」、「玛纳斯」vs「玛纳斯综合」、
             「绍兴电视台公共」vs「绍兴公共」都是同一台的两个叫法。"""
        s = NORM_RE.sub('', n).upper()
        s = re.sub(r'(高清|超清|蓝光|超高清|HD|FHD|4K|1080P|720P|标清)+', '', s)
        a = re.sub(r'(电视台|频道|卫视|综合|休闲|台)$', '', s)
        return a or s

    def flow_key(u):
        """同一流的判定键：域名 + 路径（去掉查询串与末尾斜杠）。"""
        p = re.sub(r'[?#].*$', '', u).rstrip('/')
        return p.lower()

    seen_url = {}
    uniq = []
    dropped['重复URL'] = 0
    for group, name, url in kept:
        if url in seen_url:
            prev_name = seen_url[url]
            if alias_key(prev_name) == alias_key(name):
                dropped['重复URL'] = dropped.get('重复URL', 0) + 1
            else:
                # 错台：同一流被标成两个不同台名，只保留优先级高的
                dropped['错台'] = dropped.get('错台', 0) + 1
                is_backup_new = group in ('央视频道', '卫视频道')
                is_backup_old = seen_url[url] in ('央视频道', '卫视频道')
                if is_backup_new and not is_backup_old:
                    uniq = [(g, n, u) for (g, n, u) in uniq if u != url]
                    seen_url[url] = name
                    uniq.append((group, name, url))
            continue
        seen_url[url] = name
        uniq.append((group, name, url))

    # 第二轮：URL 不同但去掉查询串后相同，且台名互为别名 → 也是错台
    by_flow = {}
    for idx, (g, n, u) in enumerate(uniq):
        by_flow.setdefault(flow_key(u), []).append(idx)
    drop_idx = set()
    for fk, idxs in by_flow.items():
        if len(idxs) < 2:
            continue
        names = [uniq[i][1] for i in idxs]
        keys = [alias_key(x) for x in names]
        if len(set(keys)) == 1:      # 互为别名 → 只留第一个
            for i in idxs[1:]:
                drop_idx.add(i)
                dropped['错台'] = dropped.get('错台', 0) + 1
    if drop_idx:
        uniq = [x for i, x in enumerate(uniq) if i not in drop_idx]
    print('  过滤后 %d 条（丢弃 %s）' % (
        len(uniq), ' '.join('%s%d' % (k, v) for k, v in sorted(dropped.items()))), flush=True)

    # 逐条实测可播性
    limit = len(uniq) if probe_limit <= 0 else min(probe_limit, len(uniq))
    sample = uniq[:limit]
    print('  探测 %d 条（并发 %d）…' % (len(sample), workers), flush=True)
    alive = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(playable, u): (g, n, u) for (g, n, u) in sample}
        done = 0
        for f in concurrent.futures.as_completed(futs):
            g, n, u = futs[f]
            done += 1
            try:
                if f.result():
                    alive.append((g, n, u))
            except Exception:
                pass
            if done % 100 == 0:
                print('    探测 %d/%d，可用 %d' % (done, len(sample), len(alive)), flush=True)
    print('  可播 %d / %d' % (len(alive), len(sample)), flush=True)

    # 错台已在 URL 去重阶段处理（同一流只保留一个台名）。
# 这里再做一次「完全同名不同 URL」的兜底：不同线路但台名相同 → 合并为多线路（正常）。

    # 错台已在 URL 去重阶段处理（同一流只保留一个台名）

    # 按归一化名称合并多线路
    # 优先保留「保底线路」的规范台名与分组（央视频道/卫视频道），
    # 其次保留上游 tvg-name；画质后缀名（如 CCTV6HD）统一用规范名。
    merged = {}
    order = []
    for g, n, u in alive:
        key = norm_key(n)
        if key not in merged:
            merged[key] = {'name': n, 'urls': [], 'group': g, 'backup': g in ('央视频道', '卫视频道')}
            order.append(key)
        else:
            cur = merged[key]
            if not cur['backup'] and g in ('央视频道', '卫视频道'):
                cur['name'] = n
                cur['group'] = g
                cur['backup'] = True
            elif cur['name'] != n and len(cur['name']) > len(n):
                cur['name'] = n
        if u not in merged[key]['urls']:
            merged[key]['urls'].append(u)

    # 分组输出
    groups = {}
    for key in order:
        it = merged[key]
        g = (it['group'] or '其它频道').strip() or '其它频道'
        groups.setdefault(g, []).append(it)

    lines = []
    for g, items in groups.items():
        lines.append('%s,#genre#' % g)
        lines.append('')
        for it in items:
            lines.append('%s,%s' % (it['name'].replace(',', '，'),
                                    ','.join(it['urls'][:5])))
            lines.append('')
    path = os.path.join(out_dir, out_name)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines))
    print('  => %s：%d 频道 / %d 组 / %d 线路 / %d bytes' % (
        out_name, len(order), len(groups),
        sum(len(v['urls']) for v in merged.values()), os.path.getsize(path)), flush=True)
    return {'file': out_name, 'channels': len(order), 'groups': len(groups),
            'lines': sum(len(v['urls']) for v in merged.values())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-dir', default=REPO)
    ap.add_argument('--probe-limit', type=int, default=0,
                    help='每个文件最多探测多少条（0=全部）；CI 快速通道用小值')
    ap.add_argument('--workers', type=int, default=16)
    ap.add_argument('--only', default='')
    args = ap.parse_args()

    summary = {}
    for out_name, default_group, sources in SOURCES:
        if args.only and args.only not in out_name:
            continue
        # 保底线路只加到 TVLives（正规台），PlatformLive/BiliLive 不加
        backup = BACKUP_CCTV if out_name == 'TVLives.txt' else {}
        summary[out_name] = build_one(out_name, sources, backup, args.out_dir,
                                      args.probe_limit, args.workers)
    print('\n=== 汇总 ===')
    for k, v in summary.items():
        print('  %-18s %4d 频道  %4d 线路' % (k, v['channels'], v['lines']))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
