# NeuroBrief · 认知神经科学文献站

面向组内阅读的公开文献站。正式地址（完成发布后生效）：
https://wang-xz-neurosci.github.io/neurobrief/

## 四个研究方向

- 语言与大脑：言语、语义、句法、阅读与语篇理解的脑机制。
- 结构与功能：白质纤维束、脑结构连接、结构—功能耦合，以及结构如何支持或约束功能。纯功能研究不进入此类。
- 脑疾病机理：自闭症、抑郁症、焦虑障碍、阿尔茨海默病、ADHD、中风等相关精神与神经疾病的脑机制。
- 静息态与自然刺激：静息态，以及电影、故事、自然语音和语篇等自然刺激研究。

一篇文献可以进入多个方向。英文检索式和分类证据写在 `config/topics.json`，不是人工质量评审。结构类要求结构证据，但摘要中的背景介绍也可能命中，需要后续用组内样例调整。

## 已实现

- 通过 Europe PMC 官方接口获取 PubMed 记录和预印本，不需要付费采集服务或模型 API Key。
- 初次回溯 90 天，此后保留历史；补查最近收录的记录，减少来源收录延迟造成的漏检。
- 四方向筛选、标题／作者／DOI／原始摘要搜索、日期／方法／文献类型筛选。
- DOI／来源编号去重，预印本与综述标记，本机收藏，RIS 导出到 Zotero。
- 网站优先读取压缩文献数据，原始 JSON 保留供核对。
- 总 RSS `feed.xml` 和四个分方向 RSS，每份提供最近 50 篇。
- GitHub Actions 每天北京时间 08:17 更新数据并发布到 GitHub Pages。
- 任何方向抓取失败或分页不完整时，保留上一次成功数据；页面显示最近成功时间，超过两天未更新会提醒。

## 发布到 Wang-xz-neurosci 的 GitHub

1. 创建公开仓库 `Wang-xz-neurosci/neurobrief`，默认分支 `main`。
2. 将本目录的 `dist`、`config`、`scripts`、`tests`、`.github`、`.gitignore` 和 README 放到仓库根目录。不要遗漏隐藏的 `.github/workflows/daily-update.yml`。
3. 在 Settings → Pages 将 Source 设为 **GitHub Actions**。
4. 首次 push 或 Actions → Update papers and publish → Run workflow 会采集并发布。`update` 与 `deploy` 都成功后，才算上线。
5. 在 https://github.com/Wang-xz-neurosci/neurobrief/actions 查看运行记录，在 Pages 设置页查看正式地址。

也可以在已登录 GitHub CLI 的本机运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/publish_github.ps1
```

脚本会核对登录账号、初始化当前目录的 Git 仓库、创建或检查指定公开仓库，通过 GitHub 官方 REST 接口上传并核对文件哈希、开启 Pages、发布 main。遇到已存在且不属于本项目的远端历史会停止，不强制覆盖。初次发布可能需要几分钟。

仓库和网页均公开。账号登录和发布不要求在聊天里提供密码或令牌。

## 本机预览与验证

需要 Python 3.10+；采集只用标准库。Node.js 仅用于检查前端 JavaScript 语法。

```powershell
python -m unittest discover -s tests -v
python scripts/update_papers.py
python scripts/build_feeds.py
python scripts/build_public_data.py
python scripts/check_site.py
node --check dist/app.js
python -m http.server 8765 --bind 127.0.0.1 --directory dist
```

打开 http://127.0.0.1:8765/ 。可直接验证 `?topic=structure-function` 等分享链接。

## 调整分类与信源

编辑 `config/topics.json` 的检索式与 `required_term_groups`，然后重新运行采集和生成 RSS。

更新时会按照当前规则重新分类整个历史档案，移除退休标签，保留首次收录时间。范围不再匹配的文献不展示；旧版源数据在最初交付目录中保留。规则变更时自动重新回溯配置时间段，无需删掉现有档案。仅改菜单名称不能替代此过程。

`config/site.json` 设置公开站点地址及仓库；更换地址时同步修改页面的更新记录链接，并重新生成 RSS。

## 数据与运行边界

- 唯一采集入口是 Europe PMC，限定 MED 和 PPR；不是所有期刊或所有预印本的完整扫描。
- 标题和摘要使用来源原文，本版不做 AI 中文摘要或质量评分，不复制付费全文。
- 发表日期、来源收录日期、本站首次收录日期分别保存；不把它们混称为发表时间。
- DOI 不同的预印本与正式发表版尚未自动关联，可能分别展示。
- 分类和方法标签来自标题与摘要，可能命中背景内容，不能替代阅读原文。
- 收藏只保存在当前浏览器，不跨设备同步；可导出 RIS 长期保留。
- GitHub 定时任务可能延迟；公开仓库 60 天无活动时任务可能暂停，以页面时间与 Actions 记录为准。
- 使用免费公开 Pages 和标准 Ubuntu Actions 运行器；没有付费模型、域名或服务器。平台免费政策与额度以官方说明为准。

官方资料：
- https://europepmc.org/RestfulWebService
- https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages
- https://docs.github.com/en/billing/concepts/product-billing/github-actions

