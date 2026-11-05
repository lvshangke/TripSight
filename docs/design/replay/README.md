# 演示重放脚本（参考）

`docs/videos/*-flow.mp4` 和预览 GIF 是用这些脚本录的：真实引擎生成的数据快照 + Playwright 在真实页面上拦截 `/tok/api/**` 回放，再用 ffmpeg 转 mp4/GIF（加“演示重放”角标）。

- `lib.py`：录制器（假光标、点击涟漪、录屏）。
- `plan_rec.py` / `restore_rec.py` / `film_rec.py`：计划行程、恢复行程、旅行短片三条流程的回放脚本。
- `shots_*.py`：静态截图。

这些脚本里的路径（`/mnt/user-data/...`）、数据快照（`_demo/out/*.json`）和页面快照（`_page_rp.html`，由 `tripcore.webpage.page_html()` 生成）是我当时的工作环境，换机器要改路径并重新生成快照；想改的多半是文字、顺序和等待时间，直接改脚本里对应的 `rc.w(...)`、`rc.type(...)` 即可。
编辑视频本身，用任何剪辑软件打开 mp4 即可（没有独立的工程文件）。
