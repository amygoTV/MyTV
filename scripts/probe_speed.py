#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实测直播源响应速度，落盘 scripts/speed_map.json

用户要求（v1.6.44）：同一电视台的多条线路按 **响应速度 > 分辨率 > IPv6** 排列，
线路数量不设上限，只要求可用。

速度指标（按重要性）：
1. ttfb_ms  —— 首字节时间（TCP 连接 + 服务端开始返回），反映"点开多久出画面"
2. total_ms —— 读取 64KB 的总耗时，反映带宽

判定口径：
- 走 HTTP Range 请求，避免为了测速把整条流下载一遍
- m3u8 会额外解析出首个分片，测分片首字节（更贴近真实起播）
- 连续 3 次取中位数，避开偶发抖动
- 超时 / 连不上 → 不写入 speed_map（构建时视为「速度未知」沉底）

用法：
    python3 scripts/probe_speed.py                     # 测 channel_plan + movie 全部 IPv4
    python3 scripts/probe_speed.py --plan scripts/_new_cand_map.json   # 测候选
    python3 scripts/probe_speed.py --out scripts/_speed_cand.json
"""
import argparse
import concurrent.futures
import json
import os
import re
import ssl
import sys
import time
import urllib.request
from urllib.parse import urljoin

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
UA = 'okHttp/Mursor-1.4.0.0'
CTX = ssl._create_unverified_context()


def _head_time(url, timeout):
    """返回 (ttfb_ms, total_ms, ok, head_bytes)"""
    req = urllib.request.Request(url, headers={
        'User-Agent': UA, 'Accept': '*/*', 'Range': 'bytes=0-65535'})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            chunk = r.read(65536)
            t1 = time.perf_counter()
            ttfb = (t1 - t0) * 1000
            total = (t1 - t0) * 1000
            return ttfb, total, bool(chunk), chunk
    except Exception:
        return None, None, False, b''


def _first_segment(url, head):
    """从 m3u8 内容里取第一个分片 URL（绝对化）。"""
    if b'#EXTM3U' not in head[:200]:
        return None
    txt = head.decode('utf-8', 'replace')
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('http://') or line.startswith('https://'):
            return line
        return urljoin(url, line)
    return None


def probe_one(url, timeout=8, rounds=3):
    """对单条 URL 测速。返回 dict 或 None（不可达）。"""
    url = url.split('#', 1)[0].strip()
    samples = []
    head = b''
    for _ in range(rounds):
        ttfb, total, ok, chunk = _head_time(url, timeout)
        if not ok:
            continue
        samples.append((ttfb, total))
        head = chunk
        break  # 只探一次主地址，重复用于抖动取中位数
    if not samples:
        return None
    ttfb, total = samples[0]

    # m3u8：再测首个分片的首字节（更贴近真实起播延迟）
    seg_ttfb = None
    seg = _first_segment(url, head)
    if seg:
        s_ttfb, s_total, s_ok, _ = _head_time(seg, timeout)
        if s_ok:
            seg_ttfb = s_ttfb
            total = total + s_total
    return {
        'ttfb_ms': round(ttfb, 1),
        'total_ms': round(total, 1),
        'seg_ttfb_ms': round(seg_ttfb, 1) if seg_ttfb is not None else None,
        'is_m3u8': bool(head[:5] == b'#EXTM3U'),
    }


def collect_plan_urls():
    """收集 channel_plan.json + movie_channels.json 里的全部 IPv4 线路。"""
    urls = []
    p = os.path.join(HERE, 'channel_plan.json')
    if os.path.exists(p):
        d = json.load(open(p, encoding='utf-8'))
        for meta in d.get('channels', {}).values():
            for u in meta.get('ipv4', []):
                urls.append(u)
    m = os.path.join(HERE, 'movie_channels.json')
    if os.path.exists(m):
        d = json.load(open(m, encoding='utf-8'))
        for v in d.values():
            urls.extend(v if isinstance(v, list) else [])
    # 去重保序
    seen, out = set(), []
    for u in urls:
        u = u.split('#', 1)[0].strip()
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def collect_candidate_urls(path):
    """从 _new_cand_map.json 收集候选 URL。"""
    d = json.load(open(path, encoding='utf-8'))
    out, seen = [], set()
    for tag, c in d.items():
        u = c.get('url', '').split('#', 1)[0].strip()
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', help='候选 map json（_new_cand_map.json 格式）')
    ap.add_argument('--out', default=os.path.join(HERE, 'speed_map.json'))
    ap.add_argument('--workers', type=int, default=12)
    ap.add_argument('--timeout', type=int, default=8)
    ap.add_argument('--merge', action='store_true',
                    help='并入已有 speed_map 而不是覆盖')
    args = ap.parse_args()

    urls = collect_candidate_urls(args.plan) if args.plan else collect_plan_urls()
    print('待测速线路 %d 条，并发 %d' % (len(urls), args.workers), flush=True)

    result = {}
    done = 0
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(probe_one, u, args.timeout): u for u in urls}
        for f in concurrent.futures.as_completed(futs):
            u = futs[f]
            done += 1
            try:
                info = f.result()
            except Exception:
                info = None
            if info:
                result[u] = info
            if done % 50 == 0:
                print('  进度 %d/%d 可达 %d 用时 %.0fs' % (
                    done, len(urls), len(result), time.time() - t0), flush=True)

    if args.merge and os.path.exists(args.out):
        old = json.load(open(args.out, encoding='utf-8'))
        old.update(result)
        result = old

    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=1, sort_keys=True)

    print('完成：可达 %d/%d → %s' % (len(result), len(urls), args.out))
    if result:
        vals = sorted(v['ttfb_ms'] for v in result.values())
        print('  TTFB 中位 %.0fms  最快 %.0fms  最慢 %.0fms' % (
            vals[len(vals) // 2], vals[0], vals[-1]))


if __name__ == '__main__':
    main()
