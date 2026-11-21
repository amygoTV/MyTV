# 影视舱 MediaShell

一个适合**电脑大屏观看**的影视资源桌面壳软件，基于 Electron + 原生 JS 实现，内置本仓库的影视仓/电视直播配置，开箱即用。

## 版本

当前 **v1.0.0**（详见仓库根目录 `更新日志.md`）。

## 启动

### 已部署成品（D 盘）

双击 `D:\MediaShell\Start MediaShell.bat` 即可启动。程序和数据都在 D 盘：

- 程序：`D:\MediaShell\electron.exe`
- 配置：`D:\MediaShell\resources\app.asar` 内的 `config/`
- 数据（历史/收藏/播放列表）：`D:\MediaShell\userdata\`

> 启动器已自动清除 `ELECTRON_RUN_AS_NODE` / `NODE_OPTIONS` 环境变量，避免与开发工具的 Node 环境冲突。请勿直接双击 `electron.exe`，用 bat 启动。

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
| 采集站 | 内置 `YSCSites.json` 的 21 个站点，侧栏切换；CMS 站（http api）可用，`csp_*` 插件站会灰显并提示（桌面端无法运行影视仓 jar 插件） |
| 首页 | **电视主页风格**：顶部大图 Banner 自动轮播（热播推荐，带标题/播放按钮）、横向分类标签栏、每个分类一行横向滚动海报（鼠标悬停左右滑动）；点分类标签即切换下方横排内容，点「更多」进入完整分页网格 |
| 分类 | 自动解析站点真实 `type_id`（`ac=list`），按分类拉海报，支持分页；首页横排「更多」与分类标签联动 |
| 搜索 | 顶部搜索框回车，在当前 CMS 站按 `wd=` 搜索 |
| 详情 | 海报、简介、主演、多播放源、选集 |
| 播放 | 内嵌 `video` + hls.js 播放 m3u8/mp4；支持「系统播放器」用 PotPlayer/VLC 打开 |
| 直播 | 读取 `TVLives.txt` / `PlatformLive.txt` / `BiliLive.txt` 及赛事 M3U，按分组展示频道，每条 URL 为独立线路 |
| 收藏/历史 | 本地保存（localStorage，位于 D 盘 userdata） |
| 导入订阅 | 侧栏「导入订阅」可填任意影视仓 JSON 地址覆盖当前站点配置 |
| 重载配置 | 侧栏「重载配置」重新读取内置配置 |

## 技术说明

- **跨域**：渲染进程不能直接请求 CMS 接口，所有网络请求走主进程 `http-get` IPC 代理，支持重定向与 GBK 解码。
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
