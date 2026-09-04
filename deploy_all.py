#!/usr/bin/env python3
"""Deploy all /s2 assets exactly once, in dependency order, then build the
report from the DESTINATION (the scored source of truth) -- not from our log.

Scoring reality (why this is written so defensively):
  +1 asset present once | +2 dependent asset present once
  -1 asset missing      | -5 EACH extra copy
A duplicate costs 5x a miss, so every choice breaks toward "don't deploy twice".

Safeguards:
  * catalog is de-duplicated by id (the listing serves 306 rows for 300 ids)
  * assets already in the destination are skipped, never re-attempted
  * one stable idempotency key per id -> network retries replay, never duplicate
  * the final report is derived from a fresh read of /s2/destination and counts
    each asset; anything present >1 time is flagged as an OVERDEPLOY

  read-only (default):  python deploy_all.py        # plan + current dest, no writes
  live:                 python deploy_all.py --deploy
"""

import argparse
import collections
import json
import pathlib
import time

from client import S, BASE, call

OUT = pathlib.Path(__file__).parent / "responses"
OUT.mkdir(exist_ok=True)
TOKEN_TTL, MARGIN = 300, 60
_authed_at = 0.0


def authenticate():
    global _authed_at
    tok = call("POST", "/auth/start", json={}).json()["access_token"]
    S.headers["Authorization"] = f"Bearer {tok}"
    _authed_at = time.time()


def ensure_auth():
    if time.time() - _authed_at > TOKEN_TTL - MARGIN:
        authenticate()


def paginate(path):
    """Follow next_cursor through a listing endpoint, returning all items."""
    items, cursor = [], None
    while True:
        ensure_auth()
        params = {"cursor": cursor} if cursor else None
        r = S.get(f"{BASE}{path}", params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        items.extend(data["items"])
        cursor = data.get("next_cursor")
        if not cursor:
            return items


def deps_of(asset):
    d = asset.get("depends_on")
    return [] if d is None else (list(d) if isinstance(d, (list, tuple)) else [d])


def destination_counts():
    """asset_id -> number of live copies in the destination (source of truth)."""
    return collections.Counter(r["asset_id"] for r in paginate("/s2/destination"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deploy", action="store_true", help="actually POST deploys")
    args = ap.parse_args()

    authenticate()

    # 1) Canonical asset set: de-duplicate the listing by id.
    raw = paginate("/s2/assets")
    catalog_count = collections.Counter(a["id"] for a in raw)
    dup_in_catalog = {i: n for i, n in catalog_count.items() if n > 1}
    by_id = {}
    for a in raw:
        by_id.setdefault(a["id"], a)
    order = sorted(by_id, key=lambda i: int(i.split("-")[1]))  # parent id < child id
    dependents = {i for i in by_id if deps_of(by_id[i])}
    print(f"catalog rows={len(raw)} unique={len(by_id)} dependents={len(dependents)}")
    print(f"ids listed more than once in catalog (collapsed to 1 deploy each): "
          f"{dup_in_catalog or 'none'}")

    # 2) Current destination state.
    before = destination_counts()
    already = {i for i, n in before.items() if n >= 1}
    over_before = {i: n for i, n in before.items() if n > 1}
    print(f"destination before: {sum(before.values())} records, "
          f"{len(already)} distinct, overdeployed={over_before or 'none'}")

    todo = [i for i in order if i not in already]
    print(f"to deploy: {len(todo)}  (skipping {len(already)} already live)")

    if not args.deploy:
        (OUT / "deploy-plan.txt").write_text(
            f"unique assets: {len(by_id)}\ndependents: {sorted(dependents)}\n"
            f"already live: {sorted(already)}\nto deploy ({len(todo)}): {todo}\n")
        print("Read-only. Re-run with --deploy to execute.")
        return

    # 3) Deploy in dependency-safe order. Record per-id call outcome for reasons.
    live = set(already)
    outcomes = {}
    for asset_id in todo:
        parents = deps_of(by_id[asset_id])
        missing_parent = [p for p in parents if p not in live]
        if missing_parent:                       # never happens given ordering, but be safe
            outcomes[asset_id] = f"dependency not deployed: {missing_parent}"
            continue
        ensure_auth()
        r = call("POST", "/s2/deploy", idempotency_key=f"cq-{asset_id}",
                 json={"asset_id": asset_id})
        try:
            body = r.json()
        except ValueError:
            body = {"raw": r.text}
        if r.status_code in (200, 201):
            outcomes[asset_id] = "ok"
            live.add(asset_id)
        else:
            outcomes[asset_id] = body.get("error") or f"http {r.status_code}"
        time.sleep(0.25)

    # 4) Build the report from a FRESH destination read (the scored truth).
    after = destination_counts()
    report = {}
    for asset_id in order:
        n = after.get(asset_id, 0)
        if n == 1:
            entry = {"status": "deployed"}
        elif n == 0:
            entry = {"status": "blocked", "reason": outcomes.get(asset_id, "not deployed")}
        else:  # n > 1 -- the -5 case; surface it unmistakably
            entry = {"status": "overdeployed", "copies": n,
                     "reason": "MORE THAN ONE COPY IN DESTINATION"}
        # Account for catalog duplicates explicitly: show that an id listed
        # multiple times was still deployed exactly once.
        if asset_id in dup_in_catalog:
            entry["catalog_copies"] = dup_in_catalog[asset_id]
            entry["note"] = (f"listed {dup_in_catalog[asset_id]}x in catalog; "
                             f"deployed once ({n} live copy)")
        if asset_id in dependents:
            entry["dependent_on"] = deps_of(by_id[asset_id])
        report[asset_id] = entry

    payload = {
        "report": report,
        "summary": {
            "unique_assets": len(by_id),
            "catalog_rows": len(raw),
            "catalog_duplicate_ids": dup_in_catalog,
            "destination_records": sum(after.values()),
            "deployed": sum(1 for v in report.values() if v["status"] == "deployed"),
            "blocked": sum(1 for v in report.values() if v["status"] == "blocked"),
            "overdeployed": sum(1 for v in report.values() if v["status"] == "overdeployed"),
        },
    }
    (OUT / "report.json").write_text(json.dumps(payload, indent=2))

    deployed = sum(1 for v in report.values() if v["status"] == "deployed")
    blocked = sum(1 for v in report.values() if v["status"] == "blocked")
    over = sum(1 for v in report.values() if v["status"] == "overdeployed")
    print(f"\nDONE. destination records={sum(after.values())} "
          f"deployed={deployed} blocked={blocked} overdeployed={over}")
    if over:
        print("!! OVERDEPLOY DETECTED -- investigate before submitting !!")
    print("Report saved -> responses/report.json")


if __name__ == "__main__":
    main()
