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
        self.assertEqual(p["methods"], ["其他"])

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
        result = m.classify({"title": "Brain connectivity mechanisms of aphasia after stroke", "abstract": "We studied patients with stroke using white matter tractography of the arcuate fasciculus."}, topics)
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

    def classify(self, title, abstract, **extra):
        config = json.loads((m.ROOT / "config" / "topics.json").read_text(encoding="utf-8"))
        return m.classify({"title": title, "abstract": abstract, **extra}, config["topics"])

    def test_reported_language_lateralization_omission(self):
        result = self.classify("The dynamics of functional connectivity-based language lateralization across timescales.", "In most individuals, language is predominantly left-lateralized, a prominent feature of human brain organization. We review evidence of functional connectivity within the language system.")
        self.assertIn("language", result["topics"])

    def test_human_language_and_large_language_model_paper_not_blanket_excluded(self):
        result = self.classify("Language representations in the human cortex and large language models", "Natural language processing models were compared with fMRI responses of participants during speech comprehension.")
        self.assertIn("language", result["topics"])

    def test_t1_morphometry_is_other_not_dti_and_not_clinical_imaging_scope(self):
        result = self.classify("Cortical thickness in depression", "T1-weighted structural MRI in patients with depression showed brain morphometric differences.")
        self.assertEqual(result["methods"], ["其他"])
        self.assertNotIn("brain-disorders", result["topics"])

    def test_diffusion_and_tractography_share_dti_method(self):
        self.assertEqual(m.detect_methods("DWI diffusion-weighted imaging and fiber tracking tractography"), ["DTI"])

    def test_clinical_fnirs_is_eligible_but_displayed_as_other(self):
        result = self.classify("Cognitive function in ADHD", "We assessed children with ADHD with functional near-infrared spectroscopy (fNIRS) during an executive task.")
        self.assertIn("brain-disorders", result["topics"])
        self.assertEqual(result["methods"], ["其他"])
        self.assertIn("fNIRS", result["modalities"])

    def test_animal_eeg_and_review_are_not_clinical_population_studies(self):
        animal = self.classify("EEG networks in an epilepsy mouse model", "Mice were recorded to test neural oscillations and brain connectivity.")
        review = self.classify("fMRI of patients with depression", "Brain connectivity and cognition in patients with depression.", is_review=True)
        self.assertNotIn("brain-disorders", animal["topics"])
        self.assertNotIn("brain-disorders", review["topics"])

    def test_clinical_fmri_patient_study_is_eligible(self):
        result = self.classify("Functional connectivity and memory in Alzheimer disease", "We recruited 40 patients with Alzheimer disease and healthy controls for fMRI to investigate brain connectivity and cognitive performance.")
        self.assertIn("brain-disorders", result["topics"])

    def test_coverage_start_is_hard_lower_bound(self):
        config = {"coverage_start": "2026-09-01", "topics": [self.topic]}
        rows = [{**self.row, "id": str(i), "doi": f"10.1/{i}", "firstPublicationDate": date} for i, date in enumerate(["2026-08-31", "2026-09-01"])]
        data = m.build_dataset({}, [(self.topic, rows, {})], config, self.today, self.now)
        self.assertEqual([p["published"] for p in data["papers"]], ["2026-09-01"])

    def test_same_day_rerun_keeps_daily_new_count_and_next_day_resets(self):
        config = {"coverage_start": "2026-09-01", "topics": [self.topic]}
        first = m.build_dataset({}, [(self.topic, [self.row], {})], config, self.today, self.now)
        rerun = m.build_dataset(first, [(self.topic, [self.row], {})], config, self.today, "2026-10-23T10:00:00Z")
        tomorrow = m.build_dataset(rerun, [], config, "2026-10-24", "2026-10-24T02:00:00Z")
        self.assertEqual(first["update_summary"]["new_papers"], 1)
        self.assertEqual(rerun["update_summary"]["new_papers"], 1)
        self.assertEqual(rerun["update_summary"]["new_in_run"], 0)
        self.assertEqual(tomorrow["update_summary"]["new_papers"], 0)

    def test_incremental_query_includes_metadata_updates_and_date_floor(self):
        response = {"hitCount": 0, "resultList": {"result": []}}
        with patch.object(m, "request_json", return_value=response):
            _, report = m.fetch_topic(self.topic, "2026-09-01", self.today, "2026-10-16", full_scan=False)
        self.assertIn("UPDATE_DATE:[2026-10-16 TO 2026-10-23]", report["query"])
        self.assertIn("FIRST_PDATE:[2026-09-01 TO 2026-10-23] AND", report["query"])

    def test_ai_text_models_and_kidney_cortex_are_outside_scope(self):
        ai = self.classify("Self-supervised molecular graph encoders", "Language representations and neural networks for molecular prediction.", mesh_terms=["Brain", "Language"])
        kidney = self.classify("Kidney cortical thickness", "We measured kidney cortex, cortical thickness and structural constraints on kidney morphology.")
        self.assertNotIn("language", ai["topics"])
        self.assertNotIn("structure-function", kidney["topics"])

    def test_incidental_speech_in_breathing_study_is_not_language_focus(self):
        result = self.classify("Threat-driven respiration and its homeostatic recovery", "Brain threat signals from the amygdala control breathing. Speech sets breathing rhythms during a stress task.")
        self.assertNotIn("language", result["topics"])

    def test_narrative_review_is_not_a_natural_stimulus(self):
        result = self.classify("A narrative review of brain injury", "Clinical brain mechanisms and a narrative synthesis of stroke studies.")
        self.assertNotIn("rest-naturalistic", result["topics"])

    def test_structured_t1_methods_do_not_inherit_background_diffusion(self):
        result = self.classify("Cortical thickness in patients with depression", "Background: Diffusion tensor imaging and fMRI measure brain connectivity. Methods: We compared T1-weighted structural MRI cortical thickness in patients with depression. Results: Patients showed lower cortical thickness.")
        self.assertEqual(result["methods"], ["其他"])
        self.assertNotIn("brain-disorders", result["topics"])


if __name__ == "__main__":
    unittest.main()
