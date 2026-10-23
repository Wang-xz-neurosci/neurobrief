import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('summaries', Path(__file__).resolve().parents[1]/'scripts/summarize_papers.py')
m = importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class SummaryTests(unittest.TestCase):
    def test_cache_hash_changes_when_abstract_changes(self):
        self.assertNotEqual(m.source_hash({'title':'A','abstract':'one'}),m.source_hash({'title':'A','abstract':'two'}))

    def test_budget_uses_daily_and_annual_limits(self):
        settings={'daily_budget_cny':.35,'annual_budget_cny':150}
        cache={'ledger':[{'date':'2026-10-23','budget_charge_cny':.34}]}
        self.assertFalse(m.within_budget(cache,'2026-10-23',.02,settings))
        self.assertTrue(m.within_budget(cache,'2026-10-24',.02,settings))
        self.assertFalse(m.within_budget({'ledger':[{'date':'2026-01-01','budget_charge_cny':150}]},'2026-10-23',.01,settings))

    def test_cached_input_is_billed_separately_from_output(self):
        cost=m.usage_cost({'prompt_tokens':1000,'prompt_cache_hit_tokens':500,'completion_tokens':200},{'input_miss':2,'input_hit':.04,'output':8})
        self.assertAlmostEqual(cost,.00262)

    def test_stale_summary_is_not_attached(self):
        p={'id':'a','title':'A','abstract':'new','summary_zh':'old'}
        data={'papers':[p]}
        m.attach(data,{'entries':{'a':{'status':'success','source_hash':'old'}}},{'prompt_version':'v1','mode':'pilot','pilot_total_limit':12})
        self.assertNotIn('summary_zh',p)
        self.assertEqual(data['summary_status']['ready'],0)

    def test_hallucinated_number_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'unsupported number'):
            m.validate_summary('本研究纳入999名参与者，使用功能磁共振分析语言加工。结果显示不同脑区之间存在功能联系，研究提示语言加工依赖分布式网络。上述结果来自摘要报告的相关性分析，仍需要更多研究验证。','10 participants with fMRI')

    def test_spelled_out_sample_sizes_are_supported(self):
        self.assertTrue({'17','97','7'} <= m.numeric_evidence('Seventeen patients and ninety-seven controls, in seven regions.'))
        self.assertNotIn('3',m.numeric_evidence('one and two'))


if __name__=='__main__':unittest.main()
