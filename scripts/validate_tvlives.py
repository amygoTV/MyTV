#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate a TVBox TXT playlist and keep only working stream URLs.

Input format:
    group,#genre#
    channel,url

The script probes every URL concurrently and writes a cleaned TXT file.
Channels without any valid URL are dropped. Valid URLs are sorted by latency.
Standard library only.
"""

import argparse
import concurrent.futures
import json
import os
import re
import sys
import time
import urllib.request
from urllib.parse import urlparse

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MyTV-Validator/1.0"

DISPLAY_GROUPS = ("央视", "卫视", "港澳台", "央视付费")
GROUP_ALIASES = {
    "央视频道": "央视",
    "卫视频道": "卫视",
    "港澳台频道": "港澳台",
    "央视付费频道": "央视付费",
}

GOODTV_RE = re.compile(r"(good\s*tv|好电视)", re.I)
BAD_SOURCE_RE = re.compile(r"(voc\.com\.cn|mgtv\.com)", re.I)
VOD_EXT_RE = re.compile(r"\.(mp4|mkv|avi|mov|webm|wmv|m4v)(\?|$)", re.I)
DEFAULT_AD_BLACKLIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ad_blacklist.txt")
# IPv6 字面量地址用方括号包裹，例如 http://[2409:8087:8:21::18]:6610/...
IPV6_URL_RE = re.compile(r"^https?://\[[0-9a-fA-F:]+\]", re.I)
# 本机与 GitHub Actions runner 通常没有 IPv6 出口，无法用 HTTP 探测验证这类源。
# 它们来自运营商 IPTV（移动/联通/银河），作为备用线路直接保留，排在已验活的 IPv4 之后。
IPV6_FALLBACK_LATENCY = 10 ** 9


def log(message):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), message))


def load_ad_patterns(path):
    patterns = []
    if not path or not os.path.exists(path):
        return patterns
    with open(path, "r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            patterns.append(re.compile(line, re.I))
    return patterns


def parse_txt(path, ad_patterns=()):
    items = []
    seen = set()
    group = ""
    with open(path, "r", encoding="utf-8-sig") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line.endswith(",#genre#"):
                group = re.sub(r"\s+", " ", line[:-8]).strip()
                group = GROUP_ALIASES.get(group, group)
                continue
            if "," not in line:
                continue
            name, url = line.split(",", 1)
            name = re.sub(r"\s+", " ", name).strip()
            url = url.strip()
            if not name or not url:
                continue
            if group not in DISPLAY_GROUPS:
                continue
            if GOODTV_RE.search(name) or GOODTV_RE.search(group) or GOODTV_RE.search(url):
                continue
            if BAD_SOURCE_RE.search(url):
                continue
            if any(pattern.search(url) or pattern.search(name) for pattern in ad_patterns):
                continue
            if VOD_EXT_RE.search(url):
                continue
            key = (group, name, url)
            if key in seen:
                continue
            seen.add(key)
            items.append((group, name, url))
    return items


def probe(url, timeout):
    """Return (url, latency_ms) only when the URL responds with stream media."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None
    start = time.time()
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Range": "bytes=0-2047",
        "Accept": "*/*",
        "Connection": "close",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            content_type = (resp.headers.get("Content-Type") or "").lower()
            head = resp.read(1024)
    except Exception:
        return None
    if status not in (200, 206) or not head:
        return None

    body = head.lstrip()
    is_m3u = body[:7].upper() == b"#EXTM3U" or "mpegurl" in content_type
    is_video = (
        content_type.startswith("video/")
        or "application/octet-stream" in content_type
        or body[:4] in (b"\x00\x00\x01\xba", b"\x00\x00\x01\xbb")
        or body[:3] == b"FLV"
    )
    if not is_m3u and not is_video:
        return None
    return url, int((time.time() - start) * 1000)


def is_ipv6_url(url):
    return bool(IPV6_URL_RE.match(url))


def validate(items, workers, timeout, ipv6_mode="fallback", max_ipv6=6):
    """Validate URLs. IPv6 literals are kept as fallback sources without probing.

    Most build hosts have no IPv6 egress (or a proxy that rejects IPv6 literals),
    so probing them always fails.  With ipv6_mode='fallback' they are retained
    after all successfully probed IPv4 sources; with 'drop' they are discarded;
    with 'only' only IPv6 sources are retained.
    """
    valid = {}
    failed = {}
    ipv6_counter = {}
    probe_items = []
    for group, name, url in items:
        key = (group, name)
        if is_ipv6_url(url):
            if ipv6_mode == "drop":
                failed.setdefault(key, []).append(url)
            elif ipv6_mode == "only":
                valid.setdefault(key, []).append((IPV6_FALLBACK_LATENCY, url))
            else:  # fallback
                count = ipv6_counter.get(key, 0)
                if count < max_ipv6:
                    valid.setdefault(key, []).append((IPV6_FALLBACK_LATENCY + count, url))
                    ipv6_counter[key] = count + 1
            continue
        if ipv6_mode == "only":
            failed.setdefault(key, []).append(url)
            continue
        probe_items.append((group, name, url))

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for group, name, url in probe_items:
            future = pool.submit(probe, url, timeout)
            futures[future] = (group, name, url)
        total = len(futures)
        done = 0
        for future in concurrent.futures.as_completed(futures):
            group, name, url = futures[future]
            done += 1
            if done % 200 == 0:
                log("checked %d/%d" % (done, total))
            try:
                result = future.result()
            except Exception:
                result = None
            key = (group, name)
            if result:
                valid.setdefault(key, []).append((result[1], result[0]))
            else:
                failed.setdefault(key, []).append(url)
    for key in valid:
        valid[key].sort(key=lambda pair: (pair[0], pair[1]))
        unique = []
        seen = set()
        for ms, url in valid[key]:
            if url in seen:
                continue
            seen.add(url)
            unique.append((ms, url))
        valid[key] = unique
    return valid, failed


