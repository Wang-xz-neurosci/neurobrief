"""Persist resumable AI work separately from successful source collection."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

import review_papers as review
import summarize_papers as summaries
import update_papers as updater

ROOT = Path(__file__).resolve().parents[1]
CN = dt.timezone(dt.timedelta(hours=8))


def snapshot(data, candidates, reviews, cache, scope, review_settings, summary_settings, policy, now):
    day = now.astimezone(CN).date().isoformat()
    work, waiting, held = [], 0, 0
    for paper in candidates['papers']:
        if not paper.get('abstract', '').strip() or len(paper['abstract']) > review_settings['max_abstract_chars'] or updater.basic_exclusion(paper):
            continue
        entry = reviews['entries'].get(paper['id'], {})
        if review.valid(paper, entry, review_settings):
            continue
        if entry.get('attempt_date') == day and entry.get('fingerprint') == review.fingerprint(paper, review_settings):
            waiting += 1
        else:
            budget = {**summary_settings, 'max_output_tokens': review_settings['max_output_tokens']}
            budget.pop('backfill', None)
            messages = [{'role': 'system', 'content': review.SYSTEM_PROMPT},
                        {'role': 'user', 'content': review.USER_INSTRUCTION + json.dumps({'title': paper['title'], 'abstract': paper['abstract']}, ensure_ascii=False)}]
            work.append(('review', paper, messages, budget))
    review_count = sum(t[0] == 'review' for t in work) + waiting
    summary_count = 0
    for paper in data['papers']:
        if not paper.get('abstract', '').strip() or len(paper['abstract']) > summary_settings['max_abstract_chars']:
            continue
        entry = cache['entries'].get(paper['id'], {})
        if summaries.valid_entry(paper, entry, summary_settings):
            continue
        current = entry.get('source_hash') == summaries.source_hash(paper)
        if current and entry.get('status') == 'rejected':
            held += 1
            continue
        summary_count += 1
        if current and entry.get('status') == 'error' and entry.get('attempt_date') == day:
            waiting += 1
        else:
            work.append(('summary', paper, summaries.messages_for(paper), summary_settings))
    pending = review_count + summary_count
    retry = None
    reason = 'complete'
    if pending:
        # Decide only after all in-flight reservations have settled. The
        # annual cap applies to every task and every explicit recovery run.
        affordable = any(summaries.within_budget(cache, day, summaries.estimate_reservation(messages, settings), settings,
                                                summaries.budget_group(paper, settings))
                         for _, paper, messages, settings in work)
        if affordable:
            retry = now + dt.timedelta(minutes=30)
            reason = 'pending'
        else:
            tomorrow = now.astimezone(CN).date() + dt.timedelta(days=1)
            retry = dt.datetime.combine(tomorrow, dt.time.fromisoformat(policy['not_before']), CN)
            reason = 'daily_budget_or_provider_cooldown'
    return {'pending_reviews': review_count, 'pending_summaries': summary_count,
            'held_summaries': held, 'pending': pending, 'reason': reason,
            'checked_at': now.isoformat(timespec='seconds'),
            'retry_after': retry.isoformat(timespec='seconds') if retry else None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempted', action='store_true')
    args = parser.parse_args()
    read = lambda p: json.loads((ROOT / p).read_text(encoding='utf-8'))
    data = read('dist/data.json')
    status_path = ROOT / 'dist/update-status.json'
    status = read('dist/update-status.json') if status_path.exists() else {}
    now = dt.datetime.now(dt.timezone.utc)
    ai = snapshot(data, read('data/candidates.json'), read('data/relevance_cache.json'), read('data/summary_cache.json'),
                  read('config/topics.json'), read('config/relevance.json'), read('config/summaries.json'), read('config/update_policy.json'), now)
    # Merely publishing saved files must not postpone an already scheduled retry.
    previous = status.get('ai', {})
    if not args.attempted and previous.get('pending') and ai['pending'] and previous.get('retry_after'):
        ai['retry_after'] = previous['retry_after']
    status.update(schema_version=1, collection_date=data['update_summary']['date'], collected_at=data['updated_at'],
                  relevance_version=data['relevance_status']['version'], ai=ai,
                  content_hash=hashlib.sha256((ROOT / 'dist/data.json').read_bytes()).hexdigest()[:20])
    summaries.atomic_json(status_path, status)
    print(f"AI queue: {ai['pending_reviews']} reviews, {ai['pending_summaries']} overviews; {ai['held_summaries']} held. Next attempt: {ai['retry_after']}")


if __name__ == '__main__':
    main()
