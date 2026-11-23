"""直播源广告自动检测器（批量密集抽帧 + 图像特征打分）。

用法：python scripts/ad_scan.py [--calib] [--out DIR]
原理：
    对每个源连采 N 帧（ffmpeg fps 滤镜），逐帧提取特征：
      1. 红色热线文字占比：广告条/购物广告画面常见「订购电话 400-xxx」红色大字，
         节目画面里红色字幕占比极低。
      2. 顶部/底部条带「高饱和度文本行」密度：滚动购物条是整条高对比文字带。
      3. 整帧红色像素占比突增：购物广告整屏商品图（红色包装/背景）。
    综合打分后排序，高分者进入人工复核（编号网格拼图）。

先用已知污染源/已知干净源校准阈值（--calib）。
"""
import argparse
import concurrent.futures
import json
import pathlib
import subprocess
import sys

sys.stdout.reconfigure(encoding='utf-8')

FFMPEG = r'C:\Users\1\AppData\Local\FluxDown\bin\ffmpeg.exe'
ROOT = pathlib.Path(__file__).resolve().parent.parent

# 已知样本（2026-11-23 密集抽帧人工判定结果）
CALIB_DIRTY = [
    'http://107.150.60.122/live/cetv2.m3u8',
    'http://107.150.60.122/live/cetv4.m3u8',
    'http://198.204.228.26/live/cetv4.m3u8',
    'http://38.75.136.137:98/gslb/dsdqbv/cetv2.m3u8?auth=test20251009',
    'http://63.141.230.178:82/gslb/zbdq5.m3u8?id=gswshd',
]
CALIB_CLEAN = [
    'http://198.204.228.26/live/cetv1hd.m3u8',
    'http://198.204.228.26/live/cetv2.m3u8',
    'http://198.204.228.26/live/cetv3.m3u8',
    'http://63.141.230.178:82/gslb/zbdq5.m3u8?id=cetv1hd',
    'http://63.141.230.178:82/gslb/zbdq5.m3u8?id=cetv2',
    'http://38.75.136.137:98/gslb/dsdqpub/cetv1hd.m3u8?auth=testpub',
    'http://38.75.136.137:98/gslb/dsdqpub/cetv4.m3u8?auth=testpub',
]


def probe(url, dur, step, outdir):
    """连采 dur 秒、每 step 秒一帧，返回帧文件列表。"""
    outdir.mkdir(parents=True, exist_ok=True)
    for f in outdir.glob('*.jpg'):
        f.unlink()
    cmd = [FFMPEG, '-y', '-i', url, '-t', str(dur),
           '-vf', 'fps=1/%d,scale=320:180' % step,
           '-q:v', '4', str(outdir / 'f%03d.jpg')]
    try:
        subprocess.run(cmd, capture_output=True, timeout=dur + 60)
    except Exception:
        pass
    return sorted(outdir.glob('*.jpg'))


def _rowwise_stats(im, bandrow_pred):
    """用 PIL 的通道分离 + ImageMath 不可用时，退回逐行列表统计。

    为提速，这里只对条带区域做统计，用 bytes 转换 + 生成器计数。
    """
    w, h = im.size
    bands = [(y, y + 1) for y in range(h) if bandrow_pred(y)]
    if not bands:
        return 0, 0, 0
    rch, gch, bch = im.split()
    rb = rch.tobytes()
    gb = gch.tobytes()
    bb = bch.tobytes()
    red = 0
    redrow = 0
    sat = 0
    satrow = 0
    total = 0
    for y0, y1 in bands:
        for y in range(y0, y1):
            base = y * w
            for x in range(w):
                i = base + x
                r = rb[i]; g = gb[i]; b = bb[i]
                total += 1
                if r > 110 and (r - g) > 45 and (r - b) > 35:
                    red += 1
                    redrow += 1
                mx = r if r > g else g
                if b > mx:
                    mx = b
                mn = r if r < g else g
                if b < mn:
                    mn = b
                if mx - mn > 70:
                    sat += 1
                    satrow += 1
    return red, redrow, sat, total, satrow


