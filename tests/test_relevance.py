import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import review_papers as r
import update_papers as u
import build_public_data as public
import summarize_papers as summaries


class RelevanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT/'.local').mkdir(exist_ok=True)
    def setUp(self):
        self.config=json.loads((ROOT/'config/topics.json').read_text(encoding='utf-8'))
        self.settings=json.loads((ROOT/'config/relevance.json').read_text(encoding='utf-8'))
        self.paper={'id':'doi:example','doi':'example','title':'White matter functional signals in human memory',
                    'abstract':'We studied human memory using white matter BOLD signals and functional connectivity.',
                    'journal':'NeuroImage','journal_issns':['1053-8119'],'published':'2026-10-01',
                    'first_seen':'2026-10-25T16:01:00Z','is_preprint':False,'authors':'A','tracts':[],
                    'url':'https://doi.org/example','source_url':'https://europepmc.org/article/MED/1','source':'MED','source_id':'1'}
    def dataset(self,p=None):
        return {'schema_version':1,'papers':[p or self.paper],'updated_at':'2026-10-26T04:00:00Z','as_of':'2026-10-26',
                'initial_coverage_start':'2026-09-01','update_summary':{'date':'2026-10-26','new_papers':1,'new_in_run':1},'queries':[]}
    def cache(self,decision='include',topics=None,p=None):
        p=p or self.paper
        return {'entries':{p['id']:{'status':'success','fingerprint':r.fingerprint(p,self.settings),
                    'result':{'decision':decision,'topics':topics if topics is not None else ['structure-function','cognition'],
                              'reason':'研究白质信号与人类记忆。','evidence':'white matter BOLD signals'}}}}
    def test_white_matter_function_without_diffusion_is_in_scope(self):
        d=r.apply_reviews(self.dataset(),self.cache(),self.settings,self.config)
        self.assertIn('structure-function',d['papers'][0]['topics'])
        self.assertNotIn('DTI',d['papers'][0]['methods'])
    def test_gray_functional_review_does_not_inherit_structural_topic(self):
        p={**self.paper,'title':'Language lateralization across timescales',
           'abstract':'We review human language functional connectivity and its developmental reorganization.'}
        d=r.apply_reviews(self.dataset(p),self.cache(topics=['language','structure-function','cognition'],p=p),self.settings,self.config)
        self.assertEqual(d['papers'][0]['topics'],['language','cognition'])
    def test_regional_structural_volume_remains_eligible(self):
        p={**self.paper,'title':'Infant hippocampal volume and emotion development',
           'abstract':'MRI measured hippocampal volume in human infants and related it to emerging emotion regulation.'}
        d=r.apply_reviews(self.dataset(p),self.cache(p=p),self.settings,self.config)
        self.assertIn('structure-function',d['papers'][0]['topics'])
    def test_journal_limits_are_per_topic_and_apply_after_ai(self):
        p={**self.paper,'journal':'Unlisted','journal_issns':[]}
        d=r.apply_reviews(self.dataset(p),self.cache(topics=['language','cognition','brain-disorders'],p=p),self.settings,self.config)
        self.assertEqual(d['papers'][0]['topics'],['language'])
    def test_preprints_cannot_bypass_restricted_topics_with_journal_name(self):
        p={**self.paper,'is_preprint':True}
        d=r.apply_reviews(self.dataset(p),self.cache(p=p),self.settings,self.config)
        self.assertEqual(d['papers'][0]['topics'],['structure-function'])
    def test_uncertain_and_missing_abstract_are_retained(self):
        for abstract in [self.paper['abstract'],'']:
            p={**self.paper,'abstract':abstract}
            cache=self.cache(decision='uncertain',topics=[],p=p) if abstract else {'entries':{}}
            d=r.apply_reviews(self.dataset(p),cache,self.settings,self.config)
            self.assertTrue(d['papers'])
            self.assertEqual(d['papers'][0]['relevance']['status'],'uncertain' if abstract else 'missing_abstract')
    def test_explicit_exclusion_removes_article_but_keeps_source(self):
        data=self.dataset();original=copy.deepcopy(data)
        out=r.apply_reviews(data,self.cache(decision='exclude',topics=[]),self.settings,self.config)
        self.assertEqual(out['papers'],[]);self.assertEqual(data,original)
    def test_source_and_rule_version_invalidate_cache(self):
        entry=self.cache()['entries'][self.paper['id']]
        self.assertTrue(r.valid(self.paper,entry,self.settings))
        self.assertFalse(r.valid({**self.paper,'abstract':'Changed'},entry,self.settings))
        self.assertFalse(r.valid(self.paper,entry,{**self.settings,'version':'future'}))
    def test_quote_must_come_from_original_text(self):
        result=self.cache()['entries'][self.paper['id']]['result']
        self.assertEqual(r.validate(result,self.paper,self.config),result)
        with self.assertRaises(ValueError):r.validate({**result,'evidence':'invented participant findings'},self.paper,self.config)
    def test_review_cannot_invent_topics(self):
        result=self.cache()['entries'][self.paper['id']]['result']
        with self.assertRaises(ValueError):r.validate({**result,'topics':['invented']},self.paper,self.config)
    def test_clear_exclusions_apply_even_if_ai_says_include(self):
        p={**self.paper,'title':'Memory MRI: protocol for a trial'}
        self.assertEqual(r.apply_reviews(self.dataset(p),self.cache(p=p),self.settings,self.config)['papers'],[])
    def test_patient_background_does_not_ban_valid_human_study(self):
        p={**self.paper,'abstract':'Mouse studies motivated this study. We scanned human participants performing a memory task.'}
        self.assertIsNone(u.basic_exclusion(p))
    def test_both_restricted_queries_use_all_journal_issns(self):
        for t in self.config['topics']:
            if t['id'] in ('cognition','brain-disorders'):
                query=u.topic_query(t,self.config['monitored_journals'])
                self.assertIn('ISSN:"2050-084X"',query)
                self.assertIn('ISSN:"1664-2295"',query)
                with self.assertRaises(ValueError):u.topic_query(t)
    def test_journal_names_are_not_substring_matches(self):
        self.assertFalse(u.mark_journal({**self.paper,'journal':'Neurology. Clinical practice','journal_issns':[]},self.config)['is_monitored_journal'])
        self.assertTrue(u.mark_journal({**self.paper,'journal':'Cortex; a journal devoted to the study of the nervous system and behavior','journal_issns':[]},self.config)['is_monitored_journal'])
    def test_daily_count_is_recomputed_after_filtering_without_new_first_seen(self):
        d=r.apply_reviews(self.dataset(),self.cache(),self.settings,self.config)
        self.assertEqual(d['update_summary']['new_papers'],1)
        self.assertEqual(d['papers'][0]['first_seen'],self.paper['first_seen'])
    def test_review_spending_counts_against_summary_budget(self):
        budget=json.loads((ROOT/'config/summaries.json').read_text(encoding='utf-8'))
        ledger={'ledger':[{'date':'2026-10-26','budget_charge_cny':budget['daily_budget_cny'],'task':'relevance'}]}
        self.assertFalse(summaries.within_budget(ledger,'2026-10-26',.001,budget))
    def test_new_candidates_are_reviewed_once_and_paid_usage_is_shared(self):
        budget=json.loads((ROOT/'config/summaries.json').read_text(encoding='utf-8'))
        budget['run_budget_group']=self.settings['migration_id']
        result=self.cache()['entries'][self.paper['id']]['result']
        response={'usage':{'prompt_tokens':100,'prompt_cache_hit_tokens':50,'completion_tokens':60},
                  'choices':[{'finish_reason':'stop','message':{'content':json.dumps(result)}}]}
        cache={'entries':{}};ledger={'entries':{},'ledger':[]}
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as tmp,patch.object(r,'ROOT',Path(tmp)),patch.object(summaries,'complete',return_value=response) as api:
            r.generate([self.paper],cache,self.settings,self.config,ledger,budget,'fake-test-key','2026-10-26')
            r.generate([self.paper],cache,self.settings,self.config,ledger,budget,'fake-test-key','2026-10-27')
            self.assertEqual(api.call_count,1)
            self.assertTrue(r.valid(self.paper,cache['entries'][self.paper['id']],self.settings))
            self.assertEqual(ledger['ledger'][0]['task'],'relevance')
            self.assertEqual(ledger['ledger'][0]['status'],'success')
            self.assertLess(ledger['ledger'][0]['budget_charge_cny'],.001)
    def test_invalid_quote_fails_open_without_repeated_paid_calls(self):
        budget=json.loads((ROOT/'config/summaries.json').read_text(encoding='utf-8'))
        budget['run_budget_group']=self.settings['migration_id']
        result={**self.cache()['entries'][self.paper['id']]['result'],'evidence':'invented quote'}
        response={'usage':{'prompt_tokens':100,'completion_tokens':60},'choices':[{'finish_reason':'stop','message':{'content':json.dumps(result)}}]}
        cache={'entries':{}};ledger={'entries':{},'ledger':[]}
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as tmp,patch.object(r,'ROOT',Path(tmp)),patch.object(summaries,'complete',return_value=response) as api:
            r.generate([self.paper],cache,self.settings,self.config,ledger,budget,'fake-test-key','2026-10-26')
            r.generate([self.paper],cache,self.settings,self.config,ledger,budget,'fake-test-key','2026-10-27')
            self.assertEqual(api.call_count,1)
        self.assertEqual(cache['entries'][self.paper['id']]['result']['decision'],'uncertain')
        self.assertTrue(r.apply_reviews(self.dataset(),cache,self.settings,self.config)['papers'])
    def test_explicit_format_repair_happens_only_once(self):
        budget=json.loads((ROOT/'config/summaries.json').read_text(encoding='utf-8'))
        budget['run_budget_group']=self.settings['migration_id']
        cache=self.cache(decision='uncertain',topics=[])
        cache['entries'][self.paper['id']]['result']['reason']='AI 判定的格式或引文未通过核对，暂按主题证据保留。'
        ledger={'entries':{},'ledger':[]}
        response={'usage':{'prompt_tokens':100,'completion_tokens':60},'choices':[{'finish_reason':'stop','message':{'content':'invalid'}}]}
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as tmp,patch.object(r,'ROOT',Path(tmp)),patch.object(summaries,'complete',return_value=response) as api:
            r.generate([self.paper],cache,self.settings,self.config,ledger,budget,'fake-test-key','2026-10-26',repair_invalid=True)
            r.generate([self.paper],cache,self.settings,self.config,ledger,budget,'fake-test-key','2026-10-27',repair_invalid=True)
            self.assertEqual(api.call_count,1)
        self.assertTrue(cache['entries'][self.paper['id']]['format_repair'])
    def test_versioned_catalog_search_and_details_preserve_source(self):
        d=r.apply_reviews(self.dataset(),self.cache(),self.settings,self.config)
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as tmp:
            folder=Path(tmp);(folder/'data.json').write_bytes(public.encoded(d));(folder/'index.html').write_text('<head></head><body></body>')
            manifest=public.build(d,folder)
            catalog=json.loads((folder/manifest['catalog'].removeprefix('./')).read_text(encoding='utf-8'))
            self.assertNotIn('abstract',catalog['papers'][0])
            search=json.loads((folder/manifest['search'].removeprefix('./')).read_text(encoding='utf-8'))
            self.assertEqual(search[self.paper['id']],self.paper['abstract'])
            details=json.loads((folder/(manifest['details']+public.bucket(self.paper['id'])+'.json').removeprefix('./')).read_text(encoding='utf-8'))
            self.assertEqual(details[self.paper['id']]['abstract'],self.paper['abstract'])
            d['papers'][0]['summary_zh']='更新概览'
            newer=public.build(d,folder)
            self.assertNotEqual(manifest['version'],newer['version'])
            self.assertEqual((folder/'index.html').read_text(encoding='utf-8').count('id="initial-data"'),1)


if __name__=='__main__':unittest.main()
