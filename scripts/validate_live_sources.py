#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate live-source TXT files before CI commits them.

Rules (user 2026-11-22):
  * One playable URL per line: ``channel,http://...``.  Never
    ``channel,url1,url2`` -- clients then see only a single line.
  * TVLives.txt groups: 央视频道 / 卫视频道 / 港澳台频道 / 电影频道 / 体育频道.
  * All 71 guaranteed channels in scripts/channel_plan.json must be present,
    each with >= 3 IPv4 lines.  IPv6 coverage is reported (a few HK/TW/CGTN
    channels have no public IPv6 feed) but does not block the build.
  * 电影频道 / 体育频道 may only contain NewTV channels whose names match the
    movie / sports whitelist -- no more mis-labelled channels.
  * BiliLive.txt / LiveSports.txt use the same one-URL-per-line format.
"""
import json
import re
import sys
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

GROUPS = ["央视频道", "卫视频道", "港澳台频道", "电影频道", "体育频道"]
MOVIE_KEYS = ("超级电影", "明星大片", "动作电影", "爱情喜剧", "惊悚悬疑",
              "黑莓电影", "海外剧场", "欢乐剧场", "古装剧场", "家庭剧场",
              "潮妈辣婆", "精品大剧", "东北热剧", "军旅剧场", "超级电视剧")
SPORT_KEYS = ("超级体育", "精品体育", "哒啵赛事", "哒啵电竞",
              "武搏世界", "中国功夫")
EXTRA_FILES = ("BiliLive.txt", "LiveSports.txt")
AD_RE = re.compile(r"(支持作者|请\s*user|扫码|公众号|列表更新时间|广告|维护中?)", re.I)


def log(msg):
    print("[live] %s" % msg, flush=True)


def is_v6(url):
    return url.startswith("http://[")


def parse(path):
    """-> (groups, group_order, errors)"""
    groups, order, errors = {}, [], []
    cur = None
    for i, raw in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        ln = raw.strip()
        if not ln:
            continue
        if ln.endswith("#genre#"):
            cur = ln.split(",", 1)[0].strip()
            order.append(cur)
            groups.setdefault(cur, {})
            continue
        if "," not in ln:
            errors.append("L%d 缺少逗号: %s" % (i, ln[:80]))
            continue
        name, url = ln.split(",", 1)
        if cur is None:
            errors.append("L%d 缺少分组头" % i)
            continue
        if not url.startswith("http"):
            errors.append("L%d URL 非法: %s" % (i, url[:80]))
            continue
        if "," in url or " " in url:
            errors.append("L%d 一行含多个 URL/空格: %s" % (i, url[:100]))
            continue
        groups[cur].setdefault(name.strip(), []).append(url.strip())
    return groups, order, errors


def main():
    bad, warn = [], []
    plan = json.loads(Path("scripts/channel_plan.json").read_text(encoding="utf-8"))
    guaranteed = plan["channels"]

    groups, order, errors = parse("TVLives.txt")
    bad += ["TVLives.txt " + e for e in errors]
    if order != GROUPS:
        bad.append("TVLives.txt 分组顺序 %s != %s" % (order, GROUPS))
    else:
        log("TVLives.txt 分组顺序 OK (%s)" % " / ".join(order))

    flat = {}
    for g, chans in groups.items():
        for n, urls in chans.items():
            flat.setdefault(n, []).extend(urls)

    missing = [n for n in guaranteed if n not in flat]
    if missing:
        bad.append("保底频道缺失 %d 个: %s" % (len(missing), missing[:20]))
    else:
        log("71 个保底频道全部存在")

    few4, few6 = [], []
    for n in guaranteed:
        urls = flat.get(n, [])
        v4 = [u for u in urls if not is_v6(u)]
        v6 = [u for u in urls if is_v6(u)]
        if len(v4) < 3:
            few4.append((n, len(v4)))
        if len(v6) < 2:
            few6.append((n, len(v6)))
    if few4:
        bad.append("IPv4 不足 3 条的频道 %d 个: %s" % (len(few4), few4[:20]))
    else:
        log("全部 71 个保底频道均有 >= 3 条 IPv4")
    if few6:
        warn.append("IPv6 不足 2 条的频道 %d 个（公开源确实缺失）: %s"
                    % (len(few6), few6[:20]))
    else:
        log("全部保底频道均有 >= 2 条 IPv6")

    # 央视组 / 港澳台组顺序（每行一条线路，需先按频道名去重）
    def uniq(group):
        return list(dict.fromkeys(groups.get(group, {}).keys()))

    cctv_expect = [x for x in (plan["cctv_order"] + plan["paid_order"]
                               + plan["cgtn_order"] + plan["edu_order"])
                   if x in groups.get("央视频道", {})]
    if uniq("央视频道") != cctv_expect:
        bad.append("央视组顺序与权威表不一致: %s" % uniq("央视频道")[:30])
    else:
        log("央视组顺序 OK（%d 个频道）" % len(cctv_expect))
    hktw_expect = [x for x in plan.get("hktw_order", [])
                   if x in groups.get("港澳台频道", {})]
    if uniq("港澳台频道") != hktw_expect:
        bad.append("港澳台组顺序与权威表不一致: %s" % uniq("港澳台频道"))
    else:
        log("港澳台组顺序 OK（%d 个频道）" % len(hktw_expect))

    # 广告残留（与旧 CI 内联校验一致）
    for f in ("TVLives.txt",) + EXTRA_FILES:
        if not Path(f).exists():
            continue
        for ln, line in enumerate(Path(f).read_text(encoding="utf-8-sig").splitlines(), 1):
            if AD_RE.search(line):
                bad.append("%s:%d 广告残留 %r" % (f, ln, line.strip()[:50]))

    for g, keys in (("电影频道", MOVIE_KEYS), ("体育频道", SPORT_KEYS)):
        chans = groups.get(g, {})
        if not chans:
            bad.append("%s 分组为空" % g)
            continue
        wrong = [n for n in chans
                 if not n.startswith("NewTV") or not any(k in n for k in keys)]
        if wrong:
            bad.append("%s 含名不副实的频道: %s" % (g, wrong))
        else:
            log("%s OK（%d 个 NewTV 轮播频道，名称与内容匹配）" % (g, len(chans)))

    for f in EXTRA_FILES:
        if not Path(f).exists():
            bad.append("%s 缺失" % f)
            continue
        _, order2, errs = parse(f)
        bad += ["%s %s" % (f, e) for e in errs]
        if not order2:
            bad.append("%s 缺少 #genre# 分组头" % f)
        else:
            log("%s 格式 OK（%d 组）" % (f, len(order2)))

    for w in warn:
        log("WARN " + w)
    if bad:
        log("VALIDATION FAILED:")
        for b in bad:
            log("  - " + b)
        return 1
    log("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
