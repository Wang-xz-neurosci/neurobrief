import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("updater", Path(__file__).resolve().parents[1] / "scripts" / "update_papers.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.topic = {"id": "language", "evidence_terms": ["language network"], "query": "brain"}
        self.row = {"id": "123", "source": "MED", "title": "A language network study", "doi": "https://doi.org/10.1/ABC", "firstPublicationDate": "2026-10-01", "abstractText": "<h4>Results</h4><p>Language network in <i>fMRI</i>.</p>"}
        self.today = "2026-10-23"
        self.now = "2026-10-23T02:00:00+00:00"

    def test_html_to_text_and_no_script_content(self):
        self.assertEqual(m.plain("<p>A &amp; B</p><script>bad()</script><p>C</p>"), "A & B C")

    def test_doi_normalization_and_real_metadata(self):
        p = m.normalize(self.row, self.topic, self.today, self.now)
        self.assertEqual(p["id"], "doi:10.1/abc")
        self.assertEqual(p["methods"], ["fMRI"])
        self.assertIn("language network", p["evidence"]["language"])

    def test_future_publication_excluded(self):
        self.row["firstPublicationDate"] = "2026-11-01"
        self.assertIsNone(m.normalize(self.row, self.topic, self.today, self.now))

    def test_missing_abstract_is_not_invented(self):
        self.row.pop("abstractText")
        p = m.normalize(self.row, self.topic, self.today, self.now)
        self.assertEqual(p["abstract"], "")
        self.assertEqual(p["methods"], [])

    def test_same_doi_merges_topics_and_preserves_first_seen(self):
        a = m.normalize(self.row, self.topic, self.today, "2026-10-01T00:00:00Z")
        b = m.normalize(self.row, {**self.topic, "id": "coupling"}, self.today, self.now)
        merged = m.merge_record(a, b)
        self.assertEqual(merged["topics"], ["coupling", "language"])
        self.assertEqual(merged["first_seen"], a["first_seen"])

    def test_later_doi_does_not_duplicate_source_id(self):
        a = m.normalize({**self.row, "doi": ""}, self.topic, self.today, "2026-10-01T00:00:00Z")
        data = m.build_dataset({"papers": [a]}, [(self.topic, [self.row], {})], {"lookback_days":90,"topics":[self.topic]}, self.today, self.now)
        self.assertEqual(len(data["papers"]), 1)
        self.assertEqual(data["papers"][0]["id"], "doi:10.1/abc")
        self.assertEqual(data["papers"][0]["first_seen"], a["first_seen"])

    def test_archive_is_retained_when_not_in_new_query(self):
        a = m.normalize(self.row, self.topic, self.today, self.now)
        data = m.build_dataset({"papers": [a]}, [(self.topic, [], {})], {"lookback_days":90,"topics":[self.topic]}, self.today, self.now)
        self.assertEqual(len(data["papers"]), 1)

    def test_incomplete_pagination_is_an_error(self):
        response = {"hitCount": 500, "resultList": {"result": [self.row]}, "nextCursorMark": "*"}
        with patch.object(m, "request_json", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "Incomplete pagination"):
                m.fetch_topic(self.topic, "2026-08-01", self.today, "2026-10-01")

    def test_preprint_label_from_source(self):
        p = m.normalize({**self.row, "source": "PPR"}, self.topic, self.today, self.now)
        self.assertTrue(p["is_preprint"])

    def test_pure_functional_connectivity_has_no_structure_tag(self):
        topics = json.loads((m.ROOT / "config" / "topics.json").read_text(encoding="utf-8"))["topics"]
        result = m.classify({"title": "Resting-state functional connectivity in the brain", "abstract": "We used fMRI to measure functional networks."}, topics)
        self.assertIn("rest-naturalistic", result["topics"])
        self.assertNotIn("structure-function", result["topics"])

    def test_stroke_aphasia_white_matter_can_have_three_topics(self):
        topics = json.loads((m.ROOT / "config" / "topics.json").read_text(encoding="utf-8"))["topics"]
        result = m.classify({"title": "Brain connectivity mechanisms of aphasia after stroke", "abstract": "White matter tractography of the arcuate fasciculus."}, topics)
        self.assertEqual(set(result["topics"]), {"language", "structure-function", "brain-disorders"})

    def test_movie_and_discourse_are_naturalistic_but_not_structure(self):
        topics = json.loads((m.ROOT / "config" / "topics.json").read_text(encoding="utf-8"))["topics"]
        result = m.classify({"title": "Neural discourse comprehension during movie-watching", "abstract": "Brain responses measured with fMRI."}, topics)
        self.assertEqual(set(result["topics"]), {"language", "rest-naturalistic"})

    def test_clinical_outcomes_alone_are_not_brain_mechanisms(self):
        topics = json.loads((m.ROOT / "config" / "topics.json").read_text(encoding="utf-8"))["topics"]
        result = m.classify({"title": "Depression symptom scales after psychotherapy", "abstract": "Clinical outcomes and patient satisfaction."}, topics)
        self.assertEqual(result["topics"], [])

    def test_taxonomy_change_reclassifies_old_archive_and_keeps_first_seen(self):
        config = json.loads((m.ROOT / "config" / "topics.json").read_text(encoding="utf-8"))
        a = m.normalize({**self.row, "title": "White matter tractography in the brain", "abstractText": "Structural connectivity of cerebral networks."}, {**self.topic, "id": "white-matter"}, self.today, "2026-09-01T00:00:00Z")
        data = m.build_dataset({"papers": [a]}, [], config, self.today, self.now)
        self.assertEqual(data["papers"][0]["topics"], ["structure-function"])
        self.assertEqual(data["papers"][0]["first_seen"], "2026-09-01T00:00:00Z")
        self.assertNotIn("white-matter", data["papers"][0]["evidence"])

    def test_neural_keyword_without_target_context_is_not_a_match(self):
        topics = json.loads((m.ROOT / "config" / "topics.json").read_text(encoding="utf-8"))["topics"]
        result = m.classify({"title": "Naturalistic language processing in a neural network", "abstract": "Natural language processing on text corpora."}, topics)
        self.assertNotIn("language", result["topics"])


if __name__ == "__main__":
    unittest.main()
