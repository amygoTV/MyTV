#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""直播源分组顺序的**单一数据源**。

背景（v1.6.26 修复）：
    分组顺序先后在三个地方各写死了一份——
      * scripts/channel_plan.json 的 groups_order（计划侧，权威）
      * scripts/build_live_sources.py 的 GROUP_MAP + groups_order（构建侧）
      * scripts/validate_live_sources.py 的 GROUPS + EXTRA_GROUPS（校验侧）
    v1.6.23 给产物新增了「央视付费 / 海外频道」两组，只改了构建侧，
    校验侧没跟上 → CI 每次跑完 build 就在 validate 步骤失败，
    直播源已经连续多天没有自动更新了。

现在统一从 channel_plan.json 推导：
    * 构建侧与校验侧共用同一个映射与顺序；
    * 以后增删分组只改 channel_plan.json 一处。
"""
import json
import os

# 计划侧分组名 → 产物 TXT 里的分组名
GROUP_MAP = {
    '央视频道': '央视',
    '卫视频道': '卫视',
    '港澳台频道': '港澳台',
}

# 产物里必须出现的分组（其余分组内容为空时允许缺席）
REQUIRED_GROUPS = ('央视', '卫视', '港澳台')


def _plan_path(base_dir=None):
    if base_dir:
        return os.path.join(base_dir, 'scripts', 'channel_plan.json')
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'channel_plan.json')


def load_plan(base_dir=None):
    with open(_plan_path(base_dir), encoding='utf-8') as f:
        return json.load(f)


def to_output_name(name):
    """计划侧分组名 → 产物侧分组名（未知名字原样透传）。"""
    return GROUP_MAP.get(name, name)


def groups_order(plan=None, base_dir=None):
    """返回产物 TXT 里应有的分组顺序（已映射成产物侧名字）。

    读不到计划文件时退回保守默认值，保证脚本仍可运行。
    """
    try:
        plan = plan if plan is not None else load_plan(base_dir)
    except Exception:
        return ['央视', '卫视', '港澳台', '央视付费', '海外频道', '影视轮播', '体育频道']
    raw = plan.get('groups_order') or []
    if not raw:
        return ['央视', '卫视', '港澳台']
    return [to_output_name(g) for g in raw]


def check_order(observed, plan=None, base_dir=None):
    """校验产物里的分组顺序是否符合计划。

    规则：
      * 产物不得出现计划外的分组；
      * 产物分组必须是计划顺序的**保序子序列**（空分组允许缺席）；
      * REQUIRED_GROUPS 必须全部出现。

    返回 (errors, info)
    """
    want = groups_order(plan, base_dir)
    errors = []
    pos = 0
    for g in observed:
        if g not in want:
            errors.append('出现计划外分组 %r（计划分组：%s）' % (g, ' / '.join(want)))
            continue
        if pos < len(want) and want[pos] == g:
            pos += 1
        else:
            expected = want[pos] if pos < len(want) else '(无)'
            errors.append('分组顺序错位：%r 出现在 %r 之后（此处应为 %r）' % (g, expected, expected))
    for g in REQUIRED_GROUPS:
        if g not in observed:
            errors.append('缺少必需分组 %r' % g)
    return errors, want


# ---------------------------------------------------------------------------
# v1.6.35：频道顺序的**单一数据源**
#
# 背景：产物的频道顺序原先完全依赖 channel_plan.json 里 channels 字典的
# **插入顺序**（build 侧 for name, meta in channels.items()），而每个频道
# 自带的 order 字段被完全忽略；cctv_order / satellite_order / hktw_order
# 这些「权威顺序清单」虽然写进了计划文件，却从未被任何代码读取。
# 后果：CCTV5+ 在 channels 字典里排到了末尾（第 17 位），
#       产物里就出现在 CCTV-17 之后，而不是紧跟 CCTV-5 —— 用户反馈「说好的
#       CCTV5+ 插到 CCTV5 下面呢」就是这个原因。
#
# 现在：顺序以计划文件里的 *_order 清单为权威，channels 的 order 字段为兜底。
# ---------------------------------------------------------------------------

# 计划里的顺序清单 → 所属分组（用于把清单映射到产物分组）
ORDER_LISTS = (
    'cctv_order',      # 央视频道：央视 + CETV
    'satellite_order',  # 卫视频道
    'hktw_order',      # 港澳台频道
    'paid_order',      # 央视付费
)


def channel_order(plan=None, base_dir=None):
    """返回 {频道名: 排序序号}，权威来源是计划文件的 *_order 清单。

    * 清单里出现的频道，按清单次序排序；
    * 清单没覆盖的频道，用 channels[name]['order'] 兜底；
    * 两者都没有的，排到最后（保持相对次序）。
    """
    try:
        plan = plan if plan is not None else load_plan(base_dir)
    except Exception:
        return {}
    ch = plan.get('channels') or {}

    order = {}
    seq = 0
    for key in ORDER_LISTS:
        for name in (plan.get(key) or []):
            if name in ch and name not in order:
                order[name] = seq
                seq += 1

    # 兜底：channels 里的 order 字段
    fallback = []
    for name, meta in ch.items():
        if name in order:
            continue
        o = meta.get('order')
        fallback.append((o if isinstance(o, int) else 10 ** 6, name))
    fallback.sort()
    for _, name in fallback:
        order[name] = seq
        seq += 1
    return order


def sorted_channels(channels, plan=None, base_dir=None):
    """按权威顺序返回频道名列表。

    channels 可以是 dict（channel_plan.json 的 channels 段）。
    """
    order = channel_order(plan, base_dir)
    names = list(channels.keys())
    return sorted(names, key=lambda n: (order.get(n, 10 ** 6), names.index(n)))
