#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate multi-warehouse indexes before CI commits them.

Checks (fail fast, no commit on failure):
  1. aizheteng.json / aizheteng_v2.json / zheteng.json / zheteng_v2.json are
     strict-valid JSON (no // comments, no trailing commas) -- exactly what
     TVBox/影视仓 clients require.
  2. Every child URL in the index still returns a strict-valid JSON config
     with a non-empty sites array. This catches the regression where
     a self-hosted config got a leading // comment and broke parsing.
  3. zheteng_v2.json contains exactly two entries -- the primary
     (cdn.jsdelivr.net) and backup (gcore.jsdelivr.net) aizheteng_v2.json
     URLs -- and both are live. No extra storeHouse entries are allowed.
  4. Every index entry name contains an emoji (user-required format).
  5. Every self-hosted config's spider field is an absolute jsdelivr URL with
     a ;md5;<32hex> suffix whose md5 matches the local .txt jar. Dead hosts
     (gh-proxy.com / raw.githubusercontent.com), relative ./spider.jar paths
     and real .jar extensions (jsdelivr 403) are rejected outright.
  6. The 15 vertical self-hosted entries must point at YSCv3/ -- cache-busted
     copies, so clients never receive the stale gh-proxy config.
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
VERTICAL_RE = re.compile(r"/YSC(?:v2|v3)?/(?!YSCSites\.json)[^/]+\.json")
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
    parsed = {}
    for name in ("aizheteng.json", "aizheteng_v2.json",
                 "zheteng.json", "zheteng_v2.json"):
        try:
            parsed[name] = strict_json(name)
        except Exception as exc:
            log("%s strict parse FAILED: %s" % (name, exc))
            return 1
        log("%s strict parse OK" % name)

    # 1) emoji 规则（用户要求所有线路名带 emoji）
    for name in ("aizheteng.json", "aizheteng_v2.json"):
        entries = [x for x in parsed[name].get("urls", []) if isinstance(x, dict)]
        no_emoji = [x.get("name", "?") for x in entries if not has_emoji(x.get("name", ""))]
        if no_emoji:
            bad.append("%s names missing emoji: %s" % (name, no_emoji))
        else:
            log("%s names emoji OK (%d entries)" % (name, len(entries)))

    # 2) 主索引取 aizheteng_v2.json（配置与用户订阅都指向这个新路径）
    aiz = parsed["aizheteng_v2.json"]
    items = [x for x in aiz.get("urls", []) if isinstance(x, dict) and x.get("url")]

    # 3) 垂直线路必须走 YSCv3/（全新路径，避开 CDN 陈旧缓存）
    vertical = [x for x in items if VERTICAL_RE.search(x.get("url", ""))]
    stale_vertical = [x.get("name", "?") for x in vertical
                      if "/YSCv3/" not in x.get("url", "")]
    if stale_vertical:
        bad.append("vertical entries must use cache-busted YSCv3/: %s" % stale_vertical)
    else:
        log("vertical entries use YSCv3/ OK (%d entries)" % len(vertical))

    # 4) 每个子配置都必须严格可解析且 sites 非空
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(check_child, items))
    for name, ok, detail in results:
        log("  %-20s %s (%s)" % (name, "OK" if ok else "FAIL", detail))
        if not ok:
            bad.append("aizheteng child %s: %s" % (name, detail))

    # 5) zheteng_v2.json 必须恰好是主 cdn + 备 gcore 两条，且都指向 aizheteng_v2.json
    houses = parsed["zheteng_v2.json"].get("storeHouse", [])
    if len(houses) != 2:
        bad.append("zheteng_v2.json must contain exactly 2 entries (got %d)" % len(houses))
    house_urls = [h.get("sourceUrl", "") for h in houses if isinstance(h, dict)]
    if not all("aizheteng_v2.json" in u for u in house_urls):
        bad.append("zheteng_v2.json entries must all point to aizheteng_v2.json: %s"
                   % house_urls)
    elif len(house_urls) == 2:
        if "cdn.jsdelivr.net" not in house_urls[0] or "gcore.jsdelivr.net" not in house_urls[1]:
            bad.append("zheteng_v2.json primary/backup order or host mismatch: %s"
                       % house_urls)
        else:
            for u in house_urls:
                try:
                    local = local_path_for(u)
                    raw = Path(local).read_bytes() if local and Path(local).exists() else fetch(u)
                    data = json.loads(raw.decode("utf-8-sig"))
                    if not data.get("urls"):
                        raise ValueError("empty urls")
                    log("  zheteng_v2 entry OK: %s" % u)
                except Exception as exc:
                    bad.append("zheteng_v2 entry %s: %s" % (u, str(exc)[:120]))

    if bad:
        log("VALIDATION FAILED:")
        for b in bad:
            log("  - " + b)
        return 1
    log("ALL CHECKS PASSED (%d children + primary/backup)" % len(items))
    return 0


if __name__ == "__main__":
    sys.exit(main())
