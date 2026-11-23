"""CI 版「新增线路抽帧审查」——只抽帧、排序、出图，绝不判废 / 改黑名单 / 阻断提交。

设计原则（务必遵守，改动前先读）：
  * 这一步是**人工复核的辅助材料**，不是自动过滤器。绝不可根据本脚本的打分
    自动拉黑 URL 或改产物——打分只用于「把最可疑的排前面」，最终定案靠人看画面。
  * 判定三分法沿用既定口径：
      ① 15 帧几乎全是购物广告 / 常驻 400 热线 → 人工确认后加入 ad_blacklist.txt
      ② 只有 1~3 帧广告、其余正常 → 正常插播，保留
      ③ 全程正常 → 保留
  * 只审查「本次重建相对 HEAD 新增的线路」——存量线路此前已逐条核验过，
    每晚全量重抽既慢又会把已确认的正常台反复翻出来。
  * 跳过 UDP / RTP 组播源与 IPv6 字面地址：本机与 CI 都拉不到，抽帧无意义
    （对应用户「不要 UDP 组播源」的要求，至少在审查环节先排除）。

产出（写到 --out 目录，由 Action 上传为 artifact）：
  - review.md          待复核清单（表格 + 看图说明）
  - review_queue.json  结构化清单，供人工回填黑名单时对照
  - sheet_001.jpg ...  每源一张 5 列 x 3 行的 15 帧网格图（按可疑分降序）

用法：
  python3 scripts/live_ad_probe.py --old HEAD --out _adprobe --max 24
  python3 scripts/live_ad_probe.py --dry-run          # 本地只列新增线路，不抽帧
"""
import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

# 复用差异报告的解析逻辑，避免两处口径漂移
import live_diff_report as ldr  # noqa: E402
import ad_feat  # noqa: E402

DUR, STEP, THUMB_W, THUMB_H = 90, 6, 320, 180
COLS = 5


def find_ffmpeg(explicit):
    if explicit:
        return explicit
    p = shutil.which('ffmpeg')
    if p:
        return p
    win = r'C:\Users\1\AppData\Local\FluxDown\bin\ffmpeg.exe'
    if os.path.exists(win):
        return win
    return None


def skip_url(u):
    """UDP/RTP 组播、IPv6 字面量、非 http(s) 一律跳过。

    除协议头 udp:// 外，还要挡「HTTP 封装的 UDP 组播」——形如
    http://58.252.12.164:8000/udp/239.77.1.214:5146（路径含 /udp/ + 组播地址）。
    这类源本机与 CI 都拉不到，且用户明确不要 UDP 组播源。
    """
    if u.startswith('udp://') or u.startswith('rtp://') or u.startswith('rtsp://'):
        return True
    if u.startswith('http://[') or u.startswith('https://['):
        return True
    if '/udp/' in u or 'udp://' in u:
        return True
    return not (u.startswith('http://') or u.startswith('https://'))


def collect_new_lines(old_rev):
    """返回 [(频道, URL, 来源标签)]，来源标签 = new_channel / changed。"""
    pairs = []
    for label, rel, _ in ldr.TARGETS:
        old = ldr.read_old(rel, old_rev) or ''
        new = ldr.read_new(rel) or ''
        _, od = ldr.parse(old, rel.endswith('.m3u'))
        _, nd = ldr.parse(new, rel.endswith('.m3u'))
        for ch in nd:
            if ch not in od:
                for u in nd[ch]:
                    pairs.append((ch, u, 'new_channel'))
            else:
                added = set(nd[ch]) - set(od[ch])
                for u in nd[ch]:
                    if u in added:
                        pairs.append((ch, u, 'changed'))
    # 全局去重（TXT 与 M3U 内容相同），新增频道的线路排在前面优先审查
    seen, out = set(), []
    for ch, u, tag in pairs:
        key = (ch, u)
        if key in seen:
            continue
        seen.add(key)
        out.append((ch, u, tag))
    out.sort(key=lambda x: 0 if x[2] == 'new_channel' else 1)
    return out


def grab(job, ffmpeg, workdir):
    i, url = job
    d = os.path.join(workdir, 'f%03d' % i)
    os.makedirs(d, exist_ok=True)
    for fn in os.listdir(d):
        if fn.endswith('.jpg'):
            os.remove(os.path.join(d, fn))
    cmd = [ffmpeg, '-y', '-i', url, '-t', str(DUR),
           '-vf', 'fps=1/%d,scale=%d:%d' % (STEP, THUMB_W, THUMB_H),
           '-q:v', '3', os.path.join(d, 'f%03d.jpg')]
    try:
        subprocess.run(cmd, capture_output=True, timeout=DUR + 90)
    except Exception:
        pass
    return i, len([f for f in os.listdir(d) if f.endswith('.jpg')])


