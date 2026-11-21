#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Convert public platform M3U playlists (Douyin/Bilibili/Huya/...) into TVBox TXT.

Outputs:
  PlatformLive.txt  - from https://live.yang-1989.eu.org/Live.m3u
  BiliLive.txt      - from https://sub.ottiptv.cc/bililive.m3u

TVBox TXT format:
  分组名,#genre#
  频道名,地址
"""
import argparse
import html
import os
import re
import urllib.request

SOURCES = {
    "PlatformLive.txt": "https://live.yang-1989.eu.org/Live.m3u",
    "BiliLive.txt": "https://sub.ottiptv.cc/bililive.m3u",
}

ATTR_RE = re.compile(r'(\w[\w-]*)="([^"]*)"')


def fetch(url, timeout=40, tries=4):
    import time
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            last = e
            time.sleep(2)
    raise last


def parse_m3u(text):
    """Yield (group, name, url) triples from an EXTINF playlist."""
    cur = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            attrs = dict(ATTR_RE.findall(line))
            name = line.rsplit(",", 1)[-1].strip()
            cur = (attrs.get("group-title", "").strip(), html.unescape(name))
            continue
        if cur and (line.startswith("http://") or line.startswith("https://")):
            group, name = cur
            # skip maintenance / placeholder / test clips
            skip_groups = ("溫馨", "提示", "列表更新时间", "4K频道")
            skip_names = ("维护", "維護", "暂无主播", "暫無主播", "测试", "測試")
            if any(k in group for k in skip_groups) or any(k in name for k in skip_names):
                cur = None
                continue
            if name and "/v/" not in line and not line.rstrip("/").endswith(".m3u"):
                yield group or "平台直播", name, line
        cur = None


def convert(text):
    groups = {}
    for group, name, url in parse_m3u(text):
        groups.setdefault(group, [])
        # one URL per line => independent route in 影视仓
        if not any(n == name for n, _ in groups[group]):
            groups[group].append((name, url))
    if not groups:
        raise ValueError("no channels parsed")
    out = []
    for group in sorted(groups):
        out.append("%s,#genre#" % group)
        for name, url in groups[group]:
            out.append("%s,%s" % (name.replace(",", "，"), url))
    return "\n".join(out) + "\n", sum(len(v) for v in groups.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--only", default="")
    args = ap.parse_args()

    for filename, url in SOURCES.items():
        if args.only and args.only not in filename:
            continue
        print("fetching", url)
        text = fetch(url)
        body, count = convert(text)
        path = os.path.join(args.out_dir, filename)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        print("wrote %s: %d channels, %d bytes" % (path, count, len(body.encode("utf-8"))))


if __name__ == "__main__":
    main()
