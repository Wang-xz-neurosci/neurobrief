"""Lightweight schedule checks; at most one successful collection per Beijing day."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CN = dt.timezone(dt.timedelta(hours=8))


def decide(event, now, status, policy, published=None, force=False, cooldown=None):
    local = now.astimezone(CN)
    today = local.date().isoformat()
    if event != "schedule":
        return {"collect": force, "deploy": True, "reason": "Explicit collection" if force else "Publish saved data only"}
    if today < policy["effective_from"] or local.strftime("%H:%M") < policy["not_before"]:
        return {"collect": False, "deploy": False, "reason": "Before the daily collection window"}
    until = (cooldown or {}).get("retry_after")
    if until and now < dt.datetime.fromisoformat(until.replace("Z", "+00:00")):
        return {"collect": False, "deploy": False, "reason": "Respecting source cooldown"}
    if status.get("collection_date", "") < today:
        return {"collect": True, "deploy": True, "reason": "First available daily collection"}
    if not published or published.get("collected_at") != status.get("collected_at"):
        return {"collect": False, "deploy": True, "reason": "Collection already saved; retry deployment only"}
    return {"collect": False, "deploy": False, "reason": "Today's collection is already published"}


def read(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", default=os.environ.get("NEUROBRIEF_EVENT", "workflow_dispatch"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    policy = read(ROOT / "config/update_policy.json")
    status = read(ROOT / "dist/update-status.json")
    cooldown = read(ROOT / "data/source_cooldown.json")
    decision = decide(args.event, now, status, policy, force=args.force, cooldown=cooldown)
    if args.event == "schedule" and decision["deploy"] and not decision["collect"]:
        try:
            req = Request(policy["published_status_url"] + "?check=" + str(int(now.timestamp())), headers={"User-Agent": "NeuroBrief-schedule-check/1.0"})
            with urlopen(req, timeout=15) as response:
                published = json.load(response)
        except Exception:
            published = None
        decision = decide(args.event, now, status, policy, published, cooldown=cooldown)
    print(decision["reason"])
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            for key in ("collect", "deploy"):
                output.write(f"{key}={str(decision[key]).lower()}\n")


if __name__ == "__main__":
    main()
