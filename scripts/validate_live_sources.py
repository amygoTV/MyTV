#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate live-source TXT files before CI commits them.

Format rules (aligned with the TVBoxBD0130 reference list supplied by the user):
  * UTF-8 **with BOM**, CRLF line endings.
  * ``group,#genre#`` declares a group; ``channel,url`` is one playable line.
  * The same channel may appear on several lines -- the client merges them
    into one channel with multiple lines.  This is the intended format.
  * **No blank lines between data lines.**  A line without ``://`` is treated
    as a channel command by TVBox/影视仓, so a stray blank line can abort the
    parse and leave the whole live list empty.
  * Groups: 央视 / 卫视 / 港澳台 / NewTV频道 / SITV频道 / IHOT频道 / 少儿频道.

Extra rules:
  * All guaranteed channels from scripts/channel_plan.json must be present.
  * URLs hitting scripts/ad_blacklist.txt (manually frame-audited ad / wrong
    channels) are rejected.
  * *_v2.txt copies must be byte-identical to the main file (configs point at
    the v2 path).
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import live_filters
import live_groups

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

# 分组顺序统一由 scripts/live_groups.py 从 channel_plan.json 推导
# （v1.6.26：原先这里硬编码 5 组，构建侧 v1.6.23 已扩到 7 组 → 校验必失败）
# 频道名过滤规则与构建侧共用 scripts/live_filters.py：
#   * 电视台分组只剔除广告/购物/测试/博彩名称（台标正确的正常频道保留）；
#   * 影视轮播/B站/体育房间名沿用既有垃圾过滤。
BLACKLIST_FILE = Path("scripts/ad_blacklist.txt")
FILES = ("TVLives.txt", "TVLives_v2.txt", "BiliLive.txt", "BiliLive_v2.txt",
         "LiveSports.txt", "LiveSports_v2.txt")


def log(msg):
    print("[live] %s" % msg, flush=True)


def is_v6(url):
    return url.startswith("http://[")


def canon(name):
    return re.sub(r"[\s\-_—·・]", "", name or "").upper().replace("＋", "+")


def load_blacklist():
    pats = []
    if BLACKLIST_FILE.exists():
        for line in BLACKLIST_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                pats.append(re.compile(line))
            except re.error:
                pass
    return pats


def parse(path):
    """-> (groups, group_order, errors); groups[g] = [(channel, url), ...]"""
    errors = []
    raw = Path(path).read_bytes()
    if not raw.startswith(b"\xef\xbb\xbf"):
        errors.append("缺少 UTF-8 BOM")
    text = raw.decode("utf-8-sig")
    if "\r\n" not in text:
        errors.append("未使用 CRLF 换行")
    rows = text.split("\r\n")
    last = max((i for i, l in enumerate(rows) if l.strip()), default=-1)
    for i, l in enumerate(rows):
        if not l.strip() and i < last:
            errors.append("L%d 数据行之间存在空行（会被当成频道指令行，导致列表为空）" % (i + 1))
            break
    groups, order, cur = {}, [], None
    for i, raw_line in enumerate(rows, 1):
        s = raw_line.strip()
        if not s:
            continue
        if s.endswith("#genre#"):
            cur = s.split(",", 1)[0].strip()
            order.append(cur)
            groups.setdefault(cur, [])
            continue
        if "," not in s:
            errors.append("L%d 缺少逗号: %s" % (i, s[:70]))
            continue
        if cur is None:
            errors.append("L%d 缺少分组头" % i)
            continue
        name, url = s.split(",", 1)
        url = url.strip()
        if not url.startswith("http"):
            errors.append("L%d URL 非法: %s" % (i, url[:70]))
            continue
        if "," in url or " " in url:
            errors.append("L%d 地址含逗号或空格: %s" % (i, url[:100]))
            continue
        groups[cur].append((name.strip(), url))
    return groups, order, errors


def main():
    bad, warn = [], []
    plan = json.loads(Path("scripts/channel_plan.json").read_text(encoding="utf-8"))
    guaranteed = plan["channels"]
    # 权威频道表覆盖的「电视台」分组；其余分组（影视轮播/体育/B站/赛事）
    # 的房间名走 live_filters.is_spam_name，避免把片名当广告台误杀。
    tv_groups = {live_groups.to_output_name(meta.get("group", ""))
                 for meta in guaranteed.values()}

    groups, order, errors = parse("TVLives.txt")
    bad += ["TVLives.txt " + e for e in errors]
    order_errs, want = live_groups.check_order(order, plan)
    if order_errs:
        bad += ["TVLives.txt " + e for e in order_errs]
        bad.append("TVLives.txt 实际分组顺序 %s（计划 %s）" % (order, want))
    else:
        log("TVLives.txt 分组顺序 OK (%s)" % " / ".join(order))

    flat = {}
    for g, rows in groups.items():
        for name, url in rows:
            flat.setdefault(canon(name), []).append((name, url))

    missing = [n for n in guaranteed if canon(n) not in flat]
    if missing:
        bad.append("保底频道缺失 %d 个: %s" % (len(missing), missing[:20]))
    else:
        log("71 个保底频道全部存在")

    few = []
    for n in guaranteed:
        rows = flat.get(canon(n), [])
        v4 = [u for _, u in rows if not is_v6(u)]
        if len(v4) < 3:
            few.append((n, len(v4)))
    if few:
        warn.append("IPv4 少于 3 条的频道 %d 个（已剔除广告源，不再凑数）: %s"
                    % (len(few), few[:20]))
    else:
        log("全部保底频道均有 >= 3 条 IPv4")

    blacklist = load_blacklist()
    for f in FILES:
        if not Path(f).exists():
            continue
        cur_group = None
        for ln, line in enumerate(Path(f).read_text(encoding="utf-8-sig").splitlines(), 1):
            s = line.strip()
            if not s:
                continue
            if s.endswith("#genre#"):
                cur_group = s.split(",", 1)[0].strip()
                continue
            if "," not in s:
                continue
            name, url = s.split(",", 1)
            name, url = name.strip(), url.strip()
            if cur_group in tv_groups:
                if live_filters.is_dropped_tv_name(name):
                    bad.append("%s:%d 广告/购物/测试/博彩/提示类频道名残留 %r" % (
                        f, ln, name[:50]))
            elif live_filters.is_spam_name(name):
                bad.append("%s:%d 广告/垃圾频道名残留 %r" % (f, ln, name[:50]))
            if any(p.search(url) for p in blacklist):
                bad.append("%s:%d 命中广告黑名单: %s" % (f, ln, url[:90]))
    log("广告黑名单校验完成（%d 条规则）" % len(blacklist))

    for f in FILES:
        if not Path(f).exists():
            bad.append("%s 缺失" % f)
            continue
        g2, o2, errs = parse(f)
        bad += ["%s %s" % (f, e) for e in errs]
        if not o2:
            bad.append("%s 缺少 #genre# 分组头" % f)
        else:
            log("%s 格式 OK（%d 组 / %d 行）" % (
                f, len(o2), sum(len(v) for v in g2.values())))

    for f in ("TVLives.txt", "BiliLive.txt", "LiveSports.txt"):
        v2 = Path(f[:-4] + "_v2.txt")
        if not v2.exists():
            bad.append("%s 缺失（配置引用的新路径）" % v2)
        elif v2.read_bytes() != Path(f).read_bytes():
            bad.append("%s 与 %s 内容不一致" % (v2.name, f))
        else:
            log("%s 与主文件一致（配置引用此路径）" % v2.name)

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
