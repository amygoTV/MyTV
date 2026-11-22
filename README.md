# MyTV

TVBox / 影视仓可用的直播订阅与多仓索引仓库。

## 一、直播订阅 TVLives.txt

### 订阅地址

```text
https://fastly.jsdelivr.net/gh/amygoTV/MyTV@master/TVLives.txt
```

### 文件说明

- `TVLives.txt`：TVBox 文本订阅，格式为 `分组,#genre#` + `频道名,URL`，每条 URL 是独立线路。
- `scripts/channel_plan.json`：**权威频道表**——保证 CCTV1-17、31 省级卫视 + 深圳卫视、中国教育 1-4 台等保底频道永远存在，并定义央视组顺序（CCTV1-17 → 付费 → CGTN → 教育台）与卫视按收视率排名。
- `scripts/build_live_sources.py`：统一构建脚本——权威频道表保底 + 上游补充 → 广告/错台/静态录像过滤 → 逐条实测 IPv4 可播性 → IPv6 备用保留 → 每频道最多 3 条 IPv4 + 2 条 IPv6。探测不足时保留上一版。

### 更新机制

GitHub Actions 每天北京时间 02:17 运行一次（`.github/workflows/LiveSources.yml`）：权威频道表保底 + 上游拉取 → 广告/错台过滤 → 逐条实测可播 → 组装。校验「保底频道齐全 + 央视顺序 + 无地方频道 + 零广告」通过才提交，无变化不提交。IPv6 源（移动 IPTV）无探测出口，作为备用排 IPv4 之后。

> 平台直播（抖音 / B站 / 虎牙 / 斗鱼 / Twitch）已从订阅中移除（原 `PlatformLive.txt` 上游失效，现已停止提供）。B站直播专线见 `BiliLive.txt`。

## 一之二、影视仓单仓配置 YSCSites.json

### 订阅地址

```text
https://fastly.jsdelivr.net/gh/amygoTV/MyTV@master/YSCSites.json
```

### 说明

- 聚合配置共 **21 个采集站 + 6 条直播线路**：保留原有 7 个实测可用的 CMS 采集接口（type=1），新增 14 个垂直分类独立站（短剧、赛事、直播平台、少儿动漫、四类课堂）。
- 全部站点显示名统一为「表情符 + 名字｜类型」格式；原有 7 个 CMS 站也已按此规则重命名，站点 key、API 与分类白名单保持不变。
- 兼容 **LuckyWDGS/YingShiCang 3.6.1**：该版本按 `sites[].categories` 做每站独立的分类白名单。聚合配置里每个站只声明自己的分类；若只想看某一类，可直接导入下面 `YSC/*.json` 单用途配置（每份只有一个站）。
- 原有 CMS 7 站分类继续按 `ac=videolist&t=<type_id>&pg=1` 实测校准：大类标记在前、有数据的子分类在后。短剧 / 漫剧真正有内容的是 `AI漫剧`、`擦边短剧`、`漫剧`、`爽文短剧` 等子分类，点空壳父类可能没资源。
- `spider` 已改为本仓库自托管 `spider/fan.txt`（MD5 `654fb7dcb0aeaaea7dba0e662395f38e`），与影视仓内置 `source-20261022.jar` 完全一致；`csp_AiDjGuard`、`csp_BiliGuard`、`csp_KanqiuGuard`、`csp_LiveGzGuard`、`csp_DoubaoGuard`、`csp_AllliveGuard`、`csp_Dm84Guard` 均可由影视仓内置插件直接加载，不必再依赖第三方 jar 地址。
- 内置直播 `lives`：`TVLives.txt`（央视 CCTV1-17 / 31 省卫视 + 深圳 / 教育台 / 电影 / 体育）、`BiliLive.txt`（B站直播专线）与赛事轮播 M3U。
- 采集接口来自公开采集站，可用性随时间变化；某个源失效时在影视仓内切换其它源即可。

### B站直播镜像

