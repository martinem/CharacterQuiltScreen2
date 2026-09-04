#!/usr/bin/env python3
"""READ-ONLY. Fetch the full /s2/assets catalog and analyze it for scoring traps.

No writes. Looks for:
  - duplicate CHECKSUMS (same content under different asset_ids -> deploying
    more than one is an "extra copy", the -5 penalty)
  - duplicate titles
  - dependency structure (depends_on): chains, missing targets, cycles
  - approvals dated in the future (possibly must-not-deploy)
Saves the raw manifest and a written analysis so the log is the evidence.
"""

import collections
import json
import pathlib
import time

from client import S, BASE, call

OUT = pathlib.Path(__file__).parent / "responses"
OUT.mkdir(exist_ok=True)


def authenticate():
    tok = call("POST", "/auth/start", json={}).json()["access_token"]
    S.headers["Authorization"] = f"Bearer {tok}"


def fetch_all():
    assets, cursor, t0 = [], None, time.time()
    while True:
        if time.time() - t0 > 240:      # refresh token well inside 300s TTL
            authenticate(); t0 = time.time()
        params = {"cursor": cursor} if cursor else None
        r = S.get(f"{BASE}/s2/assets", params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        assets.extend(data["items"])
        cursor = data.get("next_cursor")
        if not cursor:
            return assets, data.get("total")


authenticate()
assets, total = fetch_all()
(OUT / "assets-all.json").write_text(json.dumps(assets, indent=2))

by_id = {a["id"]: a for a in assets}

# --- duplicate content (checksum) ---
by_checksum = collections.defaultdict(list)
for a in assets:
    by_checksum[a["checksum"]].append(a["id"])
dup_checksums = {c: ids for c, ids in by_checksum.items() if len(ids) > 1}

# --- duplicate titles ---
by_title = collections.defaultdict(list)
for a in assets:
    by_title[a["title"]].append(a["id"])
dup_titles = {t: ids for t, ids in by_title.items() if len(ids) > 1}

# --- dependency structure ---
def deps_of(a):
    d = a.get("depends_on")
    return [] if d is None else (list(d) if isinstance(d, (list, tuple)) else [d])

has_deps = [a["id"] for a in assets if deps_of(a)]
missing_dep = {a["id"]: [d for d in deps_of(a) if d not in by_id] for a in assets}
missing_dep = {k: v for k, v in missing_dep.items() if v}

# --- approvals in the future ---
now = time.time()
future = [(a["id"], a["approved_at"]) for a in assets if a.get("approved_at", 0) > now]

kinds = collections.Counter(a["kind"] for a in assets)

lines = [
    f"total assets (server):   {total}",
    f"assets fetched:          {len(assets)}",
    f"unique checksums:        {len(by_checksum)}",
    f"kinds:                   {dict(kinds)}",
    f"assets WITH depends_on:  {len(has_deps)}",
    f"deps pointing to missing id: {len(missing_dep)} {missing_dep or ''}",
    f"approved in the future:  {len(future)} {future or ''}",
    "",
    f"### DUPLICATE CHECKSUMS (same content -> deploy only ONE each): {len(dup_checksums)} groups",
]
extra_copies = 0
for c, ids in sorted(dup_checksums.items(), key=lambda kv: -len(kv[1])):
    extra_copies += len(ids) - 1
    detail = ", ".join(f"{i}({by_id[i]['kind']})" for i in sorted(ids))
    lines.append(f"  checksum {c}: {detail}")
lines.append(f"  -> redundant copies if all deployed: {extra_copies}  (each = -5)")
lines.append("")
lines.append(f"### DUPLICATE TITLES: {len(dup_titles)} groups")
for t, ids in sorted(dup_titles.items()):
    lines.append(f"  {t}: {sorted(ids)}")

report = "\n".join(lines)
(OUT / "analysis.txt").write_text(report + "\n")
print(report)
print("\nsaved -> responses/assets-all.json, responses/analysis.txt")
