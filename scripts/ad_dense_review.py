"""对可疑源做密集抽帧 + 逐源拼图（90 秒 / 15 帧），供人工逐格定案。

用法：python scripts/ad_dense_review.py <抽帧目录> <输出目录> <索引json> [URL子串过滤]
"""
import concurrent.futures
import json
import pathlib
import subprocess
import sys

sys.stdout.reconfigure(encoding='utf-8')

FFMPEG = r'C:\Users\1\AppData\Local\FluxDown\bin\ffmpeg.exe'
root = pathlib.Path(__file__).resolve().parent.parent

scan_dir = pathlib.Path(sys.argv[1])
outdir = pathlib.Path(sys.argv[2])
idx = json.loads(pathlib.Path(sys.argv[3]).read_text(encoding='utf-8'))
only_flag = (len(sys.argv) > 4 and sys.argv[4] == 'flag')

try:
    from PIL import Image, ImageDraw
except Exception as e:
    print('NO PIL', e)
    sys.exit(1)

DUR, STEP, WORKERS = 90, 6, 6
TW, TH = 320, 180
COLS = 5          # 每图 5 源 × 15 帧 = 3 行


def grab(job):
    i, u = job
    d = scan_dir / ('dense%04d' % i)
    d.mkdir(parents=True, exist_ok=True)
    cmd = [FFMPEG, '-y', '-i', u, '-t', str(DUR),
           '-vf', 'fps=1/%d,scale=%d:%d' % (STEP, TW, TH),
           '-q:v', '3', str(d / 'd%03d.jpg')]
    try:
        subprocess.run(cmd, capture_output=True, timeout=DUR + 90)
    except Exception:
        pass
    return i, len(list(d.glob('d*.jpg')))


# 选出待复核源：FLAG 的（band>=10 或 red>=0.35）
sys.path.insert(0, str(root / 'scripts'))
import ad_feat

targets = []
for r in idx:
    d = scan_dir / ('s%04d' % r['idx'])
    if not d.exists():
        continue
    fs = sorted(d.glob('*.jpg'))
    if not fs:
        continue
    best = None
    for p in fs:
        f = ad_feat.frame_features(p)
        if f is None:
            continue
        sc = f[0] * 0.9 + f[1] * 0.55 + f[2] * 120.0
        if best is None or sc > best[0]:
            best = (sc, p, f)
    if best is None:
        continue
    band, full, red = best[2]
    if band >= 10 or red >= 0.35:
        targets.append((r['idx'], r['url'], r['name'], band, red))

print('待密集复核 %d 个源（每源 %d 秒 / %d 帧）' % (len(targets), DUR, DUR // STEP),
      flush=True)

jobs = [(i, u) for i, u, _, _, _ in targets]
with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
    for i, n in ex.map(grab, jobs):
        print('  #%04d %d 帧' % (i, n), flush=True)

# 每源一张横排拼图（15 帧）
per_img = COLS
pages = (len(targets) + per_img - 1) // per_img
(outdir).mkdir(parents=True, exist_ok=True)
(outdir / 'index.txt').write_text(
    '\n'.join('#%03d %-14s band=%-3d red=%.4f  %s' % (i, n, b, rd, u)
              for i, u, n, b, rd in targets), encoding='utf-8')

for pg in range(pages):
    chunk = targets[pg * per_img:(pg + 1) * per_img]
    sh = Image.new('RGB', (COLS * 15 * 0 + 15 * TW, len(chunk) * (TH + 20)), 'white')
    dr = ImageDraw.Draw(sh)
    for k, (i, u, n, b, rd) in enumerate(chunk):
        d = scan_dir / ('dense%04d' % i)
        fs = sorted(d.glob('d*.jpg'))
        y = k * (TH + 20)
        dr.text((4, y + 4), '#%03d %s' % (i, n), fill='red')
        for c, p in enumerate(fs[:15]):
            try:
                im = Image.open(p).convert('RGB').resize((TW, TH))
            except Exception:
                continue
            sh.paste(im, (c * TW, y + 20))
    out = outdir / ('dense%d.jpg' % pg)
    sh.save(out, quality=86)
    print('sheet:', out)
