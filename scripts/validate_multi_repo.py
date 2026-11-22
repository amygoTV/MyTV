#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate multi-warehouse indexes before CI commits them.

Checks (fail fast, no commit on failure):
  1. aizheteng.json / zheteng.json are strict-valid JSON (no // comments,
     no trailing commas) -- exactly what TVBox/影视仓 clients require.
  2. Every child URL in aizheteng.json still returns a strict-valid JSON
     config with a non-empty sites array. This catches the regression where
     a self-hosted config got a leading // comment and broke parsing.
  3. zheteng.json contains exactly two entries -- the primary (cdn.jsdelivr.net)
     and backup (fastly.jsdelivr.net) aizheteng.json URLs -- and both are live.
     No extra storeHouse entries are allowed.
"""
import concurrent.futures
import json
import ssl
import sys
import urllib.request
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

SSL_CTX = ssl._create_unverified_context()
UA = "okhttp/3.15"
TIMEOUT = 20


def log(msg):
    print("[validate] %s" % msg, flush=True)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=SSL_CTX) as r:
        return r.read()


def strict_json(path):
    """Load with the same strict parser the client uses."""
    text = Path(path).read_text(encoding="utf-8-sig")
    return json.loads(text)  # no strip_comments / no trailing-comma tolerance


def check_child(item):
    name, url = item.get("name", "?"), item.get("url", "")
    local = local_path_for(url)
    try:
        if local:
            # 自有仓库的配置：校验本地文件（CI 刚重建、尚未上 CDN），不受 CDN 缓存影响
            raw = Path(local).read_bytes()
            source = "local:" + local
        else:
            raw = fetch(url)
            source = "remote"
        data = json.loads(raw.decode("utf-8-sig"))
        sites = data.get("sites") if isinstance(data, dict) else None
        if not isinstance(sites, list) or not sites:
            return name, False, "no non-empty sites array (%s)" % source
        return name, True, "sites=%d (%s)" % (len(sites), source)
    except Exception as exc:
        return name, False, str(exc)[:120]


def local_path_for(url):
    """Map self-hosted CDN URLs to local repo files; return None for external."""
    import re
    # 匹配 @<任意分支或tag>/ 形式（如 @master/、@v1.4.9/）
    m = re.search(r"amygoTV/MyTV@[^/]+/(.+)$", url)
    if m:
        from urllib.parse import unquote
        return unquote(m.group(1).split("?", 1)[0])
    return None


def main():
    bad = []

    # 1) strict parse both indexes
    try:
        aiz = strict_json("aizheteng.json")
    except Exception as exc:
        log("aizheteng.json strict parse FAILED: %s" % exc)
        return 1
    log("aizheteng.json strict parse OK (%d entries)" % len(aiz.get("urls", [])))

    try:
        zhet = strict_json("zheteng.json")
    except Exception as exc:
        log("zheteng.json strict parse FAILED: %s" % exc)
        return 1
    log("zheteng.json strict parse OK (%d entries)" % len(zhet.get("storeHouse", [])))

    # 2) every aizheteng child must parse strictly online
    items = [x for x in aiz.get("urls", []) if isinstance(x, dict) and x.get("url")]
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(check_child, items))
    for name, ok, detail in results:
        log("  %-20s %s (%s)" % (name, "OK" if ok else "FAIL", detail))
        if not ok:
            bad.append("aizheteng child %s: %s" % (name, detail))

    # 3) zheteng must be exactly the primary + backup aizheteng entries
    houses = zhet.get("storeHouse", [])
    if len(houses) != 2:
        bad.append("zheteng.json must contain exactly 2 entries (got %d)" % len(houses))
    aiz_urls = [h.get("sourceUrl", "") for h in houses if isinstance(h, dict)]
    if not all("aizheteng.json" in u for u in aiz_urls):
        bad.append("zheteng.json entries must all point to aizheteng.json: %s" % aiz_urls)
    elif len(aiz_urls) == 2:
        if "cdn.jsdelivr.net" not in aiz_urls[0] or "fastly.jsdelivr.net" not in aiz_urls[1]:
            bad.append("zheteng.json primary/backup order or host mismatch: %s" % aiz_urls)
        else:
            for u in aiz_urls:
                try:
                    local = local_path_for(u)
                    raw = Path(local).read_bytes() if local and Path(local).exists() else fetch(u)
                    data = json.loads(raw.decode("utf-8-sig"))
                    if not data.get("urls"):
                        raise ValueError("empty urls")
                    log("  zheteng entry OK: %s" % u)
                except Exception as exc:
                    bad.append("zheteng entry %s: %s" % (u, str(exc)[:120]))

    if bad:
        log("VALIDATION FAILED:")
        for b in bad:
            log("  - " + b)
        return 1
    log("ALL CHECKS PASSED (%d children + primary/backup)" % len(items))
    return 0


if __name__ == "__main__":
    sys.exit(main())
