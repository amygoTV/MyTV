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
