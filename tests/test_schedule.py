import datetime as dt
import importlib.util
import json
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('gate',Path(__file__).resolve().parents[1]/'scripts/update_gate.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class ScheduleTests(unittest.TestCase):
    policy=json.loads((Path(__file__).resolve().parents[1]/'config/update_policy.json').read_text(encoding='utf-8'))
    status={'collection_date':'2026-10-26','collected_at':'2026-10-26T04:54:53Z'}
    def now(self,value):return dt.datetime.fromisoformat(value).replace(tzinfo=m.CN)
    def test_today_does_not_collect_again(self):
        self.assertFalse(m.decide('schedule',self.now('2026-10-26T20:00:00'),self.status,self.policy)['collect'])
    def test_early_checks_do_not_call_sources(self):
        result=m.decide('schedule',self.now('2026-10-27T02:49:59'),self.status,self.policy)
        self.assertFalse(result['collect']);self.assertFalse(result['deploy'])
    def test_first_morning_slot_collects(self):
        result=m.decide('schedule',self.now('2026-10-27T02:55:00'),self.status,self.policy)
        self.assertTrue(result['collect']);self.assertTrue(result['deploy'])
    def test_delayed_early_event_uses_actual_beijing_time(self):
        self.assertTrue(m.decide('schedule',dt.datetime.fromisoformat('2026-10-26T19:01:00+00:00'),self.status,self.policy)['collect'])
    def test_successful_collection_is_not_repeated(self):
        status={'collection_date':'2026-10-27','collected_at':'2026-10-26T18:58:00Z'}
        result=m.decide('schedule',self.now('2026-10-27T04:55:00'),status,self.policy,published=status)
        self.assertFalse(result['collect']);self.assertFalse(result['deploy'])
    def test_deployment_failure_retries_without_collection(self):
        status={'collection_date':'2026-10-27','collected_at':'2026-10-26T18:58:00Z'}
        result=m.decide('schedule',self.now('2026-10-27T03:25:00'),status,self.policy,published=self.status)
        self.assertFalse(result['collect']);self.assertTrue(result['deploy'])
    def test_push_and_default_manual_run_only_publish(self):
        for event in ('push','workflow_dispatch'):
            result=m.decide(event,self.now('2026-10-27T09:00:00'),self.status,self.policy)
            self.assertFalse(result['collect']);self.assertTrue(result['deploy'])
    def test_explicit_force_can_collect(self):
        self.assertTrue(m.decide('workflow_dispatch',self.now('2026-10-26T20:00:00'),self.status,self.policy,force=True)['collect'])
    def test_provider_cooldown_is_respected(self):
        result=m.decide('schedule',self.now('2026-10-27T03:00:00'),self.status,self.policy,cooldown={'retry_after':'2026-10-26T20:00:00Z'})
        self.assertFalse(result['collect']);self.assertFalse(result['deploy'])
    def test_pending_ai_resumes_without_recollecting(self):
        status={'collection_date':'2026-10-27','collected_at':'2026-10-26T19:00:00Z',
                'ai':{'pending':42,'retry_after':'2026-10-27T03:30:00+08:00'}}
        result=m.decide('schedule',self.now('2026-10-27T03:35:00'),status,self.policy,published=status)
        self.assertFalse(result['collect']);self.assertTrue(result['process']);self.assertTrue(result['deploy'])
        early=m.decide('schedule',self.now('2026-10-27T03:20:00'),status,self.policy,published=status)
        self.assertFalse(early.get('process',False));self.assertFalse(early['deploy'])
    def test_manual_ai_resume_does_not_fetch_sources(self):
        result=m.decide('workflow_dispatch',self.now('2026-10-27T09:00:00'),self.status,self.policy,resume=True)
        self.assertFalse(result['collect']);self.assertTrue(result['process'])
    def test_saved_summary_change_requires_deployment_despite_same_collection_time(self):
        status={'collection_date':'2026-10-27','collected_at':'2026-10-26T19:00:00Z','content_hash':'new'}
        result=m.decide('schedule',self.now('2026-10-27T04:00:00'),status,self.policy,published={**status,'content_hash':'old'})
        self.assertFalse(result['collect']);self.assertTrue(result['deploy'])


if __name__=='__main__':unittest.main()
