import copy
import datetime as dt
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import processing_status as p
import review_papers as r
import summarize_papers as s


class ProcessingTests(unittest.TestCase):
    def setUp(self):
        read=lambda path:json.loads((ROOT/path).read_text(encoding='utf-8'))
        self.settings=read('config/summaries.json');self.relevance=read('config/relevance.json')
        self.scope=read('config/topics.json');self.policy=read('config/update_policy.json')
        self.now=dt.datetime.fromisoformat('2026-10-28T20:00:00+00:00')
        self.paper={'id':'p','title':'Human white matter and memory',
                    'abstract':'We measured human white matter signals during memory.',
                    'first_seen':'2026-10-28T23:00:00+00:00','published':'2026-10-28'}
        self.data={'papers':[self.paper]};self.reviews={'entries':{}}
        self.cache={'entries':{},'ledger':[]}
    def snapshot(self):
        return p.snapshot(self.data,self.data,self.reviews,self.cache,self.scope,self.relevance,self.settings,self.policy,self.now)
    def test_pending_jobs_have_a_bounded_followup(self):
        result=self.snapshot()
        self.assertEqual(result['pending_reviews'],1);self.assertEqual(result['pending_summaries'],1)
        self.assertEqual(dt.datetime.fromisoformat(result['retry_after']),self.now+dt.timedelta(minutes=30))
    def test_valid_results_are_not_pending_or_paid_again(self):
        self.reviews['entries']['p']={'status':'success','fingerprint':r.fingerprint(self.paper,self.relevance)}
        self.cache['entries']['p']={'status':'success','source_hash':s.source_hash(self.paper),'prompt_version':self.settings['prompt_version']}
        result=self.snapshot();self.assertEqual(result['pending'],0);self.assertIsNone(result['retry_after'])
    def test_no_abstract_is_not_a_paid_retry_task(self):
        self.paper['abstract']=''
        self.assertEqual(self.snapshot()['pending'],0)
    def test_spent_budget_postpones_until_next_beijing_day(self):
        self.cache['ledger']=[{'date':'2026-10-29','budget_charge_cny':self.settings['daily_budget_cny']}]
        result=self.snapshot()
        self.assertEqual(dt.datetime.fromisoformat(result['retry_after']).astimezone(p.CN).strftime('%Y-%m-%d %H:%M'),'2026-10-30 02:50')
    def test_uncertain_network_result_does_not_trigger_immediate_paid_retry(self):
        self.reviews['entries']['p']={'status':'error','attempt_date':'2026-10-29','fingerprint':r.fingerprint(self.paper,self.relevance)}
        self.cache['entries']['p']={'status':'error','attempt_date':'2026-10-29','source_hash':s.source_hash(self.paper)}
        self.assertEqual(self.snapshot()['reason'],'daily_budget_or_provider_cooldown')
    def test_changed_abstract_reopens_work_without_repeating_unchanged_result(self):
        self.test_valid_results_are_not_pending_or_paid_again()
        self.paper['abstract']+=' Updated results.'
        self.assertEqual(self.snapshot()['pending'],2)


if __name__=='__main__':unittest.main()
