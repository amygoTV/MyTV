#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Purge jsdelivr edge cache for fixed @master URLs.

Why: subscribers use a permanent @master URL. jsdelivr caches GitHub
branches at the edge and may serve stale content for days. Calling the
official purge endpoint after each CI content update makes the fixed URL
reflect new content immediately (clears both CF and Fastly providers).

Usage:
    python3 scripts/purge_cdn.py [--extra path1 path2 ...]

Exit code is always 0 (purge failure only warns) so a CDN hiccup never
fails the content workflow.
"""
import argparse
import sys
import urllib.request
import urllib.error

REPO = "amygoTV/MyTV"
REF = "master"
PURGE_BASE = "https://purge.jsdelivr.net/gh/%s@%s/" % (REPO, REF)

# Every path reachable from the fixed subscription URL. Purge is idempotent,
# so clearing all of them on every run is safe.
DEFAULT_PATHS = [
    # multi-repo entry points
    "zheteng.json",
    "aizheteng.json",
    # standalone interfaces users subscribe directly
    "YSCSites.json",
    "TVBoxDesktop.json",
    # per-site configs that aizheteng references
    "fty/api.json",
    "feimao/api.json",
    "xiaomi/api.json",
    "PG/api.json",
    "moyuer/api.json",
    "niaoshu/tongyong.json",
    # disguised spider jars (real .jar gets HTTP 403 on jsdelivr)
    "spider/fan.txt",
    "spider/fty.txt",
    "spider/feimao.txt",
    "spider/xiaomi.txt",
    "spider/PG.txt",
    "spider/moyuer.txt",
    "spider/Tong.txt",
    # live sources (rebuilt daily)
    "TVLives.txt",
    "BiliLive.txt",
    "LiveSports.txt",
]


def purge(path):
    url = PURGE_BASE + path
    try:
        req = urllib.request.Request(url, method="GET",
                                     headers={"User-Agent": "mytv-purge/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", "replace")
            if resp.status == 200 and '"status":"finished"' in body.replace(" ", ""):
                return True, "ok"
            return False, "unexpected response: " + body[:120].replace("\n", " ")
    except Exception as exc:
        return False, str(exc)[:120]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extra", nargs="*", default=[])
    args = ap.parse_args()

    paths = list(DEFAULT_PATHS)
    for p in args.extra:
        if p not in paths:
            paths.append(p)

    ok = 0
    failed = []
    for path in paths:
        good, msg = purge(path)
        if good:
            ok += 1
        else:
            failed.append((path, msg))
        print("[purge] %-28s %s" % (path, "OK" if good else "WARN " + msg))

    print("[purge] done: %d/%d purged" % (ok, len(paths)))
    for path, msg in failed:
        print("::warning::jsdelivr purge failed for %s: %s" % (path, msg))
    # Never fail the workflow over a CDN purge hiccup.
    return 0


if __name__ == "__main__":
    sys.exit(main())
