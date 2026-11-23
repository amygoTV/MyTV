"""生成人工复核拼图：每个源只取「最可疑的一帧」，拼成大图。

用法：python scripts/ad_review_sheet.py <抽帧目录> <输出目录>
配合 scripts/ad_feat.py 的特征，挑出得分最高的帧作为该源的代表帧，
再拼成带编号的大图，供人工逐格扫读判定（购物广告画面 / 热线滚动条 / 正常节目）。
"""
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
outdir.mkdir(parents=True, exist_ok=True)

PER_PAGE = 24          # 每页 24 个源
COLS, ROWS = 6, 4
TW, TH = 320, 180

# 每个源挑一帧
picks = []   # (dirname, framepath, score, band, full, red)
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
        picks.append((d.name, best[1], best[0], best[2], best[3], best[4]))

picks.sort(key=lambda x: -x[2])
print('源 %d 个，按可疑度排序' % len(picks))

# 写索引（编号 -> 目录名），供后续查 URL
idx = {}
for i, (dn, p, sc, b, f, r) in enumerate(picks):
    idx[dn] = i
(outdir / 'index.txt').write_text(
    '\n'.join('#%03d %s  score=%.1f band=%d full=%d red=%.4f' % (i, dn, sc, b, f, r)
              for i, (dn, p, sc, b, f, r) in enumerate(picks)),
    encoding='utf-8')

pages = (len(picks) + PER_PAGE - 1) // PER_PAGE
for pg in range(pages):
    chunk = picks[pg * PER_PAGE:(pg + 1) * PER_PAGE]
    sh = Image.new('RGB', (COLS * TW, ROWS * (TH + 18)), 'white')
    dr = ImageDraw.Draw(sh)
    for k, (dn, p, sc, b, f, r) in enumerate(chunk):
        try:
            im = Image.open(p).convert('RGB').resize((TW, TH))
        except Exception:
            continue
        x, y = (k % COLS) * TW, (k // COLS) * (TH + 18)
        sh.paste(im, (x, y + 18))
        dr.text((x + 3, y + 3), '#%03d  %s' % (pg * PER_PAGE + k, dn), fill='red')
    out = outdir / ('sheet%d.jpg' % pg)
    sh.save(out, quality=88)
    print('sheet:', out)
