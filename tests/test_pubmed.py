import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import pubmed
import update_papers as updater


ARTICLE = b'''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>22</PMID><Article>
  <ArticleTitle>Human white matter connectivity measured with MRI</ArticleTitle>
  <ArticleDate DateType="Electronic"><Year>2026</Year><Month>11</Month><Day>06</Day></ArticleDate>
  <Journal><Title>NeuroImage</Title><ISSN>1053-8119</ISSN><JournalIssue><PubDate>
    <Year>2027</Year><Month>Jan</Month><Day>10</Day>
  </PubDate></JournalIssue></Journal>
  <Abstract><AbstractText Label="METHODS">We acquired diffusion MRI in healthy adults.</AbstractText></Abstract>
</Article></MedlineCitation><PubmedData><ArticleIdList>
  <ArticleId IdType="doi">10.1234/neurobrief-test</ArticleId>
</ArticleIdList><History><PubMedPubDate PubStatus="pubmed">
  <Year>2026</Year><Month>11</Month><Day>07</Day>
</PubMedPubDate></History></PubmedData></PubmedArticle></PubmedArticleSet>'''


class PubMedTests(unittest.TestCase):
    def test_new_pubmed_record_reaches_candidates_when_mirror_has_only_old_rows(self):
        config = json.loads((ROOT/'config/topics.json').read_text(encoding='utf-8'))
        response = b'{"esearchresult":{"count":"2","idlist":["11","22"]}}'
        with patch.object(pubmed, 'request', side_effect=[response, ARTICLE]) as api:
            rows, report = pubmed.supplement(config, dt.date(2026, 11, 7), {'11'})
        self.assertEqual(api.call_args.kwargs['id'], '22')
        self.assertEqual(report['known_pmid_count'], 1)
        topic = {'id': 'pubmed-supplement', 'evidence_terms': []}
        output = updater.build_dataset({}, [(topic, rows, report)], config, '2026-11-07',
                                       '2026-11-07T03:00:00+00:00', keep_candidates=True)
        self.assertEqual(output['new_candidate_ids'], ['doi:10.1234/neurobrief-test'])
        paper = output['papers'][0]
        self.assertEqual(paper['published'], '2026-11-06')
        self.assertEqual(paper['indexed'], '2026-11-07')
        self.assertIn('structure-function', paper['topics'])
        self.assertEqual(paper['source_url'], 'https://pubmed.ncbi.nlm.nih.gov/22/')

    def test_europe_pmc_cooldown_leaves_pubmed_available(self):
        (ROOT/'.local').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as temp:
            folder = Path(temp)
            (folder/'config').mkdir()
            (folder/'config/topics.json').write_bytes((ROOT/'config/topics.json').read_bytes())
            (folder/'data').mkdir()
            (folder/'data/source_cooldown.json').write_text('{"retry_after":"2099-01-01T00:00:00Z"}')
            with patch.object(updater, 'ROOT', folder), patch.object(sys, 'argv', ['update_papers.py', '--as-of', '2026-11-07']), \
                 patch.object(updater, 'fetch_topic') as mirror, patch.object(pubmed, 'request', side_effect=[
                     b'{"esearchresult":{"count":"1","idlist":["22"]}}', ARTICLE]):
                updater.main()
            mirror.assert_not_called()
            result = json.loads((folder/'data/candidates.json').read_text(encoding='utf-8'))
            self.assertEqual(len(result['new_candidate_ids']), 1)
