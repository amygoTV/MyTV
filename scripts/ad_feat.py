"""直播源广告检测特征 v2（纯 PIL，无 numpy）。

核心洞察：购物广告画面与热线滚动条的共同物理特征是**大量水平文本行**，
而正常电视节目画面（除底部字幕 1~2 行外）几乎没有水平文本行。

特征定义（对每帧）：
  A. band_lines  —— 顶部 20% + 底部 22% 区域内的「水平文本行」数（热线滚动条）
  B. full_lines  —— 整帧内的「水平文本行」数（整屏购物广告海报）
  C. red_band    —— 条带内强红像素占比（热线/商品红色大字，辅助）

水平文本行判定：某一行内，相邻像素亮度差 > 42 的像素数 > 行宽 * 0.22
                 → 认为该行是文字行（文字/商品参数/热线号码）

综合分 = max_over_frames( band_lines*0.9 + full_lines*0.55 + red_band*120 )
"""
import pathlib
import sys

sys.stdout.reconfigure(encoding='utf-8')


def frame_features(path):
    """返回 (band_lines, full_lines, red_band) 或 None。"""
    try:
        from PIL import Image
    except Exception:
        return None
    try:
        im = Image.open(path).convert('L')
    except Exception:
        return None
    w, h = im.size
    if w < 8 or h < 8:
        return None
    data = list(im.tobytes())
    thr = 42
    need = max(4, int(w * 0.22))

    def row_is_text(y):
        base = y * w
        cnt = 0
        prev = data[base]
        for x in range(1, w):
            cur = data[base + x]
            if cur - prev > thr or prev - cur > thr:
                cnt += 1
                if cnt >= need:
                    return True
            prev = cur
        return False

    # 水平文本行计数（全帧）
    full_lines = 0
    rowflags = [False] * h
    for y in range(h):
        if row_is_text(y):
            rowflags[y] = True
            full_lines += 1

    # 条带范围：顶部 20% + 底部 22%
    band_lines = 0
    for y in range(h):
        if (y < int(h * 0.20) or y >= int(h * 0.78)) and rowflags[y]:
            band_lines += 1

    # 条带强红像素占比
    try:
        rgb = Image.open(path).convert('RGB')
        rch, gch, bch = rgb.split()
        rb = rch.tobytes(); gb = gch.tobytes(); bb = bch.tobytes()
    except Exception:
        return band_lines, full_lines, 0.0
    hit = 0
    tot = 0
    for y in range(h):
        if not (y < int(h * 0.20) or y >= int(h * 0.78)):
            continue
        base = y * w
        for x in range(w):
            i = base + x
            r = rb[i]; g = gb[i]; b = bb[i]
            tot += 1
            if r > 110 and (r - g) > 45 and (r - b) > 35:
                hit += 1
    return band_lines, full_lines, (hit / float(tot) if tot else 0.0)


def source_features(frames):
    """多帧聚合，返回 (max_band, max_full, max_red, n)。"""
    best = None
    n = 0
    for p in frames:
        f = frame_features(p)
        if f is None:
            continue
        n += 1
        if best is None or (f[0] + f[1] * 0.6) > (best[0] + best[1] * 0.6):
            best = f
    if best is None:
        return None
    return (best[0], best[1], best[2], n)


def score(band, full, red):
    return band * 0.9 + full * 0.55 + red * 120.0


if __name__ == '__main__':
    import json
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else '_adscan')
    out = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        fs = sorted(d.glob('*.jpg'))
        r = source_features(fs)
        if r is None:
            out.append({'dir': d.name, 'n': 0, 'score': -1})
            continue
        band, full, red, n = r
        out.append({'dir': d.name, 'band': band, 'full': full,
                    'red': round(red, 4), 'n': n,
                    'score': round(score(band, full, red), 2)})
    out.sort(key=lambda x: -x['score'])
    print(json.dumps(out, ensure_ascii=False, indent=1))