def write_txt(path, valid, max_urls, key_order, ipv6_min=2):
    ordered = list(key_order)
    for key in valid:
        if key not in ordered:
            ordered.append(key)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for group in DISPLAY_GROUPS:
            keys = [key for key in ordered if key[0] == group and key in valid]
            if not keys:
                continue
            handle.write("%s,#genre#\n\n" % group)
            for key in keys:
                _, name = key
                ipv4 = [(ms, url) for ms, url in valid[key] if not is_ipv6_url(url)]
                ipv6 = [(ms, url) for ms, url in valid[key] if is_ipv6_url(url)]
                ipv6_take = min(len(ipv6), ipv6_min)
                ipv4_take = min(len(ipv4), max_urls - ipv6_take)
                selected = ipv4[:ipv4_take] + ipv6[:ipv6_take]
                remain = max_urls - len(selected)
                if remain > 0 and ipv6_take < len(ipv6):
                    selected += ipv6[ipv6_take:ipv6_take + remain]
                seen = set()
                for _, url in selected:
                    if url in seen:
                        continue
                    seen.add(url)
                    handle.write("%s,%s\n" % (name, url))
                handle.write("\n")


def main():
    parser = argparse.ArgumentParser(description="Validate TVBox TXT and keep only working URLs")
    parser.add_argument("inputs", nargs="+", help="input TVBox TXT files")
    parser.add_argument("-o", "--output", help="output TXT file (default: overwrite input)")
    parser.add_argument("--report", help="optional JSON report path")
    parser.add_argument("--ad-blacklist", default=DEFAULT_AD_BLACKLIST,
                        help="regex file for manually confirmed ad/wrong-channel sources")
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument("--timeout", type=int, default=8)
    parser.add_argument("--max-urls", type=int, default=10)
    parser.add_argument("--min-total-urls", type=int, default=40)
    parser.add_argument("--min-channels", type=int, default=20)
    parser.add_argument("--ipv6-mode", choices=("fallback", "drop", "only"), default="fallback",
                        help="how to treat IPv6 literal URLs (default: keep as fallback)")
    parser.add_argument("--max-ipv6", type=int, default=6,
                        help="max fallback IPv6 URLs per channel (default: 6)")
    parser.add_argument("--ipv6-min", type=int, default=2,
                        help="min IPv6 URLs kept per channel when available (default: 2)")
    args = parser.parse_args()

    output = args.output or args.inputs[0]
    ad_patterns = load_ad_patterns(args.ad_blacklist)
    log("ad blacklist rules: %d" % len(ad_patterns))
    items = []
    for path in args.inputs:
        items.extend(parse_txt(path, ad_patterns))
    log("candidate urls: %d / channels: %d" % (
        len(items), len(set((group, name) for group, name, _ in items))
    ))
    if not items:
        raise SystemExit("no candidate URLs found")

    valid, failed = validate(items, args.workers, args.timeout,
                             ipv6_mode=args.ipv6_mode, max_ipv6=args.max_ipv6)
    total_urls = sum(len(value) for value in valid.values())
    ipv6_urls = sum(1 for value in valid.values() for _, url in value if is_ipv6_url(url))
    log("valid urls: %d / valid channels: %d / ipv6 fallback: %d"
        % (total_urls, len(valid), ipv6_urls))
    if total_urls < args.min_total_urls or len(valid) < args.min_channels:
        raise SystemExit(
            "validation result too small (%d urls, %d channels); refuse to overwrite %s"
            % (total_urls, len(valid), output)
        )

    key_order = []
    for group, name, _ in items:
        key = (group, name)
        if key not in key_order:
            key_order.append(key)
    write_txt(output, valid, args.max_urls, key_order, ipv6_min=args.ipv6_min)

    if args.report:
        report = {
            "inputs": args.inputs,
            "output": output,
            "candidate_urls": len(items),
            "candidate_channels": len(set((group, name) for group, name, _ in items)),
            "valid_urls": total_urls,
            "valid_channels": len(valid),
            "kept_urls": sum(min(len(value), args.max_urls) for value in valid.values()),
            "valid": {
                "%s|%s" % key: [url for _, url in value]
                for key, value in valid.items()
            },
            "failed": {
                "%s|%s" % key: urls
                for key, urls in failed.items()
            },
        }
        with open(args.report, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)

    dropped = sorted(set(failed) - set(valid))
    if dropped:
        log("dropped channels without valid URL: %d" % len(dropped))
    log("written: %s" % output)


if __name__ == "__main__":
    main()
