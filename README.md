# NeuroBrief · 每日认知神经科学资讯

面向组内阅读的公开每日文献资讯。正式地址：
https://wang-xz-neurosci.github.io/neurobrief/

## 五个研究方向

- 语言与脑：语言的神经机制与结构基础。
- 其他认知与脑：除语言外，其他认知功能的神经机制与结构基础。仅关注期刊。
- 结构与功能：白质纤维束、灰质形态、结构—功能耦合，以及白质中的功能信号与连接；白质功能研究无需同时具备结构分析。
- 脑疾病机理：借助脑疾病与脑损伤探索认知、脑发育和可塑性。仅关注期刊；相关结构 MRI、综述、病损研究和有机制价值的单病例均可纳入。
- 静息态与自然刺激：自发脑活动与网络组织，以及电影、故事、自然语音、语篇等情境中的脑加工。

## 候选与正式收录

词表先宽范围发现候选；明确规则排除研究方案、勘误和明显非脑内容；其余有摘要的新候选由 DeepSeek 依据原始标题与摘要逐篇判断相关性及栏目。临床背景不等于排除，诊疗服务、分类预测、手术定位为核心的文章通常不纳入。研究相关性不等于质量评分，不按显著性或样本大小设硬门槛，不使用用户举例文章的标题黑名单。

`data/candidates.json` 保存候选来源记录；`data/relevance_cache.json` 保存判定与原文证据，按标题、摘要和规则版本复用。信息不足或模型判定无法核对时，符合基本主题与期刊条件的文章暂留；无摘要不编造总结。`dist/data.json` 只包含最终展示的文献。两个受限制栏目同时在远端 ISSN 检索与最终标签环节检查期刊资格，预印本不进入这两栏。

本次一次性补查新栏目自 2026-09-01 的记录，并复核原有文献；今后仍是每日增量和每周上一自然周补查。已有匹配来源摘要的中文概览继续复用。

语义审查要求给出原文中的连续短引文。引文或格式核验失败时暂留，不自动循环付费；维护者可通过工作流的 `repair_reviews` 显式修复一次这类返回，正常判定和已有概览不重跑。

## 已实现

- 通过 Europe PMC 官方接口免费获取 PubMed 记录和预印本；相关性判定和中文概览使用配置的 DeepSeek API。
- 固定从 **2026-09-01 首次发表**的文献开始追踪，较早或缺少有效首次发表日期的记录不展示。现阶段每日更新并积累；归档安排另由维护者决定，目前没有自动删减历史文献。
- 每日查询来源新入库、变更与最近发表记录，并重叠 1 天以覆盖时区和收录延迟。每周一只补查上一自然周（周一至周日）的文章；周一失败后可补执行。**不再定期从 9 月 1 日重抓，规则变更也不会自动触发历史全量查询。**停机后的日常增量从上次成功日期接续。
- 44 本关注期刊按 ISSN 与准确刊名识别，合并为一个名单，包含 eLife 与 Frontiers in Neurology；名单不代表单篇文章质量。
- 五方向筛选、标题／作者／DOI／原始摘要搜索、日期／方法／文献类型筛选。“今日收录”按北京时间的首次收录日期筛选当前方向，包含此前发表但今天补收的文章，保留用户当前排序选项；不受发表时间近七天限制。
- 可切换“全部期刊／关注期刊”。方法菜单为 fMRI、DTI、EEG、MEG、颅内电生理、其他。DTI 是合并展示标签，包含扩散成像与纤维追踪；仅 T1 结构像和 fNIRS 归为其他。
- DOI／来源编号去重，预印本与综述标记，本机收藏，RIS 导出到 Zotero。
- 首屏内嵌最近 50 篇精简记录；后台读取完整列表并缓存在 IndexedDB；原始摘要按需读取。搜索时读取完整摘要索引，RIS 导出时读取完整版本，保留原有范围。资产按内容哈希隔离版本，缓存不会混用不同版本的数据。45 秒请求上限只用于停止无限等待，不循环自动重试。
- RSS 文件继续供已有阅读器使用，每份最近 50 篇；页面已移除 RSS 入口，普通读者不必打开原始 XML。
- 自 2026-10-27 起以北京时间 08:00 左右完成日更为目标。GitHub Actions 在 03:10–10:55 每 15 分钟轻量检查，07:50 前不采集；首次可用时隙执行当天一次采集，成功后其他检查跳过。早发出的事件可在调度延迟后补位，仍不能保证整点。采集已保存而发布失败时仅重试发布，不重复检索或调用模型。
- 显示“MM/DD 已更新，本日收录文献 N 篇”。N 是该更新日按北京时间首次进入本站的去重文献数，含延迟收录记录；同日重跑不重复计数。当天新发表数和新收录数不同。
- 任何方向抓取失败或分页不完整时，保留上一次成功数据；页面显示最近成功时间，超过两天未更新会提醒。