def features(frames):
    """逐帧算特征，返回 (red_strip_max, band_max, red_full_max, n_frames)。

    纯 PIL 实现（环境无 numpy）：
      - 红色热线文字：R>110 且 R-G>45 且 R-B>35
      - 条带文本密度：顶部+底部 18% 内 (max-min)>70 的像素占比（饱和文本）
    """
    try:
        from PIL import Image
    except Exception:
        return None
    if not frames:
        return None
    red_strip, band, red_full = [], [], []
    for p in frames:
        try:
            im = Image.open(p).convert('RGB')
        except Exception:
            continue
        w, h = im.size
        if w == 0 or h == 0:
            continue
        h16 = max(1, int(h * 0.16))
        h82 = int(h * 0.82)
        h18 = max(1, int(h * 0.18))

        # 条带统计（顶部16% + 底部18%）→ 红色占比 & 饱和文本密度
        strip_rows = [y for y in range(h) if y < h16 or y >= h82]
        band_rows = [y for y in range(h) if y < h18 or y >= h - h18]

        def count(rows, mode):
            rch, gch, bch = im.split()
            rb = rch.tobytes(); gb = gch.tobytes(); bb = bch.tobytes()
            hit = 0
            tot = 0
            for y in rows:
                base = y * w
                for x in range(w):
                    i = base + x
                    r = rb[i]; g = gb[i]; b = bb[i]
                    tot += 1
                    if mode == 'red':
                        if r > 110 and (r - g) > 45 and (r - b) > 35:
                            hit += 1
                    else:
                        mx = r if r > g else g
                        if b > mx:
                            mx = b
                        mn = r if r < g else g
                        if b < mn:
                            mn = b
                        if mx - mn > 70:
                            hit += 1
            return hit, tot

        rs, rt = count(strip_rows, 'red')
        bs, bt = count(band_rows, 'sat')
        # 整帧红色
        rch, gch, bch = im.split()
        rb = rch.tobytes(); gb = gch.tobytes(); bb = bch.tobytes()
        fr = 0
        for i in range(w * h):
            r = rb[i]; g = gb[i]; b = bb[i]
            if r > 110 and (r - g) > 45 and (r - b) > 35:
                fr += 1
        red_strip.append(rs / float(rt) if rt else 0)
        red_full.append(fr / float(w * h))
        band.append(bs / float(bt) if bt else 0)
    if not red_strip:
        return None
    return (max(red_strip), max(band), max(red_full), len(red_strip))


def scan(url, dur, step, workdir, idx):
    d = workdir / ('s%04d' % idx)
    frames = probe(url, dur, step, d)
    f = features(frames)
    if f is None:
        return idx, url, None, 0
    return idx, url, f[:3], f[3]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--calib', action='store_true', help='用已知样本校准阈值')
    ap.add_argument('--dur', type=int, default=30)
    ap.add_argument('--step', type=int, default=3)
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--out', default='_adscan')
    ap.add_argument('--report', default='scripts/ad_scan_report.json')
    args = ap.parse_args()

    workdir = ROOT / args.out
    workdir.mkdir(exist_ok=True)

    if args.calib:
        targets = [('DIRTY', u) for u in CALIB_DIRTY] + [('CLEAN', u) for u in CALIB_CLEAN]
    else:
        plan = json.loads((ROOT / 'scripts/channel_plan.json').read_text(encoding='utf-8'))
        seen, targets = set(), []
        for name, meta in plan['channels'].items():
            for u in meta.get('ipv4', []):
                if u.startswith('http://[') or u in seen:
                    continue
                seen.add(u)
                targets.append((name, u))

    print('待测源 %d 个，每源连采 %d 秒/每 %d 秒一帧，并发 %d'
          % (len(targets), args.dur, args.step, args.workers), flush=True)

    jobs = [(i, u) for i, (_, u) in enumerate(targets)]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(scan, u, args.dur, args.step, workdir, i): i for i, u in jobs}
        done = 0
        for fut in concurrent.futures.as_completed(futs):
            done += 1
            try:
                results.append(fut.result())
            except Exception as e:
                print('  err', e, flush=True)
            if done % 10 == 0:
                print('  ... %d/%d' % (done, len(targets)), flush=True)

    results.sort(key=lambda x: x[0])
    out = []
    for idx, url, f, n in results:
        name = targets[idx][0] if idx < len(targets) else '?'
        rec = {'name': name, 'url': url, 'frames': n}
        if f:
            rec['red_strip'], rec['band'], rec['red_full'] = [round(v, 4) for v in f]
            rec['score'] = round(f[0] * 2.2 + f[1] * 1.0 + f[2] * 2.0, 4)
        else:
            rec['score'] = -1
        out.append(rec)

    (ROOT / args.report).write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                    encoding='utf-8')

    ok = [r for r in out if r['frames']]
    ok.sort(key=lambda r: -r['score'])
    print('\n=== 得分 TOP 40（%d/%d 抓到帧）===' % (len(ok), len(out)), flush=True)
    for r in ok[:40]:
        print('  %6.3f  rs=%-7s bd=%-7s rf=%-7s  %-12s %s' % (
            r['score'], r.get('red_strip'), r.get('band'), r.get('red_full'),
            r['name'], r['url'][:88]), flush=True)


if __name__ == '__main__':
    main()
