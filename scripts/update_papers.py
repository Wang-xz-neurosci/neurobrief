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
    return re.sub(r"\s+", " ", re.sub(r"[-–—‑−]", " ", value.lower())).strip()


def term_present(term, text):
    term = searchable_text(term)
    pattern = re.escape(term.rstrip("*")) + (r"[a-z]*" if term.endswith("*") else "")
    return re.search(r"(?<![a-z0-9])" + pattern + r"(?![a-z0-9])", text) is not None


def topic_query(topic):
    """Use the same vocabulary upstream and locally; no hand-maintained second list."""
    if topic.get("query"):
        return topic["query"]
    def clause(term):
        value = term if term.endswith("*") and " " not in term else '"' + term + '"'
        return f"(TITLE_ABS:{value} OR KW:{value})"
    return " AND ".join("(" + " OR ".join(clause(t) for t in group) + ")" for group in topic["required_term_groups"])


def paper_text(paper):
    # Broad MeSH headings can describe a background concept (e.g. neural nets
    # in an AI paper), so local relevance needs title/abstract/author keywords.
    return searchable_text(" ".join([paper["title"], paper.get("abstract", ""), *paper.get("keywords", [])]))


def method_text(paper):
    abstract = paper.get("abstract", "")
    # When a structured abstract explicitly states Methods, do not take a
    # modality mentioned only in Background as the method used in this study.
    match = re.search(r"(?:^|[.!?]\s+)(?:materials and methods|methods|methodology)\s*:?\s+(.+?)(?=\b(?:results|findings|conclusions?|discussion)\s*:?\s+|$)", abstract, re.I)
    if match:
        return searchable_text(paper["title"] + " " + match.group(1))
    return paper_text(paper)


def clinical_imaging_study(paper):
    """Conservative evidence gate, not a claim of full-text or human review."""
    text = searchable_text(f"{paper['title']} {paper.get('abstract', '')}")
    if paper.get("is_review") or re.search(r"\b(meta analys\w*|systematic review|scoping review|study protocol)\b", text):
        return False
    if not any(x in detect_modalities(method_text(paper)) for x in ("fMRI", "DTI", "EEG", "MEG", "颅内电生理", "fNIRS")):
        return False
    clinical = r"\b(patients?|survivors?|clinical (?:cohort|sample|group)|(?:individuals|participants|children|adults|adolescents|people|subjects|boys|girls) (?:diagnosed |living )?with|(?:asd|mdd|adhd|sz|ad|pd) (?:group|patients|participants))\b"
    if not re.search(clinical, text):
        return False
    animal = re.search(r"\b(mice|rats|rodents?|murine|mouse model|rat model|zebrafish)\b", text)
    human = re.search(r"\b(patients?|survivors?|participants|children|adults|adolescents|people|men|women)\b", text)
    return not animal or bool(human) or "Humans" in paper.get("mesh_terms", [])


def classify(paper, topics):
    text = paper_text(paper)
    evidence = {}
    for topic in topics:
        groups = topic.get("required_term_groups", [topic["evidence_terms"]])
        if any(term_present(term, text) for term in topic.get("exclude_terms", [])):
            continue
        if topic.get("clinical_imaging_only") and not clinical_imaging_study(paper):
            continue
        if topic["id"] == "structure-function" and re.search(r"\b(kidney|renal|adrenal)\b", text) and not re.search(r"\b(brain|cerebral|neural|neuro\w*|hippocamp\w*)\b", text):
            continue  # Renal cortex is not cerebral cortex.
        if topic.get("require_language_focus"):
            terms = topic["evidence_terms"]
            title_hit = any(term_present(t, searchable_text(paper["title"])) for t in terms)
            keyword_hit = any(term_present(t, searchable_text(" ".join(paper.get("keywords", [])))) for t in terms)
            focus_terms = r"\b(?:language|speech|semantic\w*|syntac\w*|syntax|aphasi\w*|reading|dyslexi\w*|lexical\w*|phonolog\w*|linguistic\w*|bilingual\w*|multilingual\w*)\b"
            mentions = len(re.findall(focus_terms, searchable_text(paper.get("abstract", ""))))
            if not (title_hit or keyword_hit or mentions >= 2 or detect_modalities(method_text(paper))):
                continue
        # Human brain + LLM comparison papers are valid language neuroscience.
        if topic["id"] == "language" and "natural language processing" in text and not re.search(r"\b(fmri|eeg|meg|fnirs|brain|cortex|cortical|patients?|participants|intracranial)\b", text):
            continue
        if all(any(term_present(term, text) for term in group) for group in groups):
            evidence[topic["id"]] = [term for term in topic["evidence_terms"] if term_present(term, text)]
    methods_text = method_text(paper)
    return {**paper, "topics": list(evidence), "evidence": evidence, "methods": detect_methods(methods_text), "modalities": detect_modalities(methods_text)}


