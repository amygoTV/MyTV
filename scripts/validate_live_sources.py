#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate live-source TXT files before CI commits them.

Format rules (FongMi/影视仓 official docs/LIVE.md):
  * One channel per line: ``频道名,URL``.  The comma separates the two
    columns only -- extra comma-separated addresses are ignored by clients
    (that is why "channel,url1,url2" looked like a single line).
  * Several lines for the SAME channel are written as ONE line with the
    addresses joined by ``#`` (``CCTV1,url1#url2``).  Repeating the channel
    name on several lines makes clients overwrite the entry or throw while
    building the table -- the symptom is an EMPTY live list.
  * No blank lines: a line without ``://`` is treated as a channel command.
  * Channel names must be unique inside a group.

Additional rules:
  * TVLives.txt groups: 央视频道 / 卫视频道 / 港澳台频道 / 电影频道 / 体育频道.
  * All 71 guaranteed channels in scripts/channel_plan.json must be present,
    each with >= 3 IPv4 lines.  IPv6 coverage is reported (a few HK/TW/CGTN
    channels have no public IPv6 feed) but does not block the build.
  * 电影频道 / 体育频道 may only contain NewTV channels whose names match the
    movie / sports whitelist -- no more mis-labelled channels.
  * BiliLive.txt / LiveSports.txt use the same format.
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
    """-> (groups, group_order, errors); groups[g][name] = [url, ...]"""
    groups, order, errors = {}, [], []
    cur = None
    for i, raw in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        ln = raw.strip()
        if not ln:
            errors.append("L%d 存在空行（不含 :// 的行会被客户端当频道指令行）" % i)
            continue
        if ln.endswith("#genre#"):
            cur = ln.split(",", 1)[0].strip()
            order.append(cur)
            groups.setdefault(cur, {})
            continue
        if "," not in ln:
            errors.append("L%d 缺少逗号: %s" % (i, ln[:80]))
            continue
        if cur is None:
            errors.append("L%d 缺少分组头" % i)
            continue
        name, raw_urls = ln.split(",", 1)
        urls = [u.strip() for u in raw_urls.split("#") if u.strip()]
        if not urls:
            errors.append("L%d 没有可播放地址: %s" % (i, ln[:80]))
            continue
        for u in urls:
            if not u.startswith("http"):
                errors.append("L%d URL 非法: %s" % (i, u[:80]))
            if "," in u or " " in u:
                errors.append("L%d 地址含逗号或空格: %s" % (i, u[:100]))
        key = name.strip()
        if key in groups[cur]:
            errors.append("L%d 频道名重复『%s』（客户端建表会覆盖/报错，表现为直播列表为空）"
                          % (i, key))
        groups[cur][key] = urls
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

    # 央视组 / 港澳台组顺序（频道名在组内唯一，按出现顺序比对）
    def uniq(group):
        return list(groups.get(group, {}).keys())

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
