# 影视舱 MediaShell

一个适合**电脑大屏观看**的影视资源桌面壳软件，基于 Electron + 原生 JS 实现，内置本仓库的影视仓/电视直播配置，开箱即用。

## 版本

### v1.7.0
- 直播源改为影视仓/TVBox 标准 TXT（UTF-8 BOM + CRLF、一行一条线路、同名频道合并为多线路），本地内置 `TVLives.txt` / `BiliLive.txt` / `LiveSports.txt` 全部刷新到最新版本。
- 站点配置切到永久固定地址链：`zheteng_v2.json`（主 cdn + 备 gcore）→ `aizheteng_v2.json` → `YSCv3/` → `TVLives_v2.m3u`。
- 修复：`parseTVLines` 按频道名合并同名行（此前同一频道会显示成多条重名条目），并剥离 BOM、兼容 `,` 与 `#` 两种地址分隔。


当前 **v1.7.0**（开发日志见独立仓库 [MediaShell-DevLog](https://github.com/amygoTV/MediaShell-DevLog)）。

### 单文件便携版（推荐）

发布页 `MediaShell便携版.exe`（约 66MB）——双击即用，自解压到本机临时目录运行，无需 bat 启动器、无需散落 dll。启动后如需持久化收藏/历史，可设置环境变量 `MSHELL_DATA` 指向固定目录（默认随解压目录）。

### 直播页

左侧可折叠频道分类栏（同名频道去重、多源线路合并），右侧播放器预览；画面左下角切换线路，支持超时自动换线、解码方式（硬件/软件/自动）与播放器（内置 / mpv / VLC / PotPlayer，自动检测本机安装）选择。检测到 mpv 时优先用其硬件解码，显著降低直播卡顿。

直播流经**主进程本地代理**（`127.0.0.1:19871`）转发：绝大多数 IPTV 源不返回 CORS 头，浏览器直连会被拦截，代理负责拉取 m3u8、重写分片地址并透传 TS 字节流。右上角「🔍 检测线路」可并发实测每条线路是否可播，侧栏显示 `可用/总数`，点击频道时自动优先选用已验证可用的线路。

直播页性能：频道量已达 2800+，用 Map 索引 + 事件委托 + 分组按需渲染（默认每组 60 个，可展开），实测 DOM 节点 3004 → 391、渲染 135ms → 4ms。本地源毫秒级先渲染，远程赛事源后台追加（首屏 13.3s → 0.12s）。

## 启动

### 已部署成品（D 盘）

双击 `D:\MediaShell\Start MediaShell.bat` 即可启动。程序和数据都在 D 盘：

- 程序：`D:\MediaShell\electron.exe`
- 配置：`D:\MediaShell\resources\app.asar` 内的 `config/`
- 数据（历史/收藏/播放列表）：`D:\MediaShell\userdata\`

> 启动器已自动清除 `ELECTRON_RUN_AS_NODE` / `NODE_OPTIONS` 环境变量，避免与开发工具的 Node 环境冲突。请勿直接双击 `electron.exe`，用 bat 启动。
>
> 注意：Electron 必须在**应用目录内**启动（bat 里的 `cd /d "%~dp0"` 就是为此）。若用 `electron.exe <应用路径>` 的方式传入路径参数，Electron 会忽略该参数，导致配置不加载、界面空白。

### 从源码重建

```bat
cd DesktopShell
npm install --registry https://registry.npmmirror.com
npm install electron@28.3.3 asar --save-dev --registry https://registry.npmmirror.com
build.bat
```

`build.bat` 会把源码打包为 `app.asar`，并复制到 `..\MediaShellApp\resources\app.asar`。

## 功能

| 模块 | 说明 |
|---|---|
| 采集站 | 内置 `YSCSites.json` 的 19 个站点（9 个 CMS + 10 个插件源），侧栏切换；启动时自动测速并选最快的可用站，CMS 站（http api）可用，`csp_*` 插件站会灰显并提示（桌面端无法运行影视仓 jar 插件） |
| 首页 | **电视主页风格**：顶部大图 Banner 自动轮播（热播推荐，带标题/播放按钮）、横向分类标签栏、每个分类一行横向滚动海报（鼠标悬停左右滑动）；点分类标签即切换下方横排内容，点「更多」进入完整分页网格。**多站竞速**取数（并发 3 站，先回先用）+ 骨架屏 + 5 分钟缓存，实测首屏 95ms 出 32 张海报、203ms 分类就绪（45 个） |
| 分类 | 自动解析站点真实 `type_id`（`ac=list`），按分类拉海报，支持分页；首页横排「更多」与分类标签联动 |
| 搜索 | 顶部搜索框回车，在当前 CMS 站按 `wd=` 搜索 |
| 详情 | 海报、简介、主演、多播放源、选集；鼠标悬停海报即后台预取详情，点击秒开（实测 1.1s） |
| 播放 | 内嵌 `video` + hls.js 播放 m3u8/mp4；支持「系统播放器」用 PotPlayer/VLC 打开 |
| 直播 | 读取 `TVLives.txt` / `BiliLive.txt`（由 GitHub Actions 每天重建并验证，央视 CCTV1-17 + 31 省卫视 + 深圳卫视保底）及赛事 M3U，按分组展示频道；同名频道合并多线路，经主进程流媒体代理播放 |
| 自动选站 | 侧栏「⚡ 自动选站」并发测速全部 CMS 站，一键切到最快可用站 |
| 收藏/历史 | 本地保存（localStorage，位于 D 盘 userdata） |
| 导入订阅 | 侧栏「导入订阅」可填任意影视仓 JSON 地址覆盖当前站点配置 |
| 重载配置 | 侧栏「重载配置」重新读取内置配置 |

## 直播源自动重建

`scripts/build_live_sources.py` 是直播源的统一筛选流水线，每 6 小时由 `.github/workflows/LiveSources.yml` 自动执行：

1. 拉取多个上游 m3u（实测可播率：huyayqk 94% / douyuyqk 95% / yylunbo 95% / IPTV-V4 85% / CNTV-V4 82% / bililive 15%）
2. 规则过滤广告台（频道名特征 + 广告/图床域名 + 静态录像后缀）
3. **逐条实测可播性**（并发探测，只保留真正返回 m3u8 的线路）
4. 修正错台（一条流被标成多个台名 → 只保留一个；同名不同 URL → 合并为多线路）
5. 名称归一 + 同名合并，输出 `TVLives.txt` / `BiliLive.txt`

跑完会自动校验格式与广告残留，不通过则不提交。上游缺失的频道（如 CCTV6）由脚本内置的「保底线路」补齐。

手动执行：

```bash
python3 scripts/build_live_sources.py                    # 全量
python3 scripts/build_live_sources.py --probe-limit 60    # 快速通道
```

## 技术说明

- **跨域**：渲染进程不能直接请求 CMS 接口，所有网络请求走主进程 `http-get` IPC 代理，支持重定向与 GBK 解码。
- **安全防护**：实测部分采集站域名过期后被拍卖，会 302 跳转到博彩类域名。主进程 HTTP 与流媒体代理均对重定向目标做黑名单校验，命中即拒绝跟随；这类被劫持的站点已从配置移除。
- **超时语义**：主进程 `http-get` 的 `timeout` 为**总预算**（含自动重试），渲染层全部超时收敛在 5~9 秒，避免「以为 8s 实际等 15s」。
- **自动自检**：`electron.exe --selftest`（或 `MSHELL_SELFTEST=1`）会输出 `userdata/selftest.json`（首页取数耗时、直播目录、代理抽样）与 `selftest-ui.json`（首屏海报数/分类数），便于回归验证。
- **数据源**：所有请求直连采集站/CMS，壳本身不托管任何影视内容，仅提供浏览与播放界面。
- **不写 C 盘**：Electron `userData` 通过 `app.setPath` 指向应用目录下的 `userdata/`，历史收藏、播放列表、会话数据全部落在 D 盘。
- **兼容性**：仅支持苹果 CMS `provide/vod` 接口（type=1 的 http 站）；影视仓专用 Spider 插件站（`csp_*`，需 jar）在桌面端不可用，需使用安卓影视仓。
- **HLS**：hls.js 随包内置（`vendor/hls.min.js`），无需联网加载播放器。

## 目录结构

```
DesktopShell/
  main.js          Electron 主进程：窗口、配置读取、HTTP 代理、外部播放器
  preload.js       contextBridge 安全暴露 IPC
  index.html       页面结构
  style.css        深色大屏样式
  app.js           渲染逻辑：站点/分类/海报墙/搜索/详情/直播/播放
  config/          内置配置（YSCSites.json、三份直播 txt 等）
  vendor/hls.min.js  HLS 播放器
  build.bat         打包脚本
  .gitignore
```

## 许可

MIT。影视资源来自公开采集站，请遵守当地法律法规，仅作个人学习研究使用。