def classification_fingerprint(config):
    rules = {k: config.get(k) for k in ("topics", "coverage_start", "monitored_journals", "classification_version")}
    return hashlib.sha256(json.dumps(rules, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


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


def fetch_topic(topic, start, end, index_start, full_scan=True):
    dates = f"FIRST_PDATE:[{start} TO {end}]"
    if not full_scan:
        dates += f" AND (FIRST_PDATE:[{index_start} TO {end}] OR FIRST_IDATE:[{index_start} TO {end}] OR UPDATE_DATE:[{index_start} TO {end}])"
    query = f"({topic_query(topic)}) AND {dates} AND (SRC:MED OR SRC:PPR) sort_date:y"
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
        "is_review": any("review" in s.lower() for s in types),
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
    journal_issns = {j["issn"] for j in config.get("monitored_journals", [])}
    journal_names = {j["name"].lower() for j in config.get("monitored_journals", [])}
    for p in classified:
        p["is_monitored_journal"] = bool(set(p.get("journal_issns", [])) & journal_issns) or p["journal"].lower() in journal_names
    start = config.get("coverage_start") or (dt.date.fromisoformat(today) - dt.timedelta(days=config["lookback_days"] - 1)).isoformat()
    items = sorted((p for p in classified if p["topics"] and p.get("published") and start <= p["published"] <= today), key=lambda x: (x.get("published") or "", x["id"]), reverse=True)
    local_date = dt.datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
    def seen_day(p):
        return dt.datetime.fromisoformat(p["first_seen"].replace("Z", "+00:00")).astimezone(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
    old_aliases = {a for p in old.get("papers", []) for a in [p["id"], *p.get("record_aliases", [])]}
    new_in_run = sum(not ({p["id"], *p.get("record_aliases", [])} & old_aliases) for p in items)
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
    start = config["coverage_start"]
    same_rules = old.get("classification_fingerprint") == classification_fingerprint(config)
    last_success = valid_date((old.get("updated_at") or "")[:10]) if same_rules else None
    index_start = max(start, (dt.date.fromisoformat(last_success) - dt.timedelta(days=7)).isoformat()) if last_success else start
    last_full = valid_date(old.get("last_full_scan")) if same_rules else None
    full_scan = not last_full or (today - dt.date.fromisoformat(last_full)).days >= config.get("full_scan_every_days", 7)
    results = []
    for topic in config["topics"]:
        rows, report = fetch_topic(topic, start, today.isoformat(), index_start, full_scan)
        print(f"{topic['id']}: {len(rows)} candidates", flush=True)
        results.append((topic, rows, report))
        time.sleep(0.5)
    # Separate journal sweep bypasses topical query wording, then uses the same
    # local relevance rules. It is a safety net, never a journal whitelist.
    journals = config.get("monitored_journals", [])
    if journals:
        sweep = {"id": "journal-sweep", "evidence_terms": [], "query": "(" + " OR ".join(f'ISSN:"{j["issn"]}"' for j in journals) + ")"}
        rows, report = fetch_topic(sweep, start, today.isoformat(), index_start, full_scan)
        if full_scan and not rows:
            raise RuntimeError("Journal sweep unexpectedly empty; check source query fields")
        report["journals"] = [j["name"] for j in journals]
        results.append((sweep, rows, report))
        print(f"journal-sweep: {len(rows)} candidates", flush=True)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    dataset = build_dataset(old, results, config, today.isoformat(), now)
    dataset["last_full_scan"] = today.isoformat() if full_scan else last_full
    dataset["scan_mode"] = "full" if full_scan else "incremental-with-overlap"
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
    print(f"Saved {len(dataset['papers'])} unique papers to {args.output}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Update failed; previous data retained: {exc}", file=sys.stderr)
        sys.exit(1)
