"""补抓失败源（低并发重试）。

用法：python scripts/ad_refetch.py <抽帧目录> <索引json> [并发数] [重试轮数]
索引 json 需含 idx/url/frames 字段；frames=0 的会被重抓。
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
idx_file = pathlib.Path(sys.argv[2])
workers = int(sys.argv[3]) if len(sys.argv) > 3 else 4
rounds = int(sys.argv[4]) if len(sys.argv) > 4 else 2
DUR, STEP = 30, 3

rows = json.loads(idx_file.read_text(encoding='utf-8'))


def grab(r):
    d = scan_dir / ('s%04d' % r['idx'])
    d.mkdir(parents=True, exist_ok=True)
    cmd = [FFMPEG, '-y', '-i', r['url'], '-t', str(DUR),
           '-vf', 'fps=1/%d,scale=320:180' % STEP, '-q:v', '4', str(d / 'g%03d.jpg')]
    try:
        subprocess.run(cmd, capture_output=True, timeout=DUR + 90)
    except Exception:
        pass
    n = len(list(d.glob('g*.jpg')))
    return r['idx'], n


for rd in range(rounds):
    todo = [r for r in rows if len(list((scan_dir / ('s%04d' % r['idx'])).glob('*.jpg'))) == 0]
    if not todo:
        break
    print('轮次 %d：待抓 %d 个源，并发 %d' % (rd + 1, len(todo), workers), flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        done = 0
        for idx, n in ex.map(grab, todo):
            done += 1
            if done % 20 == 0:
                print('  ... %d/%d' % (done, len(todo)), flush=True)

# 汇总
for r in rows:
    d = scan_dir / ('s%04d' % r['idx'])
    r['frames'] = len(list(d.glob('*.jpg'))) if d.exists() else 0
idx_file.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
got = sum(1 for r in rows if r['frames'] > 0)
print('\n最终：%d/%d 源抓到帧' % (got, len(rows)))
