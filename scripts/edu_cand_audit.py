"""教育台替代源抽帧审计（从 Livelist 源文件自动解析候选 URL，避免手抄错误）。

用法：python scripts/edu_cand_audit.py
"""
import concurrent.futures
import pathlib
import re
import subprocess
import sys

FFMPEG = r'C:\Users\1\AppData\Local\FluxDown\bin\ffmpeg.exe'
ROOT = pathlib.Path(__file__).resolve().parent.parent
LIVELIST = ROOT.parent.parent / 'Livelist_work' / 'repo' / 'CCTV.m3u'
OUT = ROOT / '_eduframe'
OUT.mkdir(exist_ok=True)

OFFSETS = [int(x) for x in (sys.argv[1].split(',') if len(sys.argv) > 1
                            else ['6', '25', '55'])]
COLS = 4
TW, TH = 400, 225

# 从 CCTV.m3u 中抽取 CETV 段：EXTINF 行标出频道名，后续 URL 属于该频道
# （URL 本身不一定含 cetv 字样，如 cmvideo/gmcc/zby，所以按"下一个 EXTINF 前全部 URL"收集）
CAND = {}
cur = None
for line in LIVELIST.read_text(encoding='utf-8', errors='ignore').splitlines():
    line = line.strip()
    if not line:
        continue
    if line.startswith('#EXTINF'):
        m = re.search(r',([^\n,]+)\s*$', line)
        nm = (m.group(1) if m else '').strip()
        cur = nm.upper().replace('-', '').replace(' ', '') if 'CETV' in nm.upper() else None
    elif line.startswith('#'):
        continue
    elif cur:
        CAND.setdefault(cur, []).append(line)

print('解析到的 CETV 频道段:', {k: len(v) for k, v in CAND.items()}, flush=True)

CANDS = []
for ch in sorted(CAND):
    for u in CAND[ch]:
        CANDS.append((ch, u))

print('候选 %d 条，抓帧时间点 %s' % (len(CANDS), OFFSETS), flush=True)


def grab(item):
    idx, ch, u = item
    ok = 0
    for k, off in enumerate(OFFSETS):
        out = OUT / ('c%03d_%d.jpg' % (idx, k))
        cmd = [FFMPEG, '-y', '-ss', str(off), '-i', u, '-frames:v', '1',
               '-vf', 'scale=%d:%d' % (TW, TH), '-q:v', '3', str(out)]
        try:
            subprocess.run(cmd, capture_output=True, timeout=45)
        except Exception:
            pass
        if out.exists() and out.stat().st_size > 1500:
            ok += 1
    return idx, ch, u, ok


with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
    res = list(ex.map(grab, [(i,) + c for i, c in enumerate(CANDS)]))

ok_list = [(i, c, u, o) for i, c, u, o in res if o]
print('抓帧成功 %d / %d' % (len(ok_list), len(CANDS)), flush=True)
for i, c, u, o in ok_list:
    print('  #%03d %-8s %d帧  %s' % (i, c, o, u[:120]), flush=True)

try:
    from PIL import Image, ImageDraw
except Exception as exc:
    print('NO_PIL', exc, flush=True)
    sys.exit(0)


def build_sheet(items, fname):
    rows = (len(items) + COLS - 1) // COLS
    sheet = Image.new('RGB', (COLS * TW, rows * (TH + 20)), 'white')
    draw = ImageDraw.Draw(sheet)
    for k, (label, p) in enumerate(items):
        try:
            im = Image.open(p).convert('RGB').resize((TW, TH))
        except Exception:
            continue
        x, y = (k % COLS) * TW, (k // COLS) * (TH + 20)
        sheet.paste(im, (x, y + 20))
        draw.text((x + 4, y + 4), label, fill='red')
    out = OUT / fname
    sheet.save(out, quality=90)
    print('sheet:', out, flush=True)


for k, off in enumerate(OFFSETS):
    items = []
    for i, c, u, o in ok_list:
        p = OUT / ('c%03d_%d.jpg' % (i, k))
        if p.exists() and p.stat().st_size > 1500:
            items.append(('#%03d %s' % (i, c[:12]), p))
    if items:
        build_sheet(items, 'cand_t%d.jpg' % off)
