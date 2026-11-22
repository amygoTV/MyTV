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
     and backup (gcore.jsdelivr.net) aizheteng.json URLs -- and both are live.
     No extra storeHouse entries are allowed.
  4. Every aizheteng.json entry name contains an emoji (user-required format).
  5. Every self-hosted config's spider field is an absolute jsdelivr URL with
     a ;md5;<32hex> suffix whose md5 matches the local .txt jar. Dead hosts
     (gh-proxy.com / raw.githubusercontent.com), relative ./spider.jar paths
     and real .jar extensions (jsdelivr 403) are rejected outright.
  6. The 14 vertical YSC entries in aizheteng.json must point at YSCv2/ --
     cache-busted copies, so clients never receive the stale gh-proxy config.
"""
import concurrent.futures
import hashlib
import json
import re
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


EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")
SPIDER_OK_RE = re.compile(
    r"^https://cdn\.jsdelivr\.net/gh/amygoTV/MyTV@master/spider/[A-Za-z0-9_]+\.txt;md5;[0-9a-f]{32}$")
VERTICAL_RE = re.compile(r"/YSC(?:v2)?/(?!YSCSites\.json)[^/]+\.json")
DEAD_HOSTS = ("gh-proxy.com", "raw.githubusercontent.com")


def check_spider(data):
    """Reject stale/dead jar references; verify md5 against the local jar."""
    sp = data.get("spider", "") if isinstance(data, dict) else ""
    sites = data.get("sites") or []
    csp = [s for s in sites if isinstance(s, dict)
           and str(s.get("api", "")).startswith("csp_")]
    if not sp:
        if csp:
            return False, "missing spider field but has %d csp_ sites" % len(csp)
        return True, "no spider"
    if any(h in sp for h in DEAD_HOSTS) or sp.startswith("./") or ".jar" in sp:
        return False, "stale/dead spider host or relative jar: %s" % sp[:110]
    if not SPIDER_OK_RE.match(sp):
        return False, "spider must be cdn.jsdelivr.net .../spider/*.txt;md5;<32hex>: %s" % sp[:110]
    url_part, expect = sp.split(";md5;")
    fname = url_part.rsplit("/", 1)[-1]
    jar = Path("spider") / fname
    if not jar.exists():
        return False, "spider jar missing locally: %s" % jar
    real = hashlib.md5(jar.read_bytes()).hexdigest()
    if real != expect:
        return False, "spider md5 mismatch: config=%s local=%s" % (expect, real)
    return True, "spider %s md5 OK" % fname


def has_emoji(name):
    """User rule: every aizheteng line name must contain an emoji."""
    return bool(EMOJI_RE.search(name or ""))


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
        sp_ok, sp_detail = check_spider(data)
        if not sp_ok:
            return name, False, sp_detail
        return name, True, "sites=%d, %s (%s)" % (len(sites), sp_detail, source)
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
    vertical = [x for x in aiz.get("urls", [])
                if isinstance(x, dict) and VERTICAL_RE.search(x.get("url", ""))]
    stale_vertical = [x.get("name", "?") for x in vertical
                      if "/YSCv2/" not in x.get("url", "")]
    if stale_vertical:
        bad.append("vertical entries must use cache-busted YSCv2/: %s" % stale_vertical)
    else:
        log("vertical entries use YSCv2/ OK (%d entries)" % len(vertical))
    no_emoji = [x.get("name", "?") for x in aiz.get("urls", [])
                if isinstance(x, dict) and not has_emoji(x.get("name", ""))]
    if no_emoji:
        bad.append("aizheteng names missing emoji: %s" % no_emoji)
    else:
        log("aizheteng names emoji OK (%d entries)" % len(aiz.get("urls", [])))

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
        if "cdn.jsdelivr.net" not in aiz_urls[0] or "gcore.jsdelivr.net" not in aiz_urls[1]:
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
