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
from urllib.error import HTTPError
from email.utils import parsedate_to_datetime

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
    return re.sub(r"\s+", " ", re.sub(r"[-–—‑−]", " ", value.lower())).strip()


def term_present(term, text):
    term = searchable_text(term)
    pattern = re.escape(term.rstrip("*")) + (r"[a-z]*" if term.endswith("*") else "")
    return re.search(r"(?<![a-z0-9])" + pattern + r"(?![a-z0-9])", text) is not None


def journal_query(journals):
    values = sorted({v for j in journals for v in [j["issn"], *j.get("other_issns", [])]})
    return "(" + " OR ".join(f'ISSN:"{v}"' for v in values) + ")"


def topic_query(topic, journals=None):
    """Use the same vocabulary upstream and locally; no hand-maintained second list."""
    if topic.get("query"):
        return topic["query"]
    def clause(group):
        terms = " OR ".join(t if t.endswith("*") and " " not in t else '"' + t + '"' for t in group)
        return f"(TITLE_ABS:({terms}) OR KW:({terms}))"
    query = " AND ".join(clause(group) for group in topic["required_term_groups"])
    if topic.get("monitored_only"):
        if not journals:
            raise ValueError("Restricted topic requires the monitored journal list")
        query += " AND " + journal_query(journals)
    return query


def paper_text(paper):
    # Broad MeSH headings can describe a background concept (e.g. neural nets
    # in an AI paper), so local relevance needs title/abstract/author keywords.
    return searchable_text(" ".join([paper["title"], paper.get("abstract", ""), *paper.get("keywords", [])]))


def is_review_paper(paper):
    types = searchable_text(" ".join(paper.get("publication_types", [])))
    text = searchable_text(paper["title"] + " " + paper.get("abstract", ""))
    return bool(paper.get("is_review") or re.search(r"\breview\b|\bmeta analys", types)
                or re.search(r"\b(?:systematic|scoping|narrative) review\b|\bmeta analys\w*\b|\bthis review\b|\bwe review\b", text))


def method_text(paper):
    abstract = paper.get("abstract", "")
    if is_review_paper(paper):
        return searchable_text(paper["title"] + " " + abstract)
    # When a structured abstract explicitly states Methods, do not take a
    # modality mentioned only in Background as the method used in this study.
    match = re.search(r"(?:^|[.!?]\s+)(?:materials and methods|methods|methodology)\s*:?\s+(.+?)(?=\b(?:results|findings|conclusions?|discussion)\s*:?\s+|$)", abstract, re.I)
    if match:
        return searchable_text(paper["title"] + " " + match.group(1))
    # Keywords can list a technique discussed in a review, or can be copied to
    # an erratum. They are insufficient evidence that the study used it.
    return searchable_text(paper["title"] + " " + abstract)


def basic_exclusion(paper):
    """Only unequivocal exclusions here; semantic ambiguities go to the reviewer."""
    title = searchable_text(paper["title"])
    types = searchable_text(" ".join(paper.get("publication_types", [])))
    if re.search(r"\b(?:protocol|published erratum|retracted publication|retraction of publication)\b", types):
        return "protocol_or_correction"
    if re.match(r"(?:correction|corrigendum|erratum|retraction)\s*:", title):
        return "protocol_or_correction"
    if re.search(r"\b(?:study protocol|trial protocol|review protocol|protocol for (?:a|an|the)|protocol for systematic)\b", title):
        return "protocol_or_correction"
    if re.search(r"\b(?:femoral|femur|hip structure analysis|renal|kidney)\b", title) and not re.search(r"\b(?:brain|cerebral|neural)\b", title):
        return "non_brain_anatomy"
    # Do not infer animal-only from background paragraphs in a human study.
    if re.search(r"\b(?:in mice|in rats|mouse models?|rat models?|murine models?|zebrafish)\b", title) and not re.search(r"\b(?:human|patients?|participants)\b", title):
        return "animal_only"
    return None


def classify(paper, topics):
    """Broad candidate tags, never a claim that the study is relevant or reviewed."""
    text = paper_text(paper)
    # Boilerplate and clinical image reading are not language-task evidence.
    text = re.sub(r"\bplain language summary\b|\benglish language articles\b|\bcase reading time\b", " ", text)
    evidence = {}
    for topic in topics:
        groups = topic.get("required_term_groups", [topic["evidence_terms"]])
        if all(any(term_present(term, text) for term in group) for group in groups):
            evidence[topic["id"]] = [t for t in topic["evidence_terms"] if term_present(t, text)]
    methods = method_text(paper)
    if basic_exclusion(paper):
        evidence = {}
    return {**paper, "is_review": is_review_paper(paper), "topics": list(evidence), "evidence": evidence,
            "methods": detect_methods(methods), "modalities": detect_modalities(methods)}


