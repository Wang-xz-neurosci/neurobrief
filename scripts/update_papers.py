"""Fetch actual Europe PMC records. Standard library only; no AI or API key.

Fail closed: keep the previous dataset if any topic fails or pagination truncates.
Publication and indexing dates remain distinct; never fabricate missing metadata.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from html.parser import HTMLParser
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag in ("p", "br", "h4", "div", "title"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        self.parts.append(" ")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def plain(value):
    parser = PlainText()
    parser.feed(value or "")
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip()


def normalize_doi(doi):
    return re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", (doi or "").strip(), flags=re.I).lower()


def searchable_text(value):
    return re.sub(r"\s+", " ", value.lower().replace("–", "-").replace("—", "-").replace("‑", "-")).strip()


def term_present(term, text):
    # Left boundary avoids e.g. stroke matching heatstroke; prefixes are intentional.
    return re.search(r"(?<![a-z0-9])" + re.escape(term.lower()), text) is not None


def classify(paper, topics):
    text = searchable_text(f"{paper['title']} {paper.get('abstract', '')}")
    evidence = {}
    for topic in topics:
        groups = topic.get("required_term_groups", [topic["evidence_terms"]])
        if any(term_present(term, text) for term in topic.get("exclude_terms", [])):
            continue
        if all(any(term_present(term, text) for term in group) for group in groups):
            evidence[topic["id"]] = [term for term in topic["evidence_terms"] if term_present(term, text)]
    return {**paper, "topics": list(evidence), "evidence": evidence}


def classification_fingerprint(config):
    return hashlib.sha256(json.dumps(config["topics"], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def valid_date(value):
    try:
        return dt.date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        return None


def request_json(params):
    url = API + "?" + urlencode(params)
    for attempt in range(4):
        try:
            req = Request(url, headers={"User-Agent": "NeuroBrief/1.0 (academic literature tracker)", "Accept": "application/json"})
            with urlopen(req, timeout=60) as response:
                data = json.load(response)
            if "hitCount" not in data or not isinstance(data.get("resultList", {}).get("result"), list):
                raise ValueError("Unexpected Europe PMC response schema")
            return data
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** (attempt + 1))


def fetch_topic(topic, start, end, index_start):
    # Incremental overlap finds delayed indexing, while the publication window
    # backfills new and amended records. Previously stored records are retained.
    dates = f"(FIRST_PDATE:[{start} TO {end}] OR FIRST_IDATE:[{index_start} TO {end}])"
    query = f"({topic['query']}) AND {dates} AND (SRC:MED OR SRC:PPR) sort_date:y"
    cursor, rows = "*", []
    total = None
    for page in range(40):
        data = request_json({"query": query, "format": "json", "resultType": "core", "pageSize": 250, "cursorMark": cursor})
        batch = data["resultList"]["result"]
        total = int(data["hitCount"])
        rows.extend(batch)
        next_cursor = data.get("nextCursorMark")
        if len(rows) >= total:
            break
        if not batch or not next_cursor or next_cursor == cursor:
            raise RuntimeError(f"Incomplete pagination for {topic['id']}: {len(rows)}/{total}")
        cursor = next_cursor
        time.sleep(0.4)
    else:
        raise RuntimeError(f"Pagination limit exceeded for {topic['id']}; old data preserved")
    return rows, {"topic": topic["id"], "query": query, "candidate_count": total, "request_url": API + "?" + urlencode({"query": query, "format": "json", "resultType": "core"})}


METHODS = [
    ("fMRI", r"\bfmri\b|functional magnetic resonance"),
    ("dMRI / DTI", r"\bdmri\b|\bdti\b|diffusion (tensor|magnetic|mri)|diffusion-weighted"),
    ("EEG", r"\beeg\b|electroencephalograph"),
    ("MEG", r"\bmeg\b|magnetoencephalograph"),
    ("颅内电生理", r"\becog\b|\bieeg\b|intracranial|electrocorticograph"),
    ("纤维追踪", r"tractography|fiber tracking|fibre tracking"),
    ("脑刺激", r"\btms\b|\btdcs\b|transcranial"),
]
TRACTS = [
    ("弓状束 AF", "arcuate fasciculus"),
    ("上纵束 SLF", "superior longitudinal fasciculus"),
    ("额枕下束 IFOF", "inferior fronto-occipital fasciculus"),
    ("下纵束 ILF", "inferior longitudinal fasciculus"),
    ("钩束 UF", "uncinate fasciculus"),
    ("额斜束 FAT", "frontal aslant tract"),
]


def normalize(row, topic, today, seen):
    title = plain(row.get("title"))
    if not title:
        return None
    published = valid_date(row.get("firstPublicationDate"))
    # Some source records have only a future issue date. Do not label them new.
    if published and published > today:
        return None
    abstract = plain(row.get("abstractText"))
    text = searchable_text(f"{title} {abstract}")
    doi = normalize_doi(row.get("doi"))
    source, rid = row.get("source", "MED"), row.get("id", "")
    record_key = f"{source}:{rid}" if rid else "title:" + hashlib.sha256(title.lower().encode()).hexdigest()[:16]
    key = "doi:" + doi if doi else record_key
    types = row.get("pubTypeList", {}).get("pubType", [])
    is_preprint = source == "PPR" or any("preprint" in s.lower() for s in types)
    journal = row.get("journalInfo", {}).get("journal", {}).get("title") or row.get("bookOrReportDetails", {}).get("publisher") or "来源未提供刊名"
    matches = [term for term in topic["evidence_terms"] if term in text]
    return {
        "id": key, "doi": doi, "source": source, "source_id": rid,
        "record_aliases": [record_key],
        "title": title, "authors": plain(row.get("authorString")), "journal": journal,
        "published": published, "publication_year": row.get("pubYear"),
        "indexed": valid_date(row.get("firstIndexDate")), "first_seen": seen,
        "abstract": abstract, "abstract_language": "original", "is_preprint": is_preprint,
        "is_review": any("review" in s.lower() for s in types),
        "is_open_access": row.get("isOpenAccess") == "Y",
        "topics": [topic["id"]], "evidence": {topic["id"]: matches},
        "methods": [label for label, pattern in METHODS if re.search(pattern, text, re.I)],
        "tracts": [label for label, term in TRACTS if term in text],
        "source_url": f"https://europepmc.org/article/{quote(source)}/{quote(rid)}",
        "url": "https://doi.org/" + doi if doi else f"https://europepmc.org/article/{quote(source)}/{quote(rid)}",
    }


def merge_record(old, new):
    preferred = new if old.get("is_preprint", True) or not new.get("is_preprint") else old
    merged = {**old, **preferred}
    merged["topics"] = sorted(set(old.get("topics", [])) | set(new.get("topics", [])))
    merged["evidence"] = {**old.get("evidence", {}), **new.get("evidence", {})}
    merged["record_aliases"] = sorted(set(old.get("record_aliases", [])) | set(new.get("record_aliases", [])))
    merged["first_seen"] = min(old.get("first_seen") or new["first_seen"], new["first_seen"])
    if not merged.get("abstract"):
        merged["abstract"] = old.get("abstract") or new.get("abstract", "")
    return merged


def build_dataset(old, topic_results, config, today, now):
    papers = {p["id"]: p for p in old.get("papers", [])}
    aliases = {alias: p["id"] for p in papers.values() for alias in p.get("record_aliases", [])}
    excluded_future = 0
    for topic, rows, report in topic_results:
        for row in rows:
            p = normalize(row, topic, today, now)
            if p is None:
                excluded_future += 1
                continue
            key = p["id"]
            # Migrate identifier if an existing PMID record later gains a DOI.
            for alias in p["record_aliases"]:
                previous = aliases.get(alias)
                if previous and previous in papers and previous != key:
                    if papers[previous].get("doi") and not p.get("doi"):
                        key = previous
                        p["id"], p["doi"] = previous, papers[previous]["doi"]
                    else:
                        migrated = papers.pop(previous)
                        papers[key] = merge_record(migrated, p)
            papers[key] = merge_record(papers[key], p) if key in papers else p
            for alias in papers[key]["record_aliases"]:
                aliases[alias] = key
    # Reclassify the entire archive, not only newly retrieved rows. Retired tags
    # must never survive a taxonomy change, and old first_seen dates stay intact.
    classified = [classify(p, config["topics"]) for p in papers.values()]
    items = sorted((p for p in classified if p["topics"] and (not p.get("published") or p["published"] <= today)), key=lambda x: (x.get("published") or "", x["id"]), reverse=True)
    return {
        "schema_version": 1, "updated_at": now, "as_of": today,
        "classification_version": config.get("classification_version", "custom"),
        "classification_fingerprint": classification_fingerprint(config),
        "update_mode": "github-actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "manual",
        "initial_coverage_start": old.get("initial_coverage_start") or (dt.date.fromisoformat(today) - dt.timedelta(days=config["lookback_days"] - 1)).isoformat(),
        "source": {"name": "Europe PMC", "url": "https://europepmc.org/RestfulWebService", "description": "Europe PMC 收录的 PubMed 记录与预印本；并非所有期刊的完整覆盖。"},
        "update_status": "success", "future_or_invalid_excluded": excluded_future,
        "topics": [{k: v for k, v in t.items() if k not in ("query", "required_term_groups", "exclude_terms")} for t in config["topics"]],
        "queries": [report for _, _, report in topic_results], "papers": items,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", default=dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat())
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "data.json")
    args = parser.parse_args()
    today = dt.date.fromisoformat(args.as_of)
    config = json.loads((ROOT / "config" / "topics.json").read_text(encoding="utf-8"))
    old = json.loads(args.output.read_text(encoding="utf-8")) if args.output.exists() else {}
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    start = (today - dt.timedelta(days=config["lookback_days"] - 1)).isoformat()
    same_rules = old.get("classification_fingerprint") == classification_fingerprint(config)
    last_success = valid_date((old.get("updated_at") or "")[:10]) if same_rules else None
    index_start = (dt.date.fromisoformat(last_success) - dt.timedelta(days=7)).isoformat() if last_success else start
    results = []
    for topic in config["topics"]:
        rows, report = fetch_topic(topic, start, today.isoformat(), index_start)
        print(f"{topic['id']}: {len(rows)} candidates", flush=True)
        results.append((topic, rows, report))
        time.sleep(0.5)
    dataset = build_dataset(old, results, config, today.isoformat(), now)
    if not dataset["papers"]:
        raise RuntimeError("No records returned; refusing to replace the last successful dataset")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(".json.tmp")
    temp.write_text(json.dumps(dataset, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(temp, args.output)
    print(f"Saved {len(dataset['papers'])} unique papers to {args.output}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Update failed; previous data retained: {exc}", file=sys.stderr)
        sys.exit(1)
