"""把密集抽帧结果重排成清晰拼图（每图 3 个源，每个源 15 帧排 5列×3行）。

用法：python scripts/ad_dense_sheet.py <抽帧目录> <输出目录> <索引json>
"""
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding='utf-8')
try:
    from PIL import Image, ImageDraw
except Exception as e:
    print('NO PIL', e)
    sys.exit(1)

scan_dir = pathlib.Path(sys.argv[1])
outdir = pathlib.Path(sys.argv[2])
idx = json.loads(pathlib.Path(sys.argv[3]).read_text(encoding='utf-8'))
outdir.mkdir(parents=True, exist_ok=True)

TW, TH = 320, 180
PER_SRC = 15
SOURCES_PER_IMG = 3

rows = []
for line in (outdir / 'index.txt').read_text(encoding='utf-8').splitlines():
    p = line.split()
    if p and p[0].startswith('#'):
        rows.append(line)

# index.txt 里是 s 编号（对应 _adscan/sXXXX）；dense 目录用 dense%04d
sel = []
for line in rows:
    parts = line.split()
    num = parts[0][1:]                     # 形如 0015
    name = parts[2] if len(parts) > 2 else ''
    url = parts[-1]
    sel.append((int(num), name, url))

print('源 %d 个，每图 %d 个' % (len(sel), SOURCES_PER_IMG))

pages = (len(sel) + SOURCES_PER_IMG - 1) // SOURCES_PER_IMG
for pg in range(pages):
    chunk = sel[pg * SOURCES_PER_IMG:(pg + 1) * SOURCES_PER_IMG]
    sh = Image.new('RGB', (5 * TW, len(chunk) * (3 * TH + 22)), 'white')
    dr = ImageDraw.Draw(sh)
    for k, (num, name, url) in enumerate(chunk):
        d = scan_dir / ('dense%04d' % num)
        fs = sorted(d.glob('d*.jpg'))[:PER_SRC]
        y0 = k * (3 * TH + 22)
        dr.text((4, y0 + 4), '#%04d  %s' % (num, name), fill='red')
        for c, p in enumerate(fs):
            try:
                im = Image.open(p).convert('RGB').resize((TW, TH))
            except Exception:
                continue
            cx = (c % 5) * TW
            cy = y0 + 22 + (c // 5) * TH
            sh.paste(im, (cx, cy))
    out = outdir / ('big%d.jpg' % pg)
    sh.save(out, quality=90)
    print('sheet:', out, [c[0] for c in chunk])
