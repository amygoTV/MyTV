#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""影视舱 MediaShell 应用图标生成器（纯标准库，不依赖 PIL）。

产出：
  build/icon.ico   多尺寸 Windows 图标（16/24/32/48/64/128 BMP + 256 PNG）
  build/icon.png   512x512 透明底 PNG（窗口图标 / 其它用途）

设计：
  * 圆角方形「电视屏幕」底板，深空蓝渐变 #2c3548 -> #0f131c，边缘冷灰描边；
  * 渐变播放三角（品牌色 #ff5c7a -> #6ea8ff），带蓝色柔光；
  * 右上角两段直播信号弧（#6ea8ff），呼应「直播/影视舱」。

用法：python scripts/make_icon.py
"""
import math
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(ROOT, 'build')

SIZE = 512
RADIUS = 112.0

# 主题色
TILE_TOP = (0x2c, 0x35, 0x48)
TILE_BOTTOM = (0x0f, 0x13, 0x1c)
TILE_EDGE = (0x4a, 0x56, 0x70)
ACCENT = (0xff, 0x5c, 0x7a)
ACCENT2 = (0x6e, 0xa8, 0xff)


# ----------------------------------------------------------------- PNG 输出
def write_png(path, width, height, pixels):
    """pixels: bytearray, RGBA, 长度 width*height*4"""
    stride = width * 4
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw += pixels[y * stride:(y + 1) * stride]
    comp = zlib.compress(bytes(raw), 9)

    def chunk(tag, data):
        return (struct.pack('>I', len(data)) + tag + data +
                struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff))

    out = b'\x89PNG\r\n\x1a\n'
    out += chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
    out += chunk(b'IDAT', comp)
    out += chunk(b'IEND', b'')
    with open(path, 'wb') as f:
        f.write(out)
    return len(out)


# ----------------------------------------------------------------- 基础数学
def clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else (hi if v > hi else v)


def mix(c1, c2, t):
    t = clamp(t)
    return (c1[0] + (c2[0] - c1[0]) * t,
            c1[1] + (c2[1] - c1[1]) * t,
            c1[2] + (c2[2] - c1[2]) * t)


def sd_round_rect(px, py, x0, y0, x1, y1, r):
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0
    hx = (x1 - x0) / 2.0 - r
    hy = (y1 - y0) / 2.0 - r
    dx = abs(px - cx) - hx
    dy = abs(py - cy) - hy
    ax = max(dx, 0.0)
    ay = max(dy, 0.0)
    outside = math.hypot(ax, ay)
    inside = min(max(dx, dy), 0.0)
    return outside + inside - r


def sd_segment(px, py, ax, ay, bx, by):
    vx = bx - ax
    vy = by - ay
    wx = px - ax
    wy = py - ay
    den = vx * vx + vy * vy
    t = 0.0 if den == 0 else clamp((wx * vx + wy * vy) / den)
    dx = wx - vx * t
    dy = wy - vy * t
    return math.hypot(dx, dy)


def sd_rounded_polygon(px, py, verts, r):
    """凸多边形圆角后的有符号距离（内负外正）。"""
    n = len(verts)
    normals = []
    for i in range(n):
        ax, ay = verts[i]
        bx, by = verts[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        ln = math.hypot(dx, dy) or 1.0
        normals.append((-dy / ln, dx / ln))  # CCW -> 内法线
    inset = []
    for i in range(n):
        vx, vy = verts[i]
        n1 = normals[i - 1]
        n2 = normals[i]
        den = 1.0 + (n1[0] * n2[0] + n1[1] * n2[1])
        k = r / den if den else 0.0
        inset.append((vx + (n1[0] + n2[0]) * k, vy + (n1[1] + n2[1]) * k))
    best = 1e9
    for i in range(n):
        ax, ay = inset[i]
        bx, by = inset[(i + 1) % n]
        d = sd_segment(px, py, ax, ay, bx, by) - r
        if d < best:
            best = d
    return best


def sd_arc_band(px, py, cx, cy, radius, half_w, a0, a1):
    """圆弧带（环形扇段）的距离近似。"""
    dx = px - cx
    dy = py - cy
    ang = math.atan2(dy, dx)
    # 弧段角度范围（以 0 度为 +x 轴，逆时针）
    lo, hi = a0, a1
    if hi - lo >= 2 * math.pi:
        return abs(math.hypot(dx, dy) - radius) - half_w
    # 归一化到 [-pi, pi]
    while ang < lo:
        ang += 2 * math.pi
    while ang > hi:
        ang -= 2 * math.pi
    if ang < lo or ang > hi:
        # 端点圆角
        ex = cx + radius * math.cos(lo)
        ey = cy + radius * math.sin(lo)
        fx = cx + radius * math.cos(hi)
        fy = cy + radius * math.sin(hi)
        return min(math.hypot(px - ex, py - ey), math.hypot(px - fx, py - fy)) - half_w
    return abs(math.hypot(dx, dy) - radius) - half_w


# ----------------------------------------------------------------- 图标绘制
def render():
    w = h = SIZE
    px = bytearray(w * h * 4)
    # 播放三角（CCW）：略偏左，给右上角信号弧留位置
    tri = [(160.0, 186.0), (160.0, 326.0), (330.0, 256.0)]
    tri_r = 24.0
    # 信号弧（右上角，向右上扩散）
    arc_c = (348.0, 140.0)
    arcs = [(58.0, 6.5, math.radians(-64), math.radians(26)),
            (96.0, 6.5, math.radians(-64), math.radians(26))]
    for y in range(h):
        fy = y + 0.5
        row = y * w * 4
        for x in range(w):
            fx = x + 0.5
            # --- 底板
            sd = sd_round_rect(fx, fy, 0, 0, w, h, RADIUS)
            cov = clamp(0.5 - sd)
            if cov <= 0.0:
                continue
            base = mix(TILE_TOP, TILE_BOTTOM, clamp((fy / h) * 1.05))
            # 顶部高光
            hl = clamp(1.0 - fy / (h * 0.55)) * 0.10
            base = mix(base, (255, 255, 255), hl)
            r, g, b = base

            # --- 三角柔光
            sd_tri = sd_rounded_polygon(fx, fy, tri, tri_r)
            if sd_tri > 0:
                glow = math.exp(-sd_tri / 22.0) * 0.30
                glow2 = math.exp(-sd_tri / 62.0) * 0.12
                r = r + (ACCENT2[0] - r) * glow + (ACCENT2[0] - r) * glow2
                g = g + (ACCENT2[1] - g) * glow + (ACCENT2[1] - g) * glow2
                b = b + (ACCENT2[2] - b) * glow + (ACCENT2[2] - b) * glow2

            # --- 信号弧
            sd_arc = 1e9
            for radius, hw, a0, a1 in arcs:
                sd_arc = min(sd_arc, sd_arc_band(fx, fy, arc_c[0], arc_c[1],
                                                 radius, hw, a0, a1))
            cov_arc = clamp(0.5 - sd_arc)
            if cov_arc > 0:
                ag = clamp(1.0 - sd_arc / 22.0) * 0.22
                r = r + (ACCENT2[0] - r) * ag
                g = g + (ACCENT2[1] - g) * ag
                b = b + (ACCENT2[2] - b) * ag
                r = r + (ACCENT2[0] - r) * cov_arc
                g = g + (ACCENT2[1] - g) * cov_arc
                b = b + (ACCENT2[2] - b) * cov_arc

            # --- 播放三角本体
            cov_tri = clamp(0.5 - sd_tri)
            if cov_tri > 0:
                tc = mix(ACCENT, ACCENT2, clamp((fx - 190.0) / 250.0))
                r = r + (tc[0] - r) * cov_tri
                g = g + (tc[1] - g) * cov_tri
                b = b + (tc[2] - b) * cov_tri

            # --- 描边
            sd_edge = abs(sd_round_rect(fx, fy, 3.0, 3.0, w - 3.0, h - 3.0,
                                         RADIUS - 3.0)) - 1.6
            cov_edge = clamp(0.5 - sd_edge)
            if cov_edge > 0:
                r = r + (TILE_EDGE[0] - r) * cov_edge * 0.85
                g = g + (TILE_EDGE[1] - g) * cov_edge * 0.85
                b = b + (TILE_EDGE[2] - b) * cov_edge * 0.85

            i = row + x * 4
            px[i] = int(clamp(r, 0, 255))
            px[i + 1] = int(clamp(g, 0, 255))
            px[i + 2] = int(clamp(b, 0, 255))
            px[i + 3] = int(clamp(cov, 0, 1) * 255)
    return w, h, px


# ----------------------------------------------------------------- 缩放
def resize_rgba(src, sw, sh, dw, dh):
    """面积平均缩放（盒式滤波），输出 RGBA bytearray。"""
    dst = bytearray(dw * dh * 4)
    for y in range(dh):
        y0 = int(y * sh / dh)
        y1 = max(y0 + 1, int((y + 1) * sh / dh))
        for x in range(dw):
            x0 = int(x * sw / dw)
            x1 = max(x0 + 1, int((x + 1) * sw / dw))
            r = g = b = a = 0
            n = 0
            for sy in range(y0, min(y1, sh)):
                base = sy * sw * 4
                for sx in range(x0, min(x1, sw)):
                    i = base + sx * 4
                    r += src[i]
                    g += src[i + 1]
                    b += src[i + 2]
                    a += src[i + 3]
                    n += 1
            o = (y * dw + x) * 4
            if n:
                dst[o] = r // n
                dst[o + 1] = g // n
                dst[o + 2] = b // n
                dst[o + 3] = a // n
    return dst


def downsample_png_bytes(pixels, w, h, size):
    """把 RGBA 缩放并编码为 PNG 字节（用于 ICO 的 256 PNG 条目）。"""
    import io
    small = resize_rgba(pixels, w, h, size, size)
    stride = size * 4
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        raw += small[y * stride:(y + 1) * stride]
    comp = zlib.compress(bytes(raw), 9)

    def chunk(tag, data):
        return (struct.pack('>I', len(data)) + tag + data +
                struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff))

    return (b'\x89PNG\r\n\x1a\n' +
            chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0)) +
            chunk(b'IDAT', comp) + chunk(b'IEND', b''))


# ----------------------------------------------------------------- ICO 打包
def bmp_entry(pixels, w, h):
    """生成 ICO 内的 DIB（BITMAPINFOHEADER + 32bpp BGRA + AND 掩码）。"""
    header = struct.pack('<IiiHHIIiiII', 40, w, h * 2, 1, 32, 0,
                         w * h * 4, 0, 0, 0, 0)
    xor = bytearray()
    for y in range(h - 1, -1, -1):          # BMP 自下而上
        row = y * w * 4
        for x in range(w):
            i = row + x * 4
            xor += bytes((pixels[i + 2], pixels[i + 1], pixels[i], pixels[i + 3]))
    mask_stride = ((w + 31) // 32) * 4
    mask = bytearray()
    for y in range(h - 1, -1, -1):
        row = y * w * 4
        bits = bytearray(mask_stride)
        for x in range(w):
            if pixels[row + x * 4 + 3] < 128:
                bits[x >> 3] |= 0x80 >> (x & 7)
        mask += bits
    return bytes(header) + bytes(xor) + bytes(mask)


def build_ico(entries):
    """entries: [(size, payload_bytes)] -> ICO 字节"""
    count = len(entries)
    out = bytearray(struct.pack('<HHH', 0, 1, count))
    offset = 6 + 16 * count
    for size, payload in entries:
        w = 0 if size >= 256 else size
        out += struct.pack('<BBBBHHII', w, w, 0, 0, 1, 32, len(payload), offset)
        offset += len(payload)
    for _, payload in entries:
        out += payload
    return bytes(out)


def main():
    if not os.path.isdir(BUILD):
        os.makedirs(BUILD)
    print('渲染 %dx%d 主图...' % (SIZE, SIZE))
    w, h, pixels = render()

    png512 = os.path.join(BUILD, 'icon.png')
    n = write_png(png512, w, h, pixels)
    print('  build/icon.png  %d bytes' % n)

    entries = []
    for size in (16, 24, 32, 48, 64, 128, 256):
        small = resize_rgba(pixels, w, h, size, size)
        entries.append((size, bmp_entry(small, size, size)))
    ico = build_ico(entries)
    ico_path = os.path.join(BUILD, 'icon.ico')
    with open(ico_path, 'wb') as f:
        f.write(ico)
    print('  build/icon.ico  %d bytes  (sizes: %s)' %
          (len(ico), ', '.join(str(s) for s, _ in entries)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
