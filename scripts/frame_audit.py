"""广告台/错台抽帧核验工具。

用法：python scripts/frame_audit.py
对 scripts/channel_plan.json 里每个公网 IPv4 源用 ffmpeg 抓首帧，
再用 ffmpeg tile 拼成编号网格（_adframe/sheet*.jpg），人工逐格看图判定：
  * 顶部/底部常驻滚动购物条（「抢购热线/订购热线/咨询热线 400-xxx」）或
    整屏推购物广告  -> 污染源，写入 scripts/ad_blacklist.txt
  * 整屏限时插播广告（如《天天向上》片中口播）-> 正常电视广告，不拉黑
  * 台标与频道名不符 -> 错台，拉黑
"""
"""广告台/错台抽帧核验工具。

用法：python scripts/frame_audit.py
对 scripts/channel_plan.json 里每个公网 IPv4 源用 ffmpeg 抓首帧，
再用 ffmpeg tile 拼成编号网格（_adframe/sheet*.jpg），人工逐格看图判定：
  * 顶部/底部常驻滚动购物条（「抢购热线/订购热线/咨询热线 400-xxx」）或
    整屏推购物广告  -> 污染源，写入 scripts/ad_blacklist.txt
  * 整屏限时插播广告（如《天天向上》片中口播）-> 正常电视广告，不拉黑
  * 台标与频道名不符 -> 错台，拉黑
"""
import concurrent.futures
import json
import pathlib
import subprocess
import sys

FFMPEG = r'C:\Users\1\AppData\Local\FluxDown\bin\ffmpeg.exe'
ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / '_adframe'
OUT.mkdir(exist_ok=True)

plan = json.loads((ROOT / 'scripts/channel_plan.json').read_text(encoding='utf-8'))
urls = []
for name, meta in plan['channels'].items():
    for u in meta.get('ipv4', []):
        if u not in urls:
            urls.append(u)
print('unique IPv4 sources:', len(urls), flush=True)


def grab(pair):
    idx, u = pair
    out = OUT / ('f%03d.jpg' % idx)
    cmd = [FFMPEG, '-y', '-ss', '8', '-i', u, '-frames:v', '1',
           '-vf', 'scale=320:180', '-q:v', '4', str(out)]
    try:
        subprocess.run(cmd, capture_output=True, timeout=30)
    except Exception:
        pass
    ok = out.exists() and out.stat().st_size > 1200
    return idx, u, ok


with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
    res = list(ex.map(grab, enumerate(urls)))
ok = [(i, u) for i, u, o in res if o]
print('frames grabbed:', len(ok), '/', len(urls), flush=True)
(OUT / 'index.txt').write_text(
    '\n'.join('%03d\t%s' % (i, u) for i, u in ok), encoding='utf-8')

try:
    from PIL import Image, ImageDraw
except Exception as exc:
    print('NO_PIL', exc, flush=True)
    sys.exit(0)

# 5 x 4 拼图，带序号标注
COLS, ROWS = 5, 4
PER = COLS * ROWS
TW, TH = 320, 180
for page in range((len(ok) + PER - 1) // PER):
    chunk = ok[page * PER:(page + 1) * PER]
    sheet = Image.new('RGB', (COLS * TW, ROWS * (TH + 18)), 'white')
    draw = ImageDraw.Draw(sheet)
    for k, (idx, u) in enumerate(chunk):
        try:
            im = Image.open(OUT / ('f%03d.jpg' % idx)).convert('RGB').resize((TW, TH))
        except Exception:
            continue
        x, y = (k % COLS) * TW, (k // COLS) * (TH + 18)
        sheet.paste(im, (x, y + 18))
        draw.text((x + 3, y + 3), '#%03d' % idx, fill='red')
    p = OUT / ('sheet%d.jpg' % page)
    sheet.save(p, quality=88)
    print('sheet:', p, flush=True)
