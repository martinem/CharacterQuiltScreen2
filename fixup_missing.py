#!/usr/bin/env python3
"""Deploy whatever is still MISSING from the destination, safely.

The bulk run left 10 assets undeployed (rate_limited + cascaded blocks). This
recovers them:
  * recompute 'missing' from a fresh destination read (deduped by record id,
    because the listing repeats rows at page boundaries)
  * deploy each missing id in dependency order, gently, retrying on rate_limited
    with backoff -- safe because every deploy carries its stable cq-{id} key,
    so a replay never creates a second copy
  * rebuild responses/report.json from the destination (the scored truth),
    deduping record rows and flagging any asset with >1 real record
"""

import collections
import json
import pathlib
import time

from client import S, BASE, call

OUT = pathlib.Path(__file__).parent / "responses"
ALL_IDS = [f"as-{n:04d}" for n in range(1, 301)]


def authenticate():
    tok = call("POST", "/auth/start", json={}).json()["access_token"]
    S.headers["Authorization"] = f"Bearer {tok}"


def destination_rows():
    rows, cur = [], None
    while True:
        r = S.get(f"{BASE}/s2/destination", params={"cursor": cur} if cur else None, timeout=30).json()
        rows.extend(r["items"])
        cur = r.get("next_cursor")
        if not cur:
            break
    # dedup by record id (dep-N); the listing repeats some rows at boundaries
    uniq = {row["id"]: row for row in rows}.values()
    return collections.Counter(row["asset_id"] for row in uniq)


def deploy_with_backoff(asset_id, max_tries=6):
    """POST /s2/deploy, retrying on rate_limited. Idempotency key makes retries safe."""
    delay = 1.0
    for attempt in range(1, max_tries + 1):
        r = call("POST", "/s2/deploy", idempotency_key=f"cq-{asset_id}",
                 json={"asset_id": asset_id})
        try:
            body = r.json()
        except ValueError:
            body = {"raw": r.text}
        if r.status_code in (200, 201):
            return "ok", body
        if body.get("error") == "rate_limited":
            print(f"    rate_limited on {asset_id}, backoff {delay:.1f}s (try {attempt})")
            time.sleep(delay)
            delay = min(delay * 2, 15)
            continue
        return body.get("error") or f"http {r.status_code}", body
    return "rate_limited_gave_up", {}


authenticate()
catalog = {a["id"]: a for a in
           json.load(open(OUT / "assets-all.json"))}   # from analyze.py (deduped by id below)
deps_of = lambda i: ([] if catalog[i].get("depends_on") is None
                     else [catalog[i]["depends_on"]])

counts = destination_rows()
live = {i for i, n in counts.items() if n >= 1}
missing = [i for i in ALL_IDS if i not in live]
print(f"live={len(live)} missing={len(missing)}: {missing}")

for asset_id in missing:                      # ALL_IDS is ascending == dependency-safe
    parents = deps_of(asset_id)
    bad = [p for p in parents if p not in live]
    if bad:
        print(f"  DEFER {asset_id}: parent still missing {bad}")
        continue
    print(f"  deploy {asset_id} (dep={parents or 'none'})")
    status, _ = deploy_with_backoff(asset_id)
    if status == "ok":
        live.add(asset_id)
    else:
        print(f"    -> {asset_id}: {status}")
    time.sleep(0.8)                            # gentler than the bulk run

# Rebuild the report from the destination (scored truth).
final = destination_rows()
# ids the catalog listed more than once (must show they collapsed to 1 deploy)
raw_catalog = json.load(open(OUT / "assets-all.json"))
dup_in_catalog = {i: n for i, n in collections.Counter(a["id"] for a in raw_catalog).items() if n > 1}
report = {}
for asset_id in ALL_IDS:
    n = final.get(asset_id, 0)
    if n == 1:
        entry = {"status": "deployed"}
    elif n == 0:
        entry = {"status": "blocked", "reason": "not in destination after fixup"}
    else:
        entry = {"status": "overdeployed", "copies": n, "reason": "MORE THAN ONE COPY"}
    if deps_of(asset_id):
        entry["dependent_on"] = deps_of(asset_id)
    if asset_id in dup_in_catalog:
        entry["catalog_copies"] = dup_in_catalog[asset_id]
        entry["note"] = (f"listed {dup_in_catalog[asset_id]}x in catalog; "
                         f"collapsed to 1 deploy ({n} live copy)")
    report[asset_id] = entry

deployed = sum(1 for v in report.values() if v["status"] == "deployed")
blocked = sum(1 for v in report.values() if v["status"] == "blocked")
over = sum(1 for v in report.values() if v["status"] == "overdeployed")
payload = {"report": report,
           "summary": {"unique_assets": 300, "destination_records": sum(final.values()),
                       "deployed": deployed, "blocked": blocked, "overdeployed": over,
                       "catalog_duplicate_ids": dup_in_catalog}}
(OUT / "report.json").write_text(json.dumps(payload, indent=2))
print(f"\nFINAL: deployed={deployed} blocked={blocked} overdeployed={over} "
      f"(dest records={sum(final.values())})")
print("Report saved -> responses/report.json")
