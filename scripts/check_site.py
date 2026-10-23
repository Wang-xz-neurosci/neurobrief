"""Check delivered static assets and data integrity; no external dependencies."""
import json
import gzip
import importlib.util
from pathlib import Path
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
for name in ["index.html", "styles.css", "app.js", "favicon.svg", "data.json"]:
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
    assert urlparse(p["url"]).scheme == "https"
    assert urlparse(p["source_url"]).netloc == "europepmc.org"
    assert "<script" not in p["abstract"].lower()
    assert p["topics"] == updater.classify(p, config["topics"])["topics"], "Paper classification is out of date"
print(f"Validated {len(data['papers'])} real literature records and 5 static assets.")
for t in data["topics"]:
    print(f"{t['id']}: {sum(t['id'] in p['topics'] for p in data['papers'])}")
