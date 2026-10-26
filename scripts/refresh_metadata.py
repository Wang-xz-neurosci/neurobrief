"""Apply saved classification/display rules without retrieving older literature."""
import json
from pathlib import Path
import update_papers as updater

ROOT = Path(__file__).resolve().parents[1]


def refresh(data, config):
    rebuilt = updater.build_dataset(data, [], config, data["as_of"], data["updated_at"])
    for key in ("papers", "topics", "monitored_journals", "classification_version", "classification_fingerprint"):
        data[key] = rebuilt[key]
    for report in data["queries"]:
        if report["topic"] in {t["id"] for t in config["topics"]}:
            report["retained_topic_count"] = sum(report["topic"] in p["topics"] for p in data["papers"])
    return data


def main():
    path = ROOT / "dist/data.json"
    data = refresh(json.loads(path.read_text(encoding="utf-8")), json.loads((ROOT / "config/topics.json").read_text(encoding="utf-8")))
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    status = {"schema_version": 1, "collection_date": data["update_summary"]["date"], "collected_at": data["updated_at"]}
    (ROOT / "dist/update-status.json").write_text(json.dumps(status, separators=(",", ":")) + "\n", encoding="utf-8")
    print("Refreshed saved metadata; collection date and first-seen dates preserved. No source requests.")


if __name__ == "__main__":
    main()
