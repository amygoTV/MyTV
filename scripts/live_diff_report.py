"""直播源自动重建的**变更报告**生成器。

Action 每天重建后，把「这次到底改了什么」算出来，输出到
$GITHUB_STEP_SUMMARY（GitHub Actions 页面直接可见），并可选写进
commit message 的简短统计。

用法：
    python3 scripts/live_diff_report.py --old HEAD --new . [--format markdown|text]
    python3 scripts/live_diff_report.py --old HEAD --new . --summary-file /tmp/s.txt

对比对象是重建产物与 git HEAD 中的旧版本，支持 TXT 与 M3U 两种格式。
"""
import argparse
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 需要纳入报告的文件：(显示名, 旧版路径, 新版路径)
TARGETS = [
    ('直播源(TXT)', 'TVLives.txt', 'TVLives.txt'),
    ('直播源(M3U)', 'TVLives.m3u', 'TVLives.m3u'),
    ('B站直播', 'BiliLive.txt', 'BiliLive.txt'),
    ('体育直播', 'LiveSports.txt', 'LiveSports.txt'),
]


def read_old(path, rev):
    """取 git rev 里的文件内容；取不到返回 None。"""
    try:
        r = subprocess.run(['git', 'show', '%s:%s' % (rev, path)],
                           capture_output=True, cwd=ROOT)
        if r.returncode == 0:
            return r.stdout.decode('utf-8', 'ignore')
    except Exception:
        pass
    return None


def read_new(path):
    p = os.path.join(ROOT, path)
    if not os.path.exists(p):
        return None
    with open(p, 'rb') as f:
        return f.read().decode('utf-8', 'ignore')


def parse(text, is_m3u):
    """返回 (分组, {频道名: [线路, ...]})。"""
    groups = []
    data = {}
    cur_group = ''
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith('#EXTM3U'):
            continue
        if s.endswith(',#genre#'):
            cur_group = s[:-len(',#genre#')]
            if cur_group not in groups:
                groups.append(cur_group)
            continue
        if s.startswith('#EXTINF'):
            name = s.rsplit(',', 1)[1].strip() if ',' in s else s
            data.setdefault(name, [])
            cur_name = name
            continue
        if s.startswith('#'):
            continue
        if is_m3u:
            # URL 独占一行，频道名来自上一条 EXTINF
            name = cur_name if 'cur_name' in dir() else ''
            if name:
                data[name].append(s)
            continue
        if ',' in s:
            name, url = s.split(',', 1)
            name = name.strip()
            data.setdefault(name, []).append(url.strip())
            cur_name = name
    return groups, data


def diff_one(old_text, new_text, is_m3u):
    """返回单个文件的变更字典。"""
    og, od = parse(old_text, is_m3u)
    ng, nd = parse(new_text, is_m3u)
    added = [c for c in nd if c not in od]
    removed = [c for c in od if c not in nd]
    changed = []
    for c in nd:
        if c not in od:
            continue
        o = set(od[c])
        n = set(nd[c])
        if o != n:
            changed.append((c, sorted(n - o), sorted(o - n)))
    return {
        'old_groups': og, 'new_groups': ng,
        'old_ch': len(od), 'new_ch': len(nd),
        'old_lines': sum(len(v) for v in od.values()),
        'new_lines': sum(len(v) for v in nd.values()),
        'added': added, 'removed': removed, 'changed': changed,
    }


def fmt_markdown(d, name):
    L = []
    L.append('### %s' % name)
    L.append('')
    L.append('| 项 | 旧 | 新 | 变化 |')
    L.append('|---|---:|---:|---:|')
    dch = d['new_ch'] - d['old_ch']
    dln = d['new_lines'] - d['old_lines']
    L.append('| 频道数 | %d | %d | %+d |' % (d['old_ch'], d['new_ch'], dch))
    L.append('| 线路数 | %d | %d | %+d |' % (d['old_lines'], d['new_lines'], dln))
    L.append('')
    if not d['added'] and not d['removed'] and not d['changed']:
        L.append('内容无变化。')
        L.append('')
        return L
    if d['added']:
        L.append('**新增频道 %d 个**：%s' % (len(d['added']), '、'.join(d['added'][:40])))
        L.append('')
    if d['removed']:
        L.append('**移除频道 %d 个**：%s' % (len(d['removed']), '、'.join(d['removed'][:40])))
        L.append('')
    if d['changed']:
        L.append('**线路变动 %d 个频道**：' % len(d['changed']))
        L.append('')
        L.append('| 频道 | 新增线路 | 移除线路 |')
        L.append('|---|---|---|')
        for c, add, rem in d['changed'][:60]:
            L.append('| %s | %d | %d |' % (c, len(add), len(rem)))
        if len(d['changed']) > 60:
            L.append('')
            L.append('> 另有 %d 个频道线路有变动，详见提交 diff。' % (len(d['changed']) - 60))
        L.append('')
        # 逐条列出被移除的线路（更关心「什么被删了」——尤其是广告源）
        removed_lines = []
        for c, add, rem in d['changed']:
            for u in rem:
                removed_lines.append((c, u))
        if removed_lines:
            L.append('<details><summary>被移除的线路明细（%d 条）</summary>' % len(removed_lines))
            L.append('')
            for c, u in removed_lines[:120]:
                L.append('- `%s` → %s' % (c, u))
            L.append('')
            L.append('</details>')
            L.append('')
    return L


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--old', default='HEAD', help='旧版本来源（git rev）')
    ap.add_argument('--new', default='.', help='新版本所在目录')
    ap.add_argument('--format', default='markdown', choices=['markdown', 'text'])
    ap.add_argument('--summary-file', default='', help='同时把简短统计写入该文件')
    ap.add_argument('--max-detail', type=int, default=60)
    args = ap.parse_args()

    blocks = []
    stats = []
    for label, rel, _rel2 in TARGETS:
        old = read_old(rel, args.old)
        new = read_new(rel)
        if new is None:
            continue
        if old is None:
            old = ''
        d = diff_one(old, new, rel.endswith('.m3u'))
        blocks.append((label, d))
        stats.append((label, d))

    if args.format == 'markdown':
        out = ['## 📋 直播源自动重建 · 变更报告', '']
        out.append('> 对比基准：`%s`（重建前） → 本次重建产物' % args.old)
        out.append('')
        # 总览表
        out.append('| 文件 | 频道数 | 线路数 | 新增频道 | 移除频道 | 线路变动频道 |')
        out.append('|---|---:|---:|---:|---:|---:|')
        for label, d in stats:
            out.append('| %s | %d → %d | %d → %d | %d | %d | %d |' % (
                label, d['old_ch'], d['new_ch'], d['old_lines'], d['new_lines'],
                len(d['added']), len(d['removed']), len(d['changed'])))
        out.append('')
        for label, d in blocks:
            out += fmt_markdown(d, label)
        text = '\n'.join(out)
    else:
        lines = []
        for label, d in stats:
            lines.append('%s: 频道 %d→%d 线路 %d→%d 新增%d 移除%d 变动%d' % (
                label, d['old_ch'], d['new_ch'], d['old_lines'], d['new_lines'],
                len(d['added']), len(d['removed']), len(d['changed'])))
        text = '\n'.join(lines)

    print(text)

    if args.summary_file:
        one = '；'.join(
            '%s 频道%d→%d 线路%d→%d' % (l, d['old_ch'], d['new_ch'],
                                        d['old_lines'], d['new_lines'])
            for l, d in stats)
        with open(args.summary_file, 'w', encoding='utf-8') as f:
            f.write(one)


if __name__ == '__main__':
    main()
