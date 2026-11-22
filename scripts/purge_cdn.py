#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Purge jsdelivr edge cache for fixed @master URLs.

Why: subscribers use a permanent @master URL. jsdelivr caches GitHub
branches at the edge (12h s-maxage) and can serve stale content. Calling
the official purge endpoint after each CI content update makes the fixed URL
reflect new content immediately (clears all jsdelivr edge providers (CF / Gcore / Fastly)).

IMPORTANT: purge is rate-limited. In CI use --changed to purge ONLY the files
that actually changed in the just-pushed commit (usually 1-3 files). Purging
all 20 paths every run triggers throttling and can leave stale caches.

Usage:
    python3 scripts/purge_cdn.py --changed        # CI: only git-diff files
    python3 scripts/purge_cdn.py                  # manual: full default list
    python3 scripts/purge_cdn.py --extra p1 p2    # add specific paths

Exit code is always 0 (purge failure only warns) so a CDN hiccup never
fails the content workflow.
"""
import argparse
import os
import subprocess
import sys
import urllib.request
from urllib.parse import quote

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
    # cache-busted aggregate config used by "王炸资源" in aizheteng.json
    "YSCv2/YSCSites.json",
    # per-site configs that aizheteng references
    "fty/api.json",
    "feimao/api.json",
    "xiaomi/api.json",
    "PG/api.json",
    "moyuer/api.json",
    "niaoshu/tongyong.json",
    # cache-busted copies used by the 14 vertical configs (old /YSC/ was stale on CDN)
    "YSCv2/短剧漫剧.json",
    "YSCv2/短剧点播.json",
    "YSCv2/漫剧点播.json",
    "YSCv2/看球赛事.json",
    "YSCv2/吃瓜看球.json",
    "YSCv2/比赛回放.json",
    "YSCv2/赛事点播.json",
    "YSCv2/一直播.json",
    "YSCv2/少儿动漫.json",
    "YSCv2/少儿动漫点播.json",
    "YSCv2/儿童启蒙.json",
    "YSCv2/小学课堂.json",
    "YSCv2/初中课堂.json",
    "YSCv2/高中课堂.json",
    # disguised spider jars (real .jar gets HTTP 403 on jsdelivr)
    "spider/fan.txt",
    "spider/fan_v2.txt",
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
    url = PURGE_BASE + quote(path)
    try:
        req = urllib.request.Request(url, method="GET",
                                     headers={"User-Agent": "mytv-purge/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", "replace")
            if resp.status == 200 and '"status":"finished"' in body.replace(" ", ""):
                # purge.jsdelivr.net throttles per-path; a throttled request
                # does NOT clear that path. Report it so CI can warn.
                if '"throttled": true' in body:
                    import re as _re
                    m = _re.search(r'"throttlingReset":\s*(\d+)', body)
                    reset = m.group(1) + "s" if m else "?"
                    return False, "throttled (reset in %s)" % reset
                return True, "ok"
            return False, "unexpected response: " + body[:120].replace("\n", " ")
    except Exception as exc:
        return False, str(exc)[:120]


def changed_files(base="HEAD~1", head="HEAD"):
    """Return repo-relative paths changed between two refs (for CI --changed)."""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", base, head],
            text=True, stderr=subprocess.DEVNULL,
        )
        return [ln.strip() for ln in out.splitlines() if ln.strip()]
    except Exception:
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extra", nargs="*", default=[])
    ap.add_argument("--changed", action="store_true",
                    help="purge only files changed in the last commit (CI mode)")
    ap.add_argument("--base", default="HEAD~1", help="git base ref for --changed")
    args = ap.parse_args()

    if args.changed:
        paths = changed_files(args.base)
        # Always include the entry indexes if any config changed: they are the
        # fixed URLs subscribers actually import.
        if paths:
            for entry in ("aizheteng.json", "zheteng.json"):
                if entry not in paths and os.path.exists(entry):
                    paths.append(entry)
        print("[purge] --changed mode: %d files from git diff" % len(paths))
    else:
        paths = list(DEFAULT_PATHS)

    for p in args.extra:
        if p not in paths:
            paths.append(p)

    # Only purge paths served from this repo via jsdelivr @master.
    paths = [p for p in paths if os.path.exists(p) and not p.startswith(".github/")]
    if not paths:
        print("[purge] no paths to purge")
        return 0

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
