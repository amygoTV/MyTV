"""诊断：枚举指定窗口的子窗口 z-order（从顶到底），判断 mpv 视频窗口是否被 Chromium 渲染层盖住。

用法: python zorder.py <parent_hwnd> [--children]
"""
import ctypes, ctypes.wintypes as w, sys

u = ctypes.windll.user32
ENUMPROC = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)


def wtext(h):
    n = u.GetWindowTextLengthW(h)
    b = ctypes.create_unicode_buffer(n + 1)
    u.GetWindowTextW(h, b, n + 1)
    return b.value


def wclass(h):
    b = ctypes.create_unicode_buffer(256)
    u.GetClassNameW(h, b, 256)
    return b.value


def rect(h):
    r = w.RECT()
    u.GetWindowRect(h, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


parent = int(sys.argv[1])
only_children = '--children' in sys.argv

kids = []
def cb(ch, lp):
    kids.append(ch)
    return True
u.EnumChildWindows(parent, ENUMPROC(cb), 0)

print('parent hwnd=%d class=%r vis=%s rect=%s' % (
    parent, wclass(parent), bool(u.IsWindowVisible(parent)), rect(parent)))
for i, ch in enumerate(kids):
    print('  z%d hwnd=%d class=%r title=%r vis=%s rect=%s' % (
        i, ch, wclass(ch), wtext(ch)[:36], bool(u.IsWindowVisible(ch)), rect(ch)))

if not only_children:
    print('--- top level (z top first, filtered) ---')
    tops = []
    def cb2(h, lp):
        cl = wclass(h); ti = wtext(h)
        if cl in ('mpv', 'Chrome_WidgetWin_1') or 'mpv' in ti.lower():
            tops.append('hwnd=%d class=%r title=%r vis=%s rect=%s' % (
                h, cl, ti[:36], bool(u.IsWindowVisible(h)), rect(h)))
        return True
    u.EnumWindows(ENUMPROC(cb2), 0)
    for t in tops:
        print(' ', t)