- `BiliLive.txt`：B站直播专线，按分区（情感杂谈 / 户外 / 疗愈助眠等）分组，由工作流每天重建。走 `cdn.jsdelivr.net` 加速，电视端无需直连海外域名。
- 说明：抖音 / 虎牙 / 斗鱼 / Twitch 等平台直播订阅（原 `PlatformLive.txt`）因上游失效已移除。
- 说明：快手自 2025 年底起对匿名访问限流，没有稳定的公开直播订阅；若必须看快手直播，需在「纯粹直播」等客户端中填入自己的快手 Cookie，TVBox 的静态订阅无法提供。

## 一之二之二、电脑桌面版（TVBox Desktop）

Windows 桌面客户端 [TVBox Desktop](https://github.com/hgtuj5688/tvbox-desktop) 可直接加载本仓库的桌面专用配置：

```text
https://fastly.jsdelivr.net/gh/amygoTV/MyTV@master/TVBoxDesktop.json
```

- 该客户端把数字 `type=3` 当苹果 CMS、`type=1` 当网页规则站，与安卓 TVBox 不同；`TVBoxDesktop.json` 已做转换：11 个 CMS 站写为 `type: "cms"`，10 个 `csp_*` Spider 站写为 `type: "spider"`（桌面端会灰显并提示无法运行）。
- 直播线路含 TVLives / BiliLive 与赛事 M3U（原 PlatformLive 已移除）。
- 需要完整短剧 / 赛事 / 课堂 Spider 体验时，请用安卓影视仓加载 `YSCSites.json`；桌面版主要覆盖影视点播与直播。

## 一之三、垂直分类独立采集站（YSC/*.json）

每个文件都是一份可直接导入影视仓的单仓配置，只含一个站点，因此首页分类导航天然互相隔离。地址模板：

```text
https://cdn.jsdelivr.net/gh/amygoTV/MyTV@master/YSC/<文件名>.json
```

| 文件名 | 采集方式 | 主页分类 |
|---|---|---|
| `短剧漫剧.json` | `csp_AiDjGuard`（内置短剧入口） | 插件原生短剧 / 漫剧分类 |
| `短剧点播.json` | CMS type=1 | AI漫剧、擦边短剧、现代都市、古装仙侠、反转爽剧、言情总裁、穿越年代、重生民国、脑洞悬疑 |
| `漫剧点播.json` | CMS type=1 | 漫剧、爽文短剧、擦边短剧、女频恋爱、年代穿越、古装仙侠、现代都市 |
| `看球赛事.json` | `csp_KanqiuGuard` | 插件原生赛事直播分类 |
| `吃瓜看球.json` | `csp_LiveGzGuard` | 插件原生看球分类 |
| `比赛回放.json` | `csp_DoubaoGuard` | 插件原生比赛集锦分类 |
| `赛事点播.json` | CMS type=1 | 足球、篮球、其他赛事 |
| `一直播.json` | `csp_AllliveGuard` | 插件原生直播平台分类 |
| `少儿动漫.json` | `csp_Dm84Guard` | 插件原生少儿动漫分类 |
| `少儿动漫点播.json` | CMS type=1 | 动画片、中国动漫、日本动漫、欧美动漫 |
| `儿童启蒙.json` | `csp_BiliGuard` + `Edu/kids.json` | 儿童早教、儿童启蒙故事、儿童英语启蒙、儿童歌曲、儿童绘画、睡前故事、儿童动画、儿童音乐、儿童安全教育、贝瓦儿歌、悟空识字、宝宝巴士、儿歌多多、学而思（14 类） |
| `小学课堂.json` | `csp_BiliGuard` + `Edu/primary.json` | 1–6 年级语文 / 数学 / 英语（18 类） |
| `初中课堂.json` | `csp_BiliGuard` + `Edu/junior.json` | 7–9 年级语文 / 数学 / 英语 / 历史 / 地理 / 生物 / 物理 / 化学（24 类） |
| `高中课堂.json` | `csp_BiliGuard` + `Edu/senior.json` | 高一 / 高二 / 高三各科及信息技术（28 类） |

- 四类课堂源各自只读取自己的 `Edu/*.json`，分类从 JSON 的 `class[].type_name` 生成并去重，不会把别的学段分类带进首页。
- 这 14 个单用途配置已同时加入 `aizheteng.json`（`urls`）和 `zheteng.json`（`storeHouse`），可在多仓索引里逐项导入；也可以只导入你需要的那一条。

## 二、多仓索引 aizheteng.json

`aizheteng.json` 是影视仓 / 宝盒使用的多仓索引（`urls` 数组），每个子项都是一份单仓配置。

### 订阅地址

```text
https://cdn.jsdelivr.net/gh/amygoTV/MyTV@master/aizheteng.json
```

备用：

```text
https://fastly.jsdelivr.net/gh/amygoTV/MyTV@master/aizheteng.json
```

> 原 Gitee 仓库 `amygotv/tv` 已被封禁（HTTP 423），因此原有固定线路改用本仓库 GitHub 内容的 `cdn.jsdelivr.net` 加速地址。
>
> 索引里 3 条饭太硬系子配置（饭太硬/肥猫/小米）用 `@v1.4.8` 固定版本地址而非 `@master`：规避 jsdelivr 对可变分支的缓存延迟，确保修复后的配置立即生效。后续版本升级时会同步更新这几个 tag。

### 线路说明

- `urls`：21 条线路，全部指向 `github.com/amygoTV/MyTV` 本仓库：原有 6 条 + `💣王炸资源💣` 聚合配置 + 14 条垂直分类单用途配置；**实际输出不含外部站点**，`scripts/aizheteng_sources.json` 里保留的少数外部地址仅作 CI 验活兜底（自托管节点都挂时才可能启用）。
- `zheteng.json` 的 `storeHouse` 同步扩展为 17 条（原有 3 条 + 14 条垂直分类配置）。
- 各单仓配置内的 `lives` 统一指向本仓库的 `TVLives.txt`、`BiliLive.txt`（均通过 `cdn.jsdelivr.net` 加速）。

### 自动更新

- `.github/workflows/Aizheteng_Sync.yml`：每天北京时间 11:17 运行。
- `scripts/aizheteng_sources.json` 的 `pinned` 列表逐条验活，包含原有 6 条、`💣王炸资源💣` 和 14 条垂直分类单用途配置；`sources` 列表已清空，避免外部站点接口被定时任务重新写回。
- `scripts/update_aizheteng.py` 使用 `okhttp/3.15` UA 逐个请求，只有返回 200 且能解析出非空 `sites` 数组的地址才会写入。
- 所有候选都失败时保留上一条可用地址；没有历史地址的新线路会跳过。下载不到 `list.txt` 时不提交，避免误删。
- 新增自有线路：在 `scripts/aizheteng_sources.json` 的 `pinned` 中添加 `name` 和 `urls`（jsdelivr + fastly 双节点）即可；不要用 `raw.githubusercontent.com`，国内/电视端会超时。

### 影视仓 3.6.1 分类适配

- 影视仓 3.6.1 的“电影筛选 / 电视筛选”和“热播电影 / 热播剧集 / 热播综艺”会读取站源实际声明的 `categories` 与筛选项，并按名称识别电影、电视剧、综艺。
- 配置里的 `sites[].categories` 是分类白名单：名称对不上时，该分类不会显示；留空则不限制。
- 已为 8 个带 `categories` 的采集站补全并校准分类：`PG` 的索尼资源、非凡；`moyuer` 的红牛、索尼、光速、极速、量子、非凡。电影、电视剧、综艺、动漫、短剧等大类置于前面，原有细分类保留。
- 其余站源不写 `categories`，由站源自身返回分类，3.6.1 会自动读取。

## 注意

直播源和接口均来自公开网络，可用性会随时间、地区和网络运营商变化；本仓库只做技术研究与个人合法使用，请勿用于商业用途。