def mark_journal(paper, config):
    name = paper.get("journal", "").casefold().rstrip(" .")
    matches = [j for j in config.get("monitored_journals", [])
               if set(paper.get("journal_issns", [])) & {j["issn"], *j.get("other_issns", [])}
               or name in {j["name"].casefold(), *[a.casefold().rstrip(" .") for a in j.get("aliases", [])]}]
    return {**paper, "is_monitored_journal": bool(matches) and not paper.get("is_preprint", False), "journal_groups": []}


def allowed_topics(paper, topic_ids, config):
    restricted = {t["id"] for t in config["topics"] if t.get("monitored_only")}
    labels = [t["id"] for t in config["topics"] if t["id"] in topic_ids
              and (t["id"] not in restricted or paper.get("is_monitored_journal", False))]
    text = paper_text(paper)
    # A model can over-tag a functional-network paper as structural. Require
    # actual structural/white-matter vocabulary; white-matter BOLD qualifies.
    structure = next((t for t in config['topics'] if t['id']=='structure-function'),None)
    if 'structure-function' in labels and structure and not any(term_present(t,text) for t in structure['evidence_terms']):
        labels.remove('structure-function')
    return labels


def classification_fingerprint(config):
    rules = {k: config.get(k) for k in ("topics", "coverage_start", "monitored_journals", "classification_version")}
    return hashlib.sha256(json.dumps(rules, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def valid_date(value):
    try:
        return dt.date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        return None


_last_request_started = 0.0


def source_cooldown(seconds, reason):
    path = ROOT / "data/source_cooldown.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    value = {"retry_after": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=seconds)).isoformat(timespec="seconds"), "reason": reason}
    path.write_text(json.dumps(value, separators=(",", ":")) + "\n", encoding="utf-8")


def retry_after_seconds(value):
    try:
        return max(0, float(value))
    except (TypeError, ValueError):
        try:
            return max(0, (parsedate_to_datetime(value) - dt.datetime.now(dt.timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def request_json(params):
    global _last_request_started
    url = API + "?" + urlencode(params)
    for attempt in range(4):
        try:
            wait_seconds = 1.0 - (time.monotonic() - _last_request_started)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            _last_request_started = time.monotonic()
            req = Request(url, headers={"User-Agent": "NeuroBrief/1.1 (+https://github.com/Wang-xz-neurosci/neurobrief; academic literature updates)", "Accept": "application/json"})
            with urlopen(req, timeout=60) as response:
                data = json.load(response)
            if "hitCount" not in data or not isinstance(data.get("resultList", {}).get("result"), list):
                raise ValueError("Unexpected Europe PMC response schema")
            return data
        except HTTPError as exc:
            if exc.code in (401, 403):
                source_cooldown(6 * 3600, f"HTTP {exc.code}; requests paused")
                raise
            if 400 <= exc.code < 500 and exc.code != 429:
                raise
            delay = retry_after_seconds(exc.headers.get("Retry-After")) if exc.headers else None
            if delay is not None and delay > 60:
                source_cooldown(delay, f"HTTP {exc.code}; Retry-After")
                raise
            if attempt == 3:
                raise
            time.sleep(max(2 ** (attempt + 1), delay or 0))
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** (attempt + 1))


def fetch_topic(topic, start, end, index_start, full_scan=False, publication_windows=None, journals=None):
    dates = f"FIRST_PDATE:[{start} TO {end}]"
    if not full_scan:
        windows = publication_windows or [(index_start, end)]
        changed = [f"FIRST_PDATE:[{a} TO {b}]" for a, b in windows]
        changed += [f"FIRST_IDATE:[{index_start} TO {end}]", f"UPDATE_DATE:[{index_start} TO {end}]"]
        dates += " AND (" + " OR ".join(changed) + ")"
    query = f"({topic_query(topic, journals)}) AND {dates} AND (SRC:MED OR SRC:PMC OR SRC:PPR) sort_date:y"
    cursor, rows = "*", []
    total = None
    for page in range(120):
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


def collection_plan(today, old, config):
    """Daily changes + previous calendar week on Monday; no automatic backfill."""
    start = config["coverage_start"]
    stamp = old.get("updated_at")
    last = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(dt.timezone(dt.timedelta(hours=8))).date() if stamp else today
    overlap = config.get("update_policy", {}).get("daily_overlap_days", 1)
    daily_start = max(start, (min(last, today) - dt.timedelta(days=overlap)).isoformat())
    windows = [(daily_start, today.isoformat())]
    monday = today - dt.timedelta(days=today.weekday())
    previous_sunday = (monday - dt.timedelta(days=1)).isoformat()
    reviewed = old.get("weekly_review_through")
    # A missed Monday is recovered on the next successful run after an earlier
    # weekly review. Installing this policy on Friday does not trigger backfill.
    weekly_due = (today.weekday() == 0 or bool(reviewed and reviewed < previous_sunday)) and reviewed != previous_sunday
    if weekly_due and previous_sunday >= start:
        windows.append((max(start, (monday - dt.timedelta(days=7)).isoformat()), previous_sunday))
        reviewed = previous_sunday
    return {"mode": "daily-plus-previous-week" if len(windows) > 1 else "daily-incremental",
            "change_start": daily_start, "publication_windows": windows,
            "weekly_review_through": reviewed, "coverage_start": start}


METHODS = [
    ("fMRI", r"\b(?:fmri|rsfmri)\b|functional (?:magnetic resonance|mri)|blood oxygen(?:ation)? level dependent"),
    ("DTI", r"\b(?:dmri|dti|dwi|hardi|noddi)\b|diffusion (?:tensor|weighted|magnetic|mri|kurtosis|imaging|spectrum)|tractograph|fib(?:er|re) tracking"),
    ("EEG", r"\beeg\b|electroencephalograph|event related potentials?"),
    ("MEG", r"\bmeg\b|magnetoencephalograph"),
    ("颅内电生理", r"\b(?:ecog|ieeg|seeg)\b|intracranial (?:eeg|electro|record)|electrocorticograph|stereo electroencephalograph"),
]


def detect_modalities(text):
    text = searchable_text(text)
    labels = [label for label, pattern in METHODS if re.search(pattern, text)]
    if re.search(r"\b(?:fnirs|nirs)\b|functional near infrared|near infrared spectroscopy", text):
        labels.append("fNIRS")
    return labels


def detect_methods(text):
    labels = [x for x in detect_modalities(text) if x != "fNIRS"]
    return labels or ["其他"]
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
    journal_meta = row.get("journalInfo", {}).get("journal", {})
    matches = [term for term in topic["evidence_terms"] if term in text]
    return {
        "id": key, "doi": doi, "source": source, "source_id": rid,
        "record_aliases": [record_key],
        "title": title, "authors": plain(row.get("authorString")), "journal": journal,
        "journal_issns": list(dict.fromkeys(journal_meta[k] for k in ("issn", "essn") if journal_meta.get(k))),
        "published": published, "publication_year": row.get("pubYear"),
        "indexed": valid_date(row.get("firstIndexDate")), "first_seen": seen,
        "abstract": abstract, "abstract_language": "original", "is_preprint": is_preprint,
        "keywords": [plain(k) for k in row.get("keywordList", {}).get("keyword", [])],
        "mesh_terms": [plain(k.get("descriptorName")) for k in row.get("meshHeadingList", {}).get("meshHeading", [])],
        "publication_types": types,
        "is_review": any("review" in s.lower() or "meta-analysis" in s.lower() for s in types),
        "is_open_access": row.get("isOpenAccess") == "Y",
        "topics": [topic["id"]], "evidence": {topic["id"]: matches},
        "methods": detect_methods(text), "modalities": detect_modalities(text),
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


def build_dataset(old, topic_results, config, today, now, keep_candidates=False):
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
    classified = [mark_journal(p, config) for p in classified]
    for p in classified:
        p["topics"] = allowed_topics(p, p["topics"], config)
        p["evidence"] = {k:v for k,v in p["evidence"].items() if k in p["topics"]}
    start = config.get("coverage_start") or (dt.date.fromisoformat(today) - dt.timedelta(days=config["lookback_days"] - 1)).isoformat()
    items = sorted((p for p in classified if (p["topics"] or (keep_candidates and p["id"] in old.get("audit_ids", []))) and p.get("published") and start <= p["published"] <= today), key=lambda x: (x.get("published") or "", x["id"]), reverse=True)
    local_date = dt.datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
    def seen_day(p):
        return dt.datetime.fromisoformat(p["first_seen"].replace("Z", "+00:00")).astimezone(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
    old_aliases = {a for p in old.get("papers", []) for a in [p["id"], *p.get("record_aliases", [])]}
    new_ids = [p['id'] for p in items if not ({p["id"], *p.get("record_aliases", [])} & old_aliases)]
    new_in_run = len(new_ids)
    return {
        "schema_version": 1, "updated_at": now, "as_of": today,
        "classification_version": config.get("classification_version", "custom"),
        "classification_fingerprint": classification_fingerprint(config),
        "update_mode": "github-actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "manual",
        "initial_coverage_start": start,
        "update_summary": {"date": local_date, "new_papers": sum(seen_day(p) == local_date for p in items), "new_in_run": new_in_run, "latest_publication": max((p["published"] for p in items), default=None)},
        "source": {"name": "Europe PMC", "url": "https://europepmc.org/RestfulWebService", "description": "Europe PMC 收录的 PubMed 记录与预印本；并非所有期刊的完整覆盖。"},
        "monitored_journals": config.get("monitored_journals", []),
        "update_status": "success", "future_or_invalid_excluded": excluded_future,
        "topics": [{k: v for k, v in t.items() if k in ("id", "name", "short_name", "description")} for t in config["topics"]],
        "queries": [report for _, _, report in topic_results], "papers": items, "new_candidate_ids":new_ids,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", default=dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat())
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "candidates.json")
    parser.add_argument("--new-topic-backfill", choices=["cognition"], help="One-time, explicitly requested coverage for the new topic only")
    args = parser.parse_args()
    today = dt.date.fromisoformat(args.as_of)
    config = json.loads((ROOT / "config" / "topics.json").read_text(encoding="utf-8"))
    seed = args.output if args.output.exists() else ROOT / "dist/data.json"
    old = json.loads(seed.read_text(encoding="utf-8")) if seed.exists() else {}
    old.setdefault("audit_ids", [p["id"] for p in old.get("papers", [])])
    backfilled = old.get("backfilled_topics", [])
    if args.new_topic_backfill in backfilled:
        print("Requested new-topic backfill already saved; reusing candidates.")
        return
    start = config["coverage_start"]
    plan = collection_plan(today, old, config)
    index_start = plan["change_start"]
    results = []
    for topic in config["topics"]:
        rows, report = fetch_topic(topic, start, today.isoformat(), index_start,
                                   full_scan=topic["id"] == args.new_topic_backfill,
                                   publication_windows=plan["publication_windows"], journals=config.get("monitored_journals", []))
        print(f"{topic['id']}: {len(rows)} candidates", flush=True)
        results.append((topic, rows, report))
        time.sleep(0.5)
    # Separate journal sweep bypasses topical query wording, then uses the same
    # local relevance rules. It is a safety net, never a journal whitelist.
    journals = config.get("monitored_journals", [])
    if journals:
        sweep = {"id": "journal-sweep", "evidence_terms": [], "query": journal_query(journals)}
        rows, report = fetch_topic(sweep, start, today.isoformat(), index_start, publication_windows=plan["publication_windows"])
        report["journals"] = [j["name"] for j in journals]
        results.append((sweep, rows, report))
        print(f"journal-sweep: {len(rows)} candidates", flush=True)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    dataset = build_dataset(old, results, config, today.isoformat(), now, keep_candidates=True)
    dataset["audit_ids"] = old["audit_ids"]
    dataset["backfilled_topics"] = list(dict.fromkeys(backfilled + ([args.new_topic_backfill] if args.new_topic_backfill else [])))
    dataset["scan_mode"] = plan["mode"]
    dataset["collection_plan"] = plan
    dataset["weekly_review_through"] = plan["weekly_review_through"]
    for report in dataset["queries"]:
        if report["topic"] in {t["id"] for t in config["topics"]}:
            report["retained_topic_count"] = sum(report["topic"] in p["topics"] for p in dataset["papers"])
    # Known omissions are release guards, not hard-coded extra papers.
    ids = {p["doi"]: p for p in dataset["papers"]}
    for sentinel in config.get("coverage_sentinels", []):
        if sentinel["doi"] not in ids or sentinel["topic"] not in ids[sentinel["doi"]]["topics"]:
            raise RuntimeError("Coverage regression: missing " + sentinel["doi"])
    if not dataset["papers"]:
        raise RuntimeError("No records returned; refusing to replace the last successful dataset")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(".json.tmp")
    temp.write_text(json.dumps(dataset, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(temp, args.output)
    (ROOT / "data/source_cooldown.json").write_text('{"retry_after":null}\n', encoding="utf-8")
    print(f"Saved {len(dataset['papers'])} unique papers to {args.output}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Update failed; previous data retained: {exc}", file=sys.stderr)
        sys.exit(1)
