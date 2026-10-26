"""Apply saved classification/display rules without retrieving older literature."""
import json
from pathlib import Path
import review_papers as review
import summarize_papers as summaries

ROOT = Path(__file__).resolve().parents[1]


def refresh(data, config):
    settings = json.loads((ROOT/'config/relevance.json').read_text(encoding='utf-8'))
    path = ROOT/'data/relevance_cache.json'
    cache = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'entries':{}}
    return review.apply_reviews(data,cache,settings,config)


def main():
    path = ROOT / "dist/data.json"
    source = ROOT/'data/candidates.json'
    data = refresh(json.loads((source if source.exists() else path).read_text(encoding="utf-8")), json.loads((ROOT / "config/topics.json").read_text(encoding="utf-8")))
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    status = {"schema_version": 1, "collection_date": data["update_summary"]["date"], "collected_at": data["updated_at"], "relevance_version":data['relevance_status']['version']}
    (ROOT / "dist/update-status.json").write_text(json.dumps(status, separators=(",", ":")) + "\n", encoding="utf-8")
    print("Refreshed saved metadata; collection date and first-seen dates preserved. No source requests.")


if __name__ == "__main__":
    main()
