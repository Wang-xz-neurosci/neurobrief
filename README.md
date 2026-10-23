# NeuroBrief · 每日认知神经科学资讯

面向组内阅读的公开每日文献资讯。正式地址：
https://wang-xz-neurosci.github.io/neurobrief/

## 四个研究方向

- 语言与大脑：言语、语义、句法、阅读与语篇理解的脑机制。
- 结构与功能：白质纤维束、脑结构连接、结构—功能耦合，以及结构如何支持或约束功能。纯功能研究不进入此类。
- 脑疾病机理：使用 EEG、MEG、fMRI、DWI/DTI 或 fNIRS 等研究疾病人群的认知与脑属性。要求临床人群证据，排除综述、研究方案、勘误、仅动物研究和仅 T1 结构像研究；词表不能替代人工核实实际方法。
- 静息态与自然刺激：静息态，以及电影、故事、自然语音和语篇等自然刺激研究。

一篇文献可以进入多个方向。英文检索式和分类证据写在 `config/topics.json`，不是人工质量评审。结构类要求结构证据，但摘要中的背景介绍也可能命中，需要后续用组内样例调整。

## 已实现

- 通过 Europe PMC 官方接口免费获取 PubMed 记录和预印本；仅中文概览使用单独配置的 DeepSeek API。
- 固定从 **2026-09-01 首次发表**的文献开始追踪，较早或缺少有效首次发表日期的记录不展示。以后每日更新并积累，不是滚动删除到仅剩一个月。
- 每日查询来源新入库、变更与最近发表记录，并重叠 1 天以覆盖时区和收录延迟。每周一只补查上一自然周（周一至周日）的文章；周一失败后可补执行。**不再定期从 9 月 1 日重抓，规则变更也不会自动触发历史全量查询。**停机后的日常增量从上次成功日期接续。
- 28 本关注期刊另做独立 ISSN 扫描，再判断相关性。按“综合与认知神经”“脑影像与连接”“临床神经与精神”分组，名单公开显示在页面中，不按影响因子设置硬门槛。包含 Neuroscience & Biobehavioral Reviews 与 Trends in Cognitive Sciences。
- 四方向筛选、标题／作者／DOI／原始摘要搜索、日期／方法／文献类型筛选。
- 可切换“全部期刊／关注期刊／三个方向分组”。方法菜单为 fMRI、DTI、EEG、MEG、颅内电生理、其他。DTI 是合并展示标签，包含扩散成像与纤维追踪；仅 T1 结构像和 fNIRS 归为其他。
- DOI／来源编号去重，预印本与综述标记，本机收藏，RIS 导出到 Zotero。
- 网站优先读取压缩文献数据，原始 JSON 保留供核对。
- RSS 文件继续供已有阅读器使用，每份最近 50 篇；页面已移除 RSS 入口，普通读者不必打开原始 XML。
- GitHub Actions 每天北京时间 08:17 更新数据并发布到 GitHub Pages。
- 显示“MM/DD 已更新，本日收录文献 N 篇”。N 是该更新日按北京时间首次进入本站的去重文献数，含延迟收录记录；同日重跑不重复计数。当天新发表数和新收录数不同。
- 任何方向抓取失败或分页不完整时，保留上一次成功数据；页面显示最近成功时间，超过两天未更新会提醒。

## 发布到 Wang-xz-neurosci 的 GitHub

