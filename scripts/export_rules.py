"""Export the exact configured vocabulary and live review prompt for inspection."""
import json
from pathlib import Path
import textwrap

import review_papers as review

ROOT = Path(__file__).resolve().parents[1]


def main():
    config = json.loads((ROOT/'config/topics.json').read_text(encoding='utf-8'))
    data = json.loads((ROOT/'data/candidates.json').read_text(encoding='utf-8'))
    groups, topic_groups = {}, {}
    for topic in config['topics']:
        topic_groups[topic['id']] = []
        for terms in topic['required_term_groups']:
            key = tuple(terms)
            if key not in groups:
                groups[key] = f'G{len(groups)+1:02}'
            topic_groups[topic['id']].append(groups[key])
    lines = ['# Europe PMC 实际检索词、筛选逻辑与 DeepSeek 提示词', '',
             f"词表版本：`{config['classification_version']}`。以下直接由 config/topics.json 与正在运行的 review_papers.py 导出。", '',
             '## 检索逻辑', '',
             '每个词组内部是 OR，同一方向的各词组之间是 AND。每组同时检索 TITLE_ABS（题目/摘要）和 KW（关键词，含来源的 MeSH 索引）。`*` 是词尾通配符。词组编号只用于避免重复抄写公共词表，不改变真实检索式。', '',
             '| 方向 | 必须同时满足的词组 | 来源限制 |', '| --- | --- | --- |']
    for topic in config['topics']:
        lines.append(f"| {topic['name']} | {' AND '.join(topic_groups[topic['id']])} | {'仅关注期刊（ISSN）' if topic.get('monitored_only') else '不限期刊；包含预印本'} |")
    lines += ['', '另有一条关注期刊 ISSN 扫描，不依赖方向词命中，用于发现词表可能漏掉的文章；取得记录后仍须通过本地候选规则和相关性判断。', '',
              '所有查询均限定首次发表日期为 2026-09-01 起，来源为 MED、PMC、PPR。日常新增窗口是最近成功采集日期前一天至当天；查询近期发表、近期首次入库或近期更新的记录（条件之间为 OR）。周一只额外补查上一自然周，不从 9 月 1 日全量重抓。', '',
              '生成式：`方向词组条件 AND FIRST_PDATE:[2026-09-01 TO 当天] AND (近期首次发表 OR 近期 FIRST_IDATE OR 近期 UPDATE_DATE) AND (SRC:MED OR SRC:PMC OR SRC:PPR)`。', '',
              f"最近一次实际运行：{data['as_of']}，窗口为 `{json.dumps(data.get('collection_plan', {}), ensure_ascii=False)}`。逐字查询见 [europe-pmc-queries.txt](europe-pmc-queries.txt)。", '', '## 完整词组', '']
    for terms, name in groups.items():
        lines += [f'### {name}（{len(terms)} 项）', '', '```text',
                  textwrap.fill(' OR '.join(terms), width=112, break_long_words=False, break_on_hyphens=False), '```', '']
    lines += ['## 取得候选后的筛选顺序', '',
              '1. 清理来源标记，按 DOI、来源编号及别名去重，保留真实首次收录日期；排除早于收录起点或无有效首次发表日期的记录。',
              '2. 本地按题目、原始摘要和作者关键词匹配候选；明显研究方案、勘误/撤稿、非脑器官或标题明确的仅动物研究先排除。纯背景词由模型结合语境进一步判断。',
              '3. 其余有摘要且未有匹配缓存的候选逐篇交给 DeepSeek。只提供原始题目和摘要，要求给出相关性决定、栏目、简短原因和原文证据。不做期刊质量或统计显著性评分。',
              '4. 信息不足、无摘要或判定无法核实时按已约定的主题和期刊条件暂留。尚未调用模型的 pending 与已经返回 uncertain 是不同状态，分别记账、后续接续。',
              '5. 模型归类后再次检查来源：其他认知与脑、脑疾病机理只允许 44 本关注期刊的正式文章；其余三个方向可以收录名单外文章和预印本。结构与功能仍需结构或白质证据词；白质功能信号本身符合此项。',
              '6. 对最终收录且有摘要的文章生成中文概览；成功缓存按题目与摘要哈希复用。无摘要不编造。方法标签另由题目/摘要推断，不代表人工核实。', '',
              '## DeepSeek 实际 SYSTEM 提示词（完整原文）', '', '```text', review.SYSTEM_PROMPT, '```', '',
              '## 每篇文献附带的 USER 消息', '', '```text', review.USER_INSTRUCTION.rstrip(),
              '{"title":"该文原始标题","abstract":"该文完整原始摘要"}', '```', '',
              'SYSTEM 提示词保持固定以尽可能复用前缀缓存。正常缓存按标题、摘要及规则版本识别；不是每天把全部档案重新交给模型。该提示词用于是否收录的判断，中文概览有另一份写作提示词。', '',
              '## 关注期刊（一个合并名单）', '']
    lines += [f"- {j['name']}（{', '.join([j['issn'], *j.get('other_issns', [])])}）" for j in config['monitored_journals']]
    folder = ROOT/'docs'
    folder.mkdir(exist_ok=True)
    (folder/'retrieval-and-screening.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    (folder/'europe-pmc-queries.txt').write_text('\n\n'.join(
        f"{q['topic']}\n{q['query']}\n{q.get('request_url','')}" for q in data['queries'])+'\n', encoding='utf-8')
    print(f'Exported {len(groups)} exact keyword groups, {len(data["queries"])} queries and the complete live review prompt.')


if __name__ == '__main__':
    main()
