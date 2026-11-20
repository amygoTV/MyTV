# MyTV

TVBox / 影视仓可用的直播订阅与多仓索引仓库。

## 一、直播订阅 TVLives.txt

### 订阅地址

```text
https://raw.githubusercontent.com/amygoTV/MyTV/master/TVLives.txt
```

### 文件说明

- `TVLives.txt`：TVBox 文本订阅，格式为 `分组,#genre#` + `频道名,URL`，每条 URL 是独立线路。
- `scripts/validate_tvlives.py`：自动验活脚本，只保留实测可响应的直播源，删除失效源、错台源和点播 MP4。
- `scripts/pinned_sources.txt`：人工复核后固定加入的补充源，每次同步会一起验活，失效会自动剔除。
- `scripts/ad_blacklist.txt`：人工抽帧确认过的广告台 / 错台源黑名单（正则匹配），同步时先过滤再做验活。

### 更新机制

GitHub Actions 每 6 小时从 `amygoTV/Livelist` 拉取最新候选源，与本仓库固定补充源合并、并发验活后，只把可用源写入 `TVLives.txt`。无变化不提交。

## 二、多仓索引 aizheteng.json

`aizheteng.json` 是影视仓 / 宝盒使用的多仓索引（`urls` 数组），每个子项都是一份单仓配置。

### 订阅地址

```text
https://gh-proxy.com/raw.githubusercontent.com/amygoTV/MyTV/master/aizheteng.json
```

备用：

```text
https://raw.githubusercontent.com/amygoTV/MyTV/master/aizheteng.json
```

> 原 Gitee 仓库 `amygotv/tv` 已被封禁（HTTP 423），因此原有固定线路改用本仓库 GitHub 内容的 `gh-proxy.com` 加速地址。

### 线路说明

- `pinned`：本仓库自带的 6 条固定线路（饭太硬、肥猫、鸟叔 4K、PG、摸鱼儿、小米），指向 `github.com/amygoTV/MyTV` 下的单仓配置。
- 这 6 条固定线路的 `lives` 已统一指向本仓库根目录的 `TVLives.txt`（通过 `gh-proxy.com` 加速），不再各自维护直播源；原各线路自带的直播文件已删除。
- `sources`：从海量接口备份站自动匹配的 16 条线路，包括南风、摸鱼 6 线、clun、小马、挺好、动漫、菜妮丝、高天流云、香雅情、健康家用、老张、心魔、俊宇、东篱、夏夏影视、周 J。这些外部线路的直播源由第三方配置决定，不在本仓库内修改。

### 自动更新

- `.github/workflows/Aizheteng_Sync.yml`：每天北京时间 11:17 运行。
- 先从备份站镜像下载当日 `list.txt`，再按 `scripts/aizheteng_sources.json` 中的 `match` 名称匹配最新地址。
- `scripts/update_aizheteng.py` 使用 `okhttp/3.15` UA 逐个请求，只有返回 200 且能解析出非空 `sites` 数组的地址才会写入。
- 所有候选都失败时保留上一条可用地址；没有历史地址的新线路会跳过。下载不到 `list.txt` 时不提交，避免误删。
- 新增线路：在 `scripts/aizheteng_sources.json` 的 `sources` 中添加 `name`、`match`（对应 `list.txt` 第一列去掉 `.json`）和可选的 `fallbacks` 即可。

## 注意

直播源和接口均来自公开网络，可用性会随时间、地区和网络运营商变化；本仓库只做技术研究与个人合法使用，请勿用于商业用途。
