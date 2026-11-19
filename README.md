# MyTV

TVBox / 影视仓可用的 `TVLives.txt` 直播订阅仓库。

## 订阅地址

```text
https://raw.githubusercontent.com/amygoTV/MyTV/master/TVLives.txt
```

## 文件说明

- `TVLives.txt`：TVBox 文本订阅，格式为 `分组,#genre#` + `频道名,URL`，每条 URL 是独立线路。
- `scripts/validate_tvlives.py`：自动验活脚本，只保留实测可响应的直播源，删除失效源、错台源和点播 MP4。
- `scripts/pinned_sources.txt`：人工复核后固定加入的补充源，每次同步会一起验活，失效会自动剔除。

## 更新机制

GitHub Actions 每 6 小时从 `amygoTV/Livelist` 拉取最新候选源，与本仓库固定补充源合并、并发验活后，只把可用源写入 `TVLives.txt`。无变化不提交。

## 注意

直播源来自公开网络，可用性会随时间、地区和网络运营商变化；本仓库只做技术研究与个人合法使用。
