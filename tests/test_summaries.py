import importlib.util
from pathlib import Path
import unittest
import copy
import json
import tempfile
from unittest.mock import patch
from urllib.error import URLError

spec = importlib.util.spec_from_file_location('summaries', Path(__file__).resolve().parents[1]/'scripts/summarize_papers.py')
m = importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
TEMP_ROOT = Path(__file__).resolve().parents[1] / '.local'


class SummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TEMP_ROOT.mkdir(exist_ok=True)

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

    def test_new_length_limits_reject_instead_of_truncating(self):
        for size in (150, 200):
            text = '文' * size
            self.assertEqual(m.validate_summary(text, '', 150, 200), text)
        for size in (149, 201):
            with self.assertRaises(m.SummaryLengthError):
                m.validate_summary('文' * size, '', 150, 200)

    def test_legacy_summary_still_attaches_without_modification(self):
        p = {'id':'old', 'title':'A', 'abstract':'B'}
        entry = {'status':'success','summary_zh':'文'*318, 'source_hash':m.source_hash(p),
                 'prompt_version':'v1','model':'prior-model','generated_at':'prior-time'}
        cache = {'entries':{'old':entry}}
        before = copy.deepcopy(cache)
        m.attach({'papers':[p]}, cache, {'prompt_version':'v2','accepted_prompt_versions':['v1','v2'],
                                      'mode':'pilot','pilot_total_limit':24})
        self.assertEqual(p['summary_zh'], entry['summary_zh'])
        self.assertEqual(p['summary_meta']['prompt_version'], 'v1')
        self.assertEqual(cache, before)

    def fixture(self):
        return ({'id':'new','title':'An imaging study','abstract':'A research abstract.'},
                {'entries':{},'ledger':[]},
                {'model':'test-model','prompt_version':'v2','min_summary_chars':150,'max_summary_chars':200,
                 'max_length_retries':2,'max_output_tokens':550,'daily_budget_cny':.35,'annual_budget_cny':150,
                 'pricing_cny_per_million':{'input_miss':2,'input_hit':.04,'output':8}})

    def response(self, text):
        return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'summary_zh':text})}}],
                'usage':{'prompt_tokens':1000,'completion_tokens':200}}

    def test_length_correction_is_bounded_and_every_call_is_charged(self):
        p, cache, settings = self.fixture()
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as folder, patch.object(m,'ROOT',Path(folder)):
            path = Path(folder)/'cache.json'
            with patch.object(m,'complete',side_effect=[self.response('文'*250),self.response('文'*180)]) as api:
                self.assertEqual(m.generate_one(p,cache,settings,'test-key',path,'2026-10-23'),'success')
                self.assertEqual(api.call_count,2)
            self.assertEqual(len(cache['entries']['new']['summary_zh']),180)
            self.assertEqual(len(cache['ledger']),2)
            self.assertTrue(all(x['budget_charge_cny']>0 for x in cache['ledger']))
            cache['entries'].clear();cache['ledger'].clear()
            with patch.object(m,'complete',return_value=self.response('文'*250)) as api:
                self.assertEqual(m.generate_one(p,cache,settings,'test-key',path,'2026-10-23'),'rejected')
                self.assertEqual(api.call_count,3)
            self.assertEqual(len(cache['ledger']),3)
            self.assertNotIn('summary_zh',cache['entries']['new'])

    def test_ambiguous_network_error_is_not_retried(self):
        p, cache, settings = self.fixture()
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as folder:
            with patch.object(m,'complete',side_effect=URLError('connection lost')) as api:
                self.assertEqual(m.generate_one(p,cache,settings,'test-key',Path(folder)/'cache.json','2026-10-23'),'stop')
                self.assertEqual(api.call_count,1)
        self.assertEqual(len(cache['ledger']),1)
        self.assertGreater(cache['ledger'][0]['budget_charge_cny'],0)

    def test_short_return_gets_an_expansion_instruction(self):
        p, cache, settings = self.fixture()
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as folder:
            with patch.object(m,'complete',side_effect=[self.response('文'*140),self.response('文'*175)]) as api:
                self.assertEqual(m.generate_one(p,cache,settings,'test-key',Path(folder)/'cache.json','2026-10-23'),'success')
                correction = api.call_args.args[0][-1]['content']
                self.assertIn('当前过短',correction)
                self.assertIn('增加约35个字符',correction)
        self.assertEqual(len(cache['entries']['new']['summary_zh']),175)

    def test_pilot_generation_skips_existing_success_and_keeps_its_metadata(self):
        p, cache, settings = self.fixture()
        old = {'id':'old','title':'Old study','abstract':'old abstract '*30}
        p['abstract'] *= 20
        entry = {'status':'success','summary_zh':'原'*318,'source_hash':m.source_hash(old),
                 'prompt_version':'v1','model':'prior-model','generated_at':'prior-time','review_status':'reviewed'}
        cache['entries']['old'] = entry
        before = copy.deepcopy(entry)
        settings.update(mode='pilot',accepted_prompt_versions=['v1','v2'],pilot_ids=['old','new'],
                        pilot_total_limit=24,max_per_run=12,max_abstract_chars=12000)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as folder, patch.object(m,'ROOT',Path(folder)):
            root = Path(folder);(root/'config').mkdir()
            m.atomic_json(root/'config/summaries.json',settings)
            m.atomic_json(root/'data.json',{'papers':[old,p]})
            m.atomic_json(root/'cache.json',cache)
            with patch('sys.argv',['summarize','--data',str(root/'data.json'),'--cache',str(root/'cache.json')]), \
                 patch.dict('os.environ',{'DEEPSEEK_API_KEY':'test-key'}), \
                 patch.object(m,'complete',return_value=self.response('文'*180)) as api:
                m.main()
                self.assertEqual(api.call_count,1)
            after = json.loads((root/'cache.json').read_text(encoding='utf-8'))
            self.assertEqual(after['entries']['old'],before)
            self.assertEqual(len(after['entries']),2)


if __name__=='__main__':unittest.main()
