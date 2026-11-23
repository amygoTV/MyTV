"""为 OCR 准备放大的条带帧。

从抽帧目录读取整帧，裁出顶部/底部条带并放大 3 倍（灰度增强对比度），
另存到 OCR 专用目录，供 WinRT OCR 识别热线号码。

用法：python scripts/prep_ocr.py <抽帧根目录> <ocr输出目录>
"""
import pathlib
import shutil
import sys

sys.stdout.reconfigure(encoding='utf-8')

try:
    from PIL import Image, ImageEnhance, ImageOps
except Exception as e:
    print('NO PIL', e)
    sys.exit(1)

src_root = pathlib.Path(sys.argv[1])
dst_root = pathlib.Path(sys.argv[2])
if dst_root.exists():
    shutil.rmtree(dst_root)
dst_root.mkdir(parents=True)

n = 0
for d in sorted(src_root.iterdir()):
    if not d.is_dir():
        continue
    out = dst_root / d.name
    out.mkdir(exist_ok=True)
    for p in sorted(d.glob('*.jpg')):
        try:
            im = Image.open(p).convert('L')
        except Exception:
            continue
        w, h = im.size
        # 顶部 20% 与底部 22%，各放大 3 倍
        for tag, box in (('T', (0, 0, w, int(h * 0.20))),
                         ('B', (0, int(h * 0.78), w, h))):
            crop = im.crop(box)
            crop = ImageOps.autocontrast(crop, cutoff=1)
            crop = crop.resize((crop.width * 3, crop.height * 3), Image.LANCZOS)
            crop.save(out / ('%s_%s.jpg' % (p.stem, tag)), quality=95)
        n += 1
print('条带帧已生成：%d 个源目录，%d 帧 ×2 条带' % (len(list(dst_root.iterdir())), n))
