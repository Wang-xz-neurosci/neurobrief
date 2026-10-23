"""Check delivered static assets and data integrity; no external dependencies."""
import json
import gzip
import importlib.util
from pathlib import Path
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
for name in ["index.html", "styles.css", "app.js", "favicon.svg", "brain-mark.svg", "data.json"]:
    assert (root / "dist" / name).is_file(), f"Missing {name}"
data = json.loads((root / "dist" / "data.json").read_text(encoding="utf-8"))
assert gzip.decompress((root / "dist" / "data.json.gz").read_bytes()) == (root / "dist" / "data.json").read_bytes(), "Compressed dataset differs from archive"
assert data["schema_version"] == 1
assert data["update_status"] == "success"
assert data["papers"], "Empty paper dataset"
assert len({p["id"] for p in data["papers"]}) == len(data["papers"]), "Duplicate IDs"
topic_ids = {t["id"] for t in data["topics"]}
config = json.loads((root / "config" / "topics.json").read_text(encoding="utf-8"))
assert topic_ids == {t["id"] for t in config["topics"]}, "Dataset taxonomy is out of date"
spec = importlib.util.spec_from_file_location("updater", root / "scripts" / "update_papers.py")
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)
assert data.get("classification_fingerprint") == updater.classification_fingerprint(config), "Run collection after changing topic rules"
assert data["initial_coverage_start"] == config["coverage_start"]
assert len(data["queries"]) == len(config["topics"]) + 1, "Missing journal safety sweep"
assert data["queries"][-1]["topic"] == "journal-sweep"
assert data["scan_mode"] in ("daily-incremental", "daily-plus-previous-week")
assert "last_full_scan" not in data, "Automatic historical rescan must remain disabled"
for sentinel in config.get("coverage_sentinels", []):
    assert any(p["doi"] == sentinel["doi"] and sentinel["topic"] in p["topics"] for p in data["papers"]), "Known coverage example is missing"
seen_day = lambda p: updater.dt.datetime.fromisoformat(p["first_seen"].replace("Z", "+00:00")).astimezone(updater.dt.timezone(updater.dt.timedelta(hours=8))).date().isoformat()
assert data["update_summary"]["new_papers"] == sum(seen_day(p) == data["update_summary"]["date"] for p in data["papers"])
html = (root / "dist" / "index.html").read_text(encoding="utf-8")
for topic_id in topic_ids:
    assert f'data-view="{topic_id}"' in html, f"Missing topic navigation: {topic_id}"
for filename in ["feed.xml", *["feed-" + t + ".xml" for t in topic_ids]]:
    feed = ET.parse(root / "dist" / filename).getroot()
    assert feed.findtext("channel/title")
    assert len(feed.findall("channel/item")) <= 50
for p in data["papers"]:
    assert p["title"] and p["first_seen"]
    assert set(p["topics"]) <= topic_ids and p["topics"]
    assert not p["published"] or p["published"] <= data["as_of"]
    assert p["published"] and p["published"] >= config["coverage_start"]
    assert p["methods"] and set(p["methods"]) <= {"fMRI", "DTI", "EEG", "MEG", "颅内电生理", "其他"}
    assert p["methods"] == updater.detect_methods(updater.method_text(p)), "Stale method labels"
    assert "其他" not in p["methods"] or p["methods"] == ["其他"]
    if "brain-disorders" in p["topics"]:
        assert updater.clinical_imaging_study(p), "Clinical imaging gate bypassed"
    assert urlparse(p["url"]).scheme == "https"
    assert urlparse(p["source_url"]).netloc == "europepmc.org"
    assert "<script" not in p["abstract"].lower()
    assert p["topics"] == updater.classify(p, config["topics"])["topics"], "Paper classification is out of date"
    if p.get("summary_zh"):
        assert len(p["summary_zh"]) <= 420 and p.get("summary_meta", {}).get("source_hash")
        expected = updater.hashlib.sha256((p["title"] + "\n" + p["abstract"]).encode()).hexdigest()
        assert p["summary_meta"]["source_hash"] == expected, "Summary does not match the current abstract"
assert sum(bool(p.get("summary_zh")) for p in data["papers"]) <= 12, "Pilot exceeded its limit"
for path in [*root.joinpath("dist").glob("*"), *root.joinpath("config").glob("*.json"), *root.joinpath("data").glob("*.json")]:
    if path.is_file() and path.suffix != ".gz":
        assert not updater.re.search(r"sk-[a-zA-Z0-9]{24,}", path.read_text(encoding="utf-8")), "Credential-like text in public files"
print(f"Validated {len(data['papers'])} real literature records, Chinese pilot summaries and static assets.")
for t in data["topics"]:
    print(f"{t['id']}: {sum(t['id'] in p['topics'] for p in data['papers'])}")
