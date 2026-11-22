# 已归档（Obsolete）

这里的文件**已停用**，仅作历史参考，不要再执行。

| 文件 | 停用原因 |
|---|---|
| `update_platform_live.py.obsolete` | 上游源已失效：`live.yang-1989.eu.org` 实测 302 到 `404.mp4` 占位视频；`sub.ottiptv.cc/bilibili/*` 大面积 404。脚本不做可播性验证，只做格式转换，会把不可用线路写进源文件。 |
| `PlatformLive.yml.obsolete` | 每 30 分钟运行上述失效脚本，把 `PlatformLive.txt` / `BiliLive.txt` 覆盖成不可用状态。 |
| `TVLives_Sync.yml.obsolete` | 拉取仓库自身旧文件形成自循环，且不做可播性验证，无法剔除失效线路。 |

替代方案：`scripts/build_live_sources.py` + `.github/workflows/LiveSources.yml`
（多上游 → 过滤广告/错台 → 逐条实测可播性 → 合并多线路 → 自动提交）。
