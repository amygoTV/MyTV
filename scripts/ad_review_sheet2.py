"""生成人工复核拼图 v2：每源挑「最异常一帧」+ 自动红框标注可疑帧。

用法：python scripts/ad_review_sheet2.py <抽帧目录> <输出目录> <索引json>

改进：
  * 每源在 10 帧里挑「条带水平文本行数 + 红色占比」最高的一帧作为代表帧；
  * 该帧若 band_lines>=10 或 red_band>=0.35 → 格子加红框（疑似热线/购物广告）；
  * 图上只印大号编号，人工用 index.txt 反查 URL。
"""
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ad_feat

try:
    from PIL import Image, ImageDraw
except Exception as e:
    print('NO PIL', e)
    sys.exit(1)

root = pathlib.Path(sys.argv[1])
outdir = pathlib.Path(sys.argv[2])
idxfile = json.loads(pathlib.Path(sys.argv[3]).read_text(encoding='utf-8'))
rev = {('s%04d' % r['idx']): r for r in idxfile}
outdir.mkdir(parents=True, exist_ok=True)

PER_PAGE = 20
COLS, ROWS = 10, 2      # 10 列 × 2 行 = 20 源，每源 1 帧
TW, TH = 300, 169

rows = []
for d in sorted(root.iterdir()):
    if not d.is_dir():
        continue
    best = None
    for p in sorted(d.glob('*.jpg')):
        f = ad_feat.frame_features(p)
        if f is None:
            continue
        band, full, red = f
        sc = band * 0.9 + full * 0.55 + red * 120.0
        if best is None or sc > best[0]:
            best = (sc, p, band, full, red)
    if best:
        sc, p, band, full, red = best
        rows.append({'dir': d.name, 'path': p, 'score': sc,
                     'band': band, 'full': full, 'red': red,
                     'flag': band >= 10 or red >= 0.35,
                     'url': rev.get(d.name, {}).get('url', ''),
                     'name': rev.get(d.name, {}).get('name', '')})

rows.sort(key=lambda r: (not r['flag'], -r['score']))
print('源 %d 个，标红 %d 个' % (len(rows), sum(1 for r in rows if r['flag'])))

(outdir / 'index.txt').write_text(
    '\n'.join('#%03d %s flag=%s score=%.1f band=%d red=%.4f  %-14s %s' % (
        i, r['dir'], 'Y' if r['flag'] else 'n', r['score'], r['band'], r['red'],
        r['name'], r['url'])
        for i, r in enumerate(rows)), encoding='utf-8')

pages = (len(rows) + PER_PAGE - 1) // PER_PAGE
for pg in range(pages):
    chunk = rows[pg * PER_PAGE:(pg + 1) * PER_PAGE]
    sh = Image.new('RGB', (COLS * TW, ROWS * (TH + 20)), 'white')
    dr = ImageDraw.Draw(sh)
    for k, r in enumerate(chunk):
        try:
            im = Image.open(r['path']).convert('RGB').resize((TW, TH))
        except Exception:
            continue
        x, y = (k % COLS) * TW, (k // COLS) * (TH + 20)
        sh.paste(im, (x, y + 20))
        if r['flag']:
            dr.rectangle([x, y + 20, x + TW - 1, y + 20 + TH - 1],
                         outline=(255, 0, 0), width=3)
        dr.text((x + 4, y + 3), '#%03d' % (pg * PER_PAGE + k), fill=(255, 0, 0))
    out = outdir / ('sheet%d.jpg' % pg)
    sh.save(out, quality=88)
    print('sheet:', out)
