import datetime as dt
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import update_papers as u


def response(rows, total=None, cursor=None):
    value = {'hitCount': len(rows) if total is None else total, 'resultList': {'result': rows}}
    if cursor is not None:
        value['nextCursorMark'] = cursor
    return value


class PaginationTests(unittest.TestCase):
    def setUp(self):
        self.topic = {'id': 'structure-function', 'query': 'brain', 'evidence_terms': ['white matter']}
        self.med = [{'source': 'MED', 'id': str(n)} for n in range(99)]
        self.ppr = [{'source': 'PPR', 'id': str(n)} for n in range(35)]

    def fetch(self):
        return u.fetch_topic(self.topic, '2026-09-01', '2026-11-06', '2026-11-04')

    def provider(self, params):
        query = params['query']
        if 'AND SRC:MED sort_date:y' in query:
            return response(self.med)
        if 'AND SRC:PMC sort_date:y' in query:
            return response([], 2)
        if 'AND SRC:PPR sort_date:y' in query:
            return response(self.ppr)
        return response(self.med+self.ppr, 136)

    def test_small_unavailable_index_entries_are_verified_and_recorded(self):
        with patch.object(u, 'request_json', side_effect=self.provider) as api:
            rows, report = self.fetch()
        self.assertEqual(len(rows), 134)
        self.assertEqual(report['candidate_count'], 136)
        self.assertEqual(report['retrieved_candidate_count'], 134)
        self.assertEqual(report['source_gaps'][0]['unavailable_count'], 2)
        self.assertEqual(report['source_gaps'][0]['change_start'], '2026-11-04')
        self.assertEqual(api.call_count, 5)
        self.assertEqual(sum(c.args[0]['resultType']=='idlist' for c in api.call_args_list), 1)

    def test_missing_records_are_recovered_when_source_queries_return_them(self):
        extra=[{'source':'PMC','id':'PMC'+str(n)} for n in range(2)]
        def provider(params):
            if 'AND SRC:PMC sort_date:y' in params['query']:
                return response(extra)
            return self.provider(params)
        with patch.object(u, 'request_json', side_effect=provider):
            rows, report = self.fetch()
        self.assertEqual(len(rows), 136)
        self.assertEqual(report['source_gaps'], [])

    def test_idlist_disagreement_still_defers_instead_of_publishing_partial_data(self):
        def provider(params):
            if params['resultType']=='idlist':
                return response([{'source':'PMC','id':'unrecovered'}], 2)
            return self.provider(params)
        with patch.object(u, 'request_json', side_effect=provider), patch.object(u,'source_cooldown') as cooldown:
            with self.assertRaises(u.SourceDeferred): self.fetch()
        cooldown.assert_called_once()

    def test_unavailable_source_is_not_limited_by_an_arbitrary_gap_count(self):
        def provider(params):
            value = self.provider(params)
            if not ('AND SRC:MED sort_date:y' in params['query'] or 'AND SRC:PPR sort_date:y' in params['query']):
                value['hitCount'] += 8
            return value
        with patch.object(u,'request_json',side_effect=provider):
            rows,report=self.fetch()
        self.assertEqual(len(rows),134)
        self.assertEqual(report['source_gaps'][0]['unavailable_count'],10)

    def test_no_healthy_nonempty_source_still_defers(self):
        def provider(params):
            scoped=any('AND SRC:'+s+' sort_date:y' in params['query'] for s in ('MED','PMC','PPR'))
            return response([],10 if scoped else 30)
        with patch.object(u,'request_json',side_effect=provider), patch.object(u,'source_cooldown'):
            with self.assertRaises(u.SourceDeferred):self.fetch()

    def test_changed_source_counts_defer_even_when_each_source_is_complete(self):
        def provider(params):
            if 'AND SRC:PMC sort_date:y' in params['query']:
                return response([])
            return self.provider(params)
        with patch.object(u,'request_json',side_effect=provider), patch.object(u,'source_cooldown'):
            with self.assertRaises(u.SourceDeferred): self.fetch()

    def test_duplicate_records_cannot_make_a_page_look_complete(self):
        row=self.med[0]
        with patch.object(u,'request_json',return_value=response([row,row],2)):
            with self.assertRaises(u.IncompletePagination):u.fetch_pages('brain')

    def test_full_page_without_cursor_is_not_accepted_as_missing_metadata(self):
        with patch.object(u,'request_json',return_value=response([{'source':'MED','id':str(n)} for n in range(250)],252)):
            with self.assertRaises(u.IncompletePagination) as caught:u.fetch_pages('brain')
        self.assertFalse(caught.exception.terminal)

    def test_cursor_continues_after_empty_page_with_a_next_cursor(self):
        with patch.object(u,'request_json',side_effect=[response([],1,'next'),response([self.med[0]],1)]),patch.object(u.time,'sleep'):
            rows,total=u.fetch_pages('brain')
        self.assertEqual(len(rows),total)

    def test_gap_recheck_is_recent_and_clears_after_recovery(self):
        config=json.loads((ROOT/'config/topics.json').read_text(encoding='utf-8'))
        old={'updated_at':'2026-11-05T04:00:00Z','source_gaps':[{'change_start':'2026-11-04'}], 'weekly_review_through':'2026-11-01'}
        self.assertEqual(u.collection_plan(dt.date(2026,11,6),old,config)['change_start'],'2026-11-04')
        self.assertEqual(u.collection_plan(dt.date(2026,11,20),old,config)['change_start'],'2026-11-13')
        old.update(updated_at='2026-11-06T04:00:00Z',source_gaps=[])
        self.assertEqual(u.collection_plan(dt.date(2026,11,7),old,config)['change_start'],'2026-11-05')


if __name__ == '__main__':
    unittest.main()
