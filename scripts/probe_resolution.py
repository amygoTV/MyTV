#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 ffprobe 实测每条直播线路的真实分辨率，生成质量映射（URL -> 宽高/档位）。

用途：把「高清源排前面、标清源沉底」建立在实测分辨率上，而不是猜 URL 里的
hd/sd 字样（实际 441 条线路里 345 条 URL 无分辨率标识，不可靠）。

输出：scripts/resolution_map.json
  { url: {"w":1920,"h":1080,"tier":"FHD","ok":true}, ... }

档位 tier（排序优先级从高到低）:
  4K(3840+) > FHD(1920+) > HD(1280+) > SD(<1280) > UNKNOWN(失败/IPv6 未测)

用法：
    python3 scripts/probe_resolution.py                 # 全量
    python3 scripts/probe_resolution.py --workers 12
"""
import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
FFPROBE = r"C:\Users\1\AppData\Local\FluxDown\bin\ffprobe.exe"
OUT = HERE / "resolution_map.json"
DIM_RE = re.compile(r"(\d{3,5})[xX](\d{3,5})")

# 档位分值（越大越靠前）
TIER_SCORE = {"4K": 4, "FHD": 3, "HD": 2, "SD": 1, "UNKNOWN": 0}


def tier_of(w, h):
    if not w or not h:
        return "UNKNOWN"
    long_side = max(w, h)
    if long_side >= 3840:
        return "4K"
    if long_side >= 1920:
        return "FHD"
    if long_side >= 1280:
        return "HD"
    return "SD"


def probe(url):
    """返回 (url, w, h, tier, ok)。硬墙钟超时 + ffprobe 自带 rw_timeout 双保险。"""
    if url.startswith("http://["):  # IPv6 无出口，跳过
        return url, 0, 0, "UNKNOWN", False
    args = [FFPROBE, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0",
            "-analyzeduration", "2000000", "-probesize", "2000000",
            "-rw_timeout", "8000000", url]
    try:
        r = subprocess.run(args, capture_output=True, timeout=14)
        text = (r.stdout or b"").decode("utf-8", "ignore")
        m = DIM_RE.search(text)
        if m:
            w, h = int(m.group(1)), int(m.group(2))
            return url, w, h, tier_of(w, h), True
        return url, 0, 0, "UNKNOWN", False
    except Exception:
        return url, 0, 0, "UNKNOWN", False


def collect_urls():
    """从 TVLives.txt 读取去重后的所有线路 URL。"""
    seen, out = set(), []
    for line in (REPO / "TVLives.txt").read_text(encoding="utf-8-sig").splitlines():
        if not line or line.endswith("#genre#") or "," not in line:
            continue
        u = line.split(",", 1)[1].strip()
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--urls-file", help="从文件读取待测 URL 列表（每行一条）")
    ap.add_argument("--merge", action="store_true", help="并入已有结果")
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()

    if a.urls_file:
        urls = [l.strip() for l in Path(a.urls_file).read_text(encoding="utf-8").splitlines() if l.strip()]
    else:
        urls = collect_urls()
    print("[probe] 待实测 %d 条线路（IPv6 跳过）" % len(urls), flush=True)
    result = {}
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(probe, u): u for u in urls}
        for f in concurrent.futures.as_completed(futs):
            url, w, h, tier, ok = f.result()
            result[url] = {"w": w, "h": h, "tier": tier, "ok": ok}
            done += 1
            if done % 50 == 0:
                print("[probe] 进度 %d/%d" % (done, len(urls)), flush=True)

    if a.merge and OUT.exists():
        old = json.loads(OUT.read_text(encoding="utf-8"))
        old.update(result)
        result = old
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    from collections import Counter
    c = Counter(v["tier"] for v in result.values())
    print("[probe] 完成，档位分布：%s" % dict(c), flush=True)
    print("[probe] 已写入 %s" % OUT, flush=True)


if __name__ == "__main__":
    main()