def make_sheet(frames, path, head):
    """5 列 x 3 行的 15 帧网格，顶部一行标题。"""
    try:
        from PIL import Image, ImageDraw
    except Exception as e:
        print('NO PIL:', e, flush=True)
        return False
    rows = (len(frames) + COLS - 1) // COLS
    sheet = Image.new('RGB', (COLS * THUMB_W, 22 + rows * THUMB_H), 'white')
    dr = ImageDraw.Draw(sheet)
    dr.text((4, 5), head, fill='red')
    for k, p in enumerate(frames[:15]):
        try:
            im = Image.open(p).convert('RGB').resize((THUMB_W, THUMB_H))
        except Exception:
            continue
        sheet.paste(im, ((k % COLS) * THUMB_W, 22 + (k // COLS) * THUMB_H))
    sheet.save(path, quality=86)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--old', default='HEAD', help='对比基准（git rev）')
    ap.add_argument('--out', default='_adprobe', help='产出目录（相对仓库根）')
    ap.add_argument('--max', type=int, default=24, help='最多抽帧条数（CI 时间预算）')
    ap.add_argument('--dur', type=int, default=DUR)
    ap.add_argument('--step', type=int, default=STEP)
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--ffmpeg', default='', help='ffmpeg 路径（默认自动探测）')
    ap.add_argument('--dry-run', action='store_true', help='只列新增线路，不抽帧')
    args = ap.parse_args()

    pairs = collect_new_lines(args.old)
    total = len(pairs)
    pairs = [(ch, u, tag) for ch, u, tag in pairs if not skip_url(u)]
    skipped = total - len(pairs)
    print('新增线路 %d 条，过滤 UDP/IPv6/非http 后 %d 条（跳过 %d）'
          % (total, len(pairs), skipped), flush=True)

    if args.dry_run:
        for ch, u, tag in pairs[:args.max]:
            print('  [%s] %-12s %s' % (tag, ch, u), flush=True)
        return

    targets = pairs[:args.max]
    truncated = max(0, len(pairs) - len(targets))

    outdir = os.path.join(ROOT, args.out)
    workdir = os.path.join(outdir, 'frames')
    os.makedirs(workdir, exist_ok=True)

    ffmpeg = find_ffmpeg(args.ffmpeg)
    if not ffmpeg:
        print('::error::找不到 ffmpeg，跳过抽帧审查（不阻断构建）', flush=True)
        with open(os.path.join(outdir, 'review.md'), 'w', encoding='utf-8') as f:
            f.write('## 待复核新增线路\n\n未找到 ffmpeg，本次未抽帧。新增线路清单见下。\n\n')
            for ch, u, tag in targets:
                f.write('- `%s` — %s\n' % (ch, u))
        return

    print('抽帧 %d 条（每源 %d 秒 / %d 帧，并发 %d）'
          % (len(targets), args.dur, args.dur // args.step, args.workers), flush=True)

    jobs = [(i, u) for i, (_, u, _) in enumerate(targets)]
    nframes = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, n in ex.map(lambda j: grab(j, ffmpeg, workdir), jobs):
            nframes[i] = n
            print('  #%03d %d 帧' % (i, n), flush=True)

    # 打分排序：只用于把最可疑的排前面，不用于判废
    scored = []
    for i, (ch, u, tag) in enumerate(targets):
        d = os.path.join(workdir, 'f%03d' % i)
        frames = sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith('.jpg'))
        r = ad_feat.source_features(frames)
        band, full, red = (r[0], r[1], r[2]) if r else (0, 0, 0.0)
        sc = ad_feat.score(band, full, red) if r else -1
        scored.append({'idx': i, 'name': ch, 'url': u, 'tag': tag,
                       'score': round(sc, 2), 'frames': nframes.get(i, 0),
                       'band': band, 'full': full, 'red': round(red, 4)})
    scored.sort(key=lambda x: -x['score'])

    queue = []
    for rank, rec in enumerate(scored, 1):
        d = os.path.join(workdir, 'f%03d' % rec['idx'])
        frames = sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith('.jpg'))
        img = 'sheet_%03d.jpg' % rank
        head = '#%02d %s  score=%.1f  band=%d red=%.2f  %s' % (
            rank, rec['name'], rec['score'], rec['band'], rec['red'], rec['url'][:70])
        if frames:
            make_sheet(frames, os.path.join(outdir, img), head)
        rec['sheet'] = img if frames else ''
        queue.append(rec)

    with open(os.path.join(outdir, 'review_queue.json'), 'w', encoding='utf-8') as f:
        json.dump({'old': args.old, 'total_new': total, 'reviewed': len(targets),
                   'skipped': skipped, 'truncated': truncated, 'items': queue},
                  f, ensure_ascii=False, indent=1)

    L = []
    L.append('## 待人工复核：本次新增线路抽帧审查')
    L.append('')
    L.append('> ⚠️ **本步骤只抽帧、排序、出图，不会自动拉黑任何源，也不阻断提交。**')
    L.append('> 打分仅用于把最可疑的排在最前。请人工看 `sheet_*.jpg`（每图 15 帧 / 90 秒）。')
    L.append('> 判定口径：整屏购物广告或常驻 400 热线 → 确认后把 URL 加入 '
             '`scripts/ad_blacklist.txt`；偶发 1~3 帧广告属正常插播，保留。')
    L.append('')
    L.append('- 本次新增线路 %d 条，过滤 UDP/IPv6/非http %d 条，实抽 %d 条'
             % (total, skipped, len(targets)))
    if truncated:
        L.append('- ⏱ 受 CI 时间预算限制，只抽了前 %d 条，另有 %d 条未抽（清单见 queue json）'
                 % (len(targets), truncated))
    L.append('')
    L.append('| # | 频道 | 可疑分 | 帧数 | URL |')
    L.append('|---:|---|---:|---:|---|')
    for rank, rec in enumerate(queue, 1):
        L.append('| %d | %s | %.1f | %d | `%s` |' % (
            rank, rec['name'], rec['score'], rec['frames'], rec['url']))
    L.append('')
    L.append('<details><summary>拼图索引（下载 artifact 后按序号查看）</summary>')
    L.append('')
    for rank, rec in enumerate(queue, 1):
        if rec['sheet']:
            L.append('- #%02d %s → `%s`' % (rank, rec['name'], rec['sheet']))
    L.append('')
    L.append('</details>')
    with open(os.path.join(outdir, 'review.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')

    print('审查产出写到 %s（%d 条待复核）' % (outdir, len(targets)), flush=True)


if __name__ == '__main__':
    main()
