# MyTV

Live TV subscriptions and multi-warehouse indexes for TVBox / 影视仓.

## 1. Live TV playlist

```text
https://fastly.jsdelivr.net/gh/amygoTV/MyTV@master/TVLives.txt
```

- `TVLives.txt`: TVBox text playlist (`group,#genre#` followed by `name,url`).
- `scripts/validate_tvlives.py`: concurrent validator; only responsive streams are kept.
- `scripts/pinned_sources.txt`: manually reviewed extra sources, validated on every sync.

GitHub Actions refreshes the playlist from `amygoTV/Livelist` every 6 hours. Nothing is committed when there are no changes.

## 2. Multi-warehouse index

```text
https://cdn.jsdelivr.net/gh/amygoTV/MyTV@master/aizheteng.json
```

Fallback:

```text
https://fastly.jsdelivr.net/gh/amygoTV/MyTV@master/aizheteng.json
```

The original Gitee repository `amygotv/tv` is blocked (HTTP 423), so the pinned
entries now point to this repository through `cdn.jsdelivr.net`.

- `pinned`: six in-repo configs (饭太硬, 肥猫, 鸟叔 4K, PG, 摸鱼儿, 小米).
- The `lives` array of these six configs points to this repository's `TVLives.txt`
  through `cdn.jsdelivr.net` instead of their own live lists. The original per-line
  live files have been removed.
- `sources`: sixteen entries matched from the public mirror list (南风, 摸鱼 6 线,
  clun, 小马, 挺好, 动漫, 菜妮丝, 高天流云, 香雅情, 健康家用, 老张, 心魔, 俊宇,
  东篱, 夏夏影视, 周 J). Their live sources are controlled by the third-party
  configs and are not modified here.

### Auto-update

- `.github/workflows/Aizheteng_Sync.yml` runs daily at 11:17 Beijing time.
- It downloads the latest `list.txt` from the mirror, matches names declared in
  `scripts/aizheteng_sources.json`, and probes every candidate with a
  `okhttp/3.15` User-Agent.
- A candidate is accepted only when it returns HTTP 200 and a non-empty `sites`
  array. If every candidate fails, the previous working URL is kept; new entries
  without a previous URL are skipped. The workflow does not commit when
  `list.txt` cannot be downloaded.
- To add a source, append `{name, match, fallbacks}` to `sources` in
  `scripts/aizheteng_sources.json`.

### 影视仓 3.6.1 category adaptation

- The movie/TV discovery pages in 影视仓 3.6.1 read each source's declared
  `categories` and filters, and recognize movie, TV drama and variety by name.
- `sites[].categories` acts as an allowlist: names that do not match are hidden,
  while an empty list means no restriction.
- The eight sources that already declared `categories` now have a calibrated
  list: Sony and 非凡 in `PG`; 红牛, Sony, 光速, 极速, 量子 and 非凡 in
  `moyuer`. Movie, TV, variety, anime and short-drama groups come first, and
  the original subcategories are preserved.
- All other sources leave `categories` empty, so 3.6.1 uses the classes returned
  by the source itself.

## Notice

All playlists and interfaces come from the public internet. Availability varies
by time, region and ISP. This repository is for technical research and personal
legal use only; do not use it commercially.