1. 创建公开仓库 `Wang-xz-neurosci/neurobrief`，默认分支 `main`。
2. 将本目录的 `dist`、`config`、`data`、`scripts`、`tests`、`.github`、`.gitignore` 和 README 放到仓库根目录。不要遗漏隐藏的 `.github/workflows/daily-update.yml`。
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
python scripts/summarize_papers.py --attach-only
python scripts/build_feeds.py
python scripts/build_public_data.py
python scripts/check_site.py
node --check dist/app.js
python -m http.server 8765 --bind 127.0.0.1 --directory dist
```

打开 http://127.0.0.1:8765/ 。可直接验证 `?topic=structure-function` 等分享链接。

## 调整分类与信源

编辑 `config/topics.json` 的 `required_term_groups`、`evidence_terms`、`clinical_imaging_only` 与 `monitored_journals`，然后重新运行采集和生成 RSS。`*` 明确表示词尾通配，连字符在本地匹配时按空格处理。

同一组词表自动生成 Europe PMC 的 TITLE_ABS／KW 查询，同时用于本地分类；不再手工维护两份容易不一致的检索式。远端 KW 包含 MeSH，用于提高候选召回；本地相关性与方法判定使用标题、摘要和作者关键词，避免仅凭宽泛的 MeSH 标签误收。

更新时按照当前规则重新分类整个档案、重算方法、移除范围外记录，保留首次收录时间。规则变更只会重分类已保存记录，不会自动从固定起点联网重抓。仅改菜单不能替代此过程。

已知漏检样例放在 `coverage_sentinels`：Cao 等的语言侧化综述（DOI `10.1016/j.tins.2026.09.001`，首次发表 2026-09-15）。旧版依赖 language processing／language network 等固定短语，远端查询和本地分类均漏掉它。新版涵盖 language／speech／语义、句法、阅读等表述与脑背景，并加入 KW 检索。该文必须真实出现在数据中且正确归入语言方向，否则更新失败，不靠单独硬塞记录修复。

每次成功更新保存完整检索式、每路候选数、各方向保留数量、最新发表日期和每日新收录统计；GitHub Actions Summary 同步展示。抓取或分页失败时拒绝替换上次成功数据。以上是检索与工程防回归检查，不能证明学术领域完整召回率。

`config/site.json` 设置公开站点地址及仓库；更换地址时同步修改页面的更新记录链接，并重新生成 RSS。

## 中文概览试阅与密钥

- 当前为 **两轮共 24 篇跨方向试阅**，入口为“中文总结试阅”。默认展示本轮新增的 12 篇 150–200 字精简概览，可切换上轮 12 篇原版或全部试阅。上轮缓存保留原样。概览默认显示在题目与作者下方，原始摘要可展开核对。其余文章继续显示英文原始摘要。
- 模型为 `deepseek-flash`，关闭思考和工具调用，每篇最多 550 输出 tokens；固定系统提示词置于最前，保存一次生成的结果，浏览器访问不会调用模型。
- 仅传送单篇题目与摘要，不传送 API Key 之外的个人资料，也不把历史聊天传给模型。完整、有效摘要才生成；内容过长时跳过，不静默截断。
- Secret 名称为 **DEEPSEEK_API_KEY**，只配置在 GitHub → Settings → Secrets and variables → Actions。不得把实际值写入代码、JSON、`.env`、命令参数或仓库。更新 Secret 不要求修改代码，也不要求把密钥贴到公开位置。
- 本地需要生成时运行 `python scripts/summarize_papers.py --key-stdin`，在隐藏输入提示中粘贴；普通本地预览用 `--attach-only`，不需要 Key。
- `config/summaries.json` 固定两轮 24 个样例及累计试阅上限，生成满后定时任务只附加已缓存结果，不扩量、不处理全部历史。后续扩量需要明确修改配置。
- 新版生成按实际字符数（含标点和英文字符）校验 150–200 字；仅在模型已返回结果但长度不符时，最多另付费请求两次长度修正。每次调用独立记账并检查预算，不截断摘要，不重试不明网络失败。
- `data/summary_cache.json` 只保存可公开概览、摘要哈希和用量账本，不含密钥。摘要有变更时不展示过期概览。缓存和费用账本会在后续部署检查前单独提交，避免检查失败后重复扣费。
- 程序阈值为每日 0.35 元、每年 150 元；按官方高峰价格、缓存未命中和输出上限预留费用，网络结果不明确时保留预留额，不自动重试。账本为程序估算，不代替 DeepSeek 账单。价格配置以 2026-10-23 官方页面为准，需要随供应商调价更新。
- 数字、语言、长度与来源哈希有自动检查；未通过的结果不会公开，不能替代科研内容的人工判断。固定前缀缓存是尽力命中，不能把整体成本理解成降到 1/50。

## 数据与运行边界

- 主采集入口是 Europe PMC，限定 MED 和 PPR，已含 PubMed 记录以及 bioRxiv 等预印本。关注期刊扫描也通过其官方 API；目前没有直接爬取出版商网站或另接 PubMed／bioRxiv 接口。源头收录延迟和关键词遗漏仍然存在。
- 原始摘要保留来源原文；中文概览处于 DeepSeek 两轮共 24 篇试阅阶段，不读取付费全文、不做质量评分。
- 发表日期、来源收录日期、本站首次收录日期分别保存；不把它们混称为发表时间。
- DOI 不同的预印本与正式发表版尚未自动关联，可能分别展示。
- 分类来自标题、摘要和作者关键词；方法标签要求标题或摘要证据（优先 Methods 部分），可能命中背景内容，不能替代阅读原文。临床人群研究的自动筛选也会有误报与漏报。
- 收藏只保存在当前浏览器，不跨设备同步；可导出 RIS 长期保留。
- GitHub 定时任务可能延迟；公开仓库 60 天无活动时任务可能暂停，以页面时间与 Actions 记录为准。
- 使用免费公开 Pages 和标准 Ubuntu Actions 运行器；没有付费域名或服务器；DeepSeek 按实际 token 用量计费。平台免费政策与额度以官方说明为准。

官方资料：
- https://europepmc.org/RestfulWebService
- https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages
- https://docs.github.com/en/billing/concepts/product-billing/github-actions


- https://api-docs.deepseek.com/zh-cn/quick_start/pricing/
- https://api-docs.deepseek.com/guides/kv_cache/