## 发布到 Wang-xz-neurosci 的 GitHub

1. 创建公开仓库 `Wang-xz-neurosci/neurobrief`，默认分支 `main`。
2. 将本目录的 `dist`、`config`、`data`、`scripts`、`tests`、`.github`、`.gitignore` 和 README 放到仓库根目录。不要遗漏隐藏的 `.github/workflows/daily-update.yml`。
3. 在 Settings → Pages 将 Source 设为 **GitHub Actions**。
4. push 通常只发布保存的数据；首次语义筛选迁移由规则版本标记触发一次补查和全量审查，成功发布后不再重复。Actions → Run workflow 勾选 collect_now 可显式立即采集；正常日更由日期门控执行。`update` 与 `deploy` 都成功后，才算上线。
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
python scripts/refresh_metadata.py
python scripts/summarize_papers.py --attach-only
python scripts/build_feeds.py
python scripts/build_public_data.py
python scripts/check_site.py
node --check dist/app.js
python -m http.server 8765 --bind 127.0.0.1 --directory dist
```

打开 http://127.0.0.1:8765/ 。可直接验证 `?topic=structure-function` 等分享链接。

## 调整分类与信源

编辑 `config/topics.json` 的 `required_term_groups`、`evidence_terms`、`monitored_only` 与 `monitored_journals`，然后用 refresh_metadata.py 应用已保存判定并生成 RSS；修改语义标准时同步更新 config/relevance.json 的 version，在授权运行中重新审查；后续联网采集继续按日常增量执行。`*` 明确表示词尾通配，连字符在本地匹配时按空格处理。

同一组词表自动生成 Europe PMC 的 TITLE_ABS／KW 查询，同时用于本地候选识别；不再手工维护两份容易不一致的检索式。远端 KW 包含 MeSH，用于提高候选召回；最终相关性使用标题与原始摘要的语义判定；方法标签使用标题与摘要，避免仅凭宽泛的 MeSH 标签误收。

更新时按照当前规则重新分类整个档案、重算方法、移除范围外记录，保留首次收录时间。规则变更只会重分类已保存记录，不会自动从固定起点联网重抓。仅改菜单不能替代此过程。

已知漏检样例放在 `coverage_sentinels`：Cao 等的语言侧化综述（DOI `10.1016/j.tins.2026.09.001`，首次发表 2026-09-15）。旧版依赖 language processing／language network 等固定短语，远端查询和本地分类均漏掉它。新版涵盖 language／speech／语义、句法、阅读等表述与脑背景，并加入 KW 检索。该文必须真实出现在数据中且正确归入语言方向，否则更新失败，不靠单独硬塞记录修复。

每次成功更新保存完整检索式、每路候选数、各方向保留数量、最新发表日期和每日新收录统计；GitHub Actions Summary 同步展示。抓取或分页失败时拒绝替换上次成功数据。以上是检索与工程防回归检查，不能证明学术领域完整召回率。

`config/site.json` 设置公开站点地址及仓库；更换地址时同步修改页面的更新记录链接，并重新生成 RSS。

## 自动中文概览与密钥

- 全部有摘要的已收录文献及后续新增文章自动生成中文概览，题目与作者下方默认显示；取消试阅入口。现有已接受的概览缓存继续复用，原始摘要始终可展开核对。缺少摘要时如实标记，不根据题目编造结果。
- 延续第二轮的简短表达：重点讲研究问题和主要发现，通常约 150–200 字。字数只作写作目标，不设置长度验收门槛，不因短于 150 或长于 200 字重新付费生成。
- 模型为 `deepseek-flash`，关闭思考和工具调用，输出上限 800 tokens；固定系统提示词置于最前。只传送单篇题目与摘要，浏览器访问不调用模型。超过配置输入上限时不截断摘要。
- Secret 名称为 **DEEPSEEK_API_KEY**，只配置在 GitHub → Settings → Secrets and variables → Actions。实际值不写入代码、JSON、环境文件、命令参数或仓库。
- 本地仅预览用 `python scripts/summarize_papers.py --attach-only`；需要本地生成时用 `--key-stdin` 隐藏输入。云端每日采集后生成新增、待处理或摘要有变更的文章，已匹配当前摘要的成功缓存不会重复计费。
- `config/summaries.json` 设置审查与总结共享常态每日 0.45 元、全年 150 元上限。初始总结补齐使用单独的 20 元预算组，限定于 2026-10-23 及以前首次收录的记录，仍累计到全年额度。本次筛选迁移及新文献总结另设一次性 25 元上限，仍计入同一年度额度。并发请求在发出前逐个预留最坏费用，用量返回后才结算；未核实的请求保留预留费用。
- 云端最多并发 8 个请求，单轮派发约 11 分钟后停止并等待在途请求结束，后续任务继续未完成记录。每 200 次返回保存缓存到仓库；任务结束另留 3 天缓存及未通过内容检查候选的附件备份。排队任务读取 main 最新版本，提交前同步远端。
- 对空内容、非中文、危险内容、摘要未支持的数字和无效 JSON 进行检查；仅内容或格式异常最多另调用一次，不因字数修正。不明网络失败不在当天自动重试，下一更新日可恢复；内容检查仍未通过的记录留待显式复查。此类程序检查不能代替科研判断。
- `data/summary_cache.json` 保存可公开概览、来源哈希和用量账本，不含密钥。摘要变更时不展示过期概览。费用账本是基于官方价格的估算，不代替 DeepSeek 账单。固定前缀缓存是尽力命中，不能把整体费用理解成降到 1/50。

## 数据与运行边界

- 主采集入口是 Europe PMC，包含 MED、PMC 和 PPR，已含 PubMed 记录以及 bioRxiv 等预印本。关注期刊扫描也通过其官方 API；目前没有直接爬取出版商网站或另接 PubMed／bioRxiv 接口。源头收录延迟和关键词遗漏仍然存在。
- 原始摘要保留来源原文；中文概览由 DeepSeek 依据题目与摘要自动生成，不读取付费全文、不做质量评分。
- 发表日期、来源收录日期、本站首次收录日期分别保存；不把它们混称为发表时间。
- DOI 不同的预印本与正式发表版尚未自动关联，可能分别展示。
- 候选来自标题、摘要和作者关键词，最终归类参考缓存的 AI 语义判定；方法标签要求标题或摘要证据（优先 Methods 部分），可能命中背景内容，不能替代阅读原文。临床人群研究的自动筛选也会有误报与漏报。
- 收藏只保存在当前浏览器，不跨设备同步；可导出 RIS 长期保留。
- GitHub 定时任务可能延迟；公开仓库 60 天无活动时任务可能暂停，以页面时间与 Actions 记录为准。
- 页脚归档说明目前只作提示，预计 2027/01/01；尚未实现自动归档、删文献或清理本机收藏。
- Europe PMC 使用官方 REST API，不批量抓取主站 HTML；串行请求最多约每秒一次。遇到 429／503 尊重 Retry-After，较长限流保存冷却状态；401／403 不反复请求并暂停 6 小时。普通网页访问只读取自己的静态数据，不增加 Europe PMC 请求。
- 使用免费公开 Pages 和标准 Ubuntu Actions 运行器；没有付费域名或服务器；DeepSeek 按实际 token 用量计费。平台免费政策与额度以官方说明为准。

官方资料：
- https://europepmc.org/RestfulWebService
- https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages
- https://docs.github.com/en/billing/concepts/product-billing/github-actions


- https://api-docs.deepseek.com/zh-cn/quick_start/pricing/
- https://api-docs.deepseek.com/guides/kv_cache/

日更门控见 config/update_policy.json、scripts/update_gate.py；dist/update-status.json 是轻量成功采集标记，随 Pages 一起发布。页面与数据源的已采集时间一致后，当天不再抓取。data/source_cooldown.json 保存来源限流／拒绝后的冷却状态。修改页面和本地分类不会改变真实采集时间及首次收录日期。

官方说明：https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule ；https://europepmc.org/help 。60 天无仓库活动可能暂停定时工作流，不是清除仓库或已发布网站。日常成功采集会真实提交数据更新。
