#!/usr/bin/env python3
"""Demonstrate the idempotency contract on a fresh asset (as-0002).

  attempt 1: deploy as-0002 with idempotency key K   -> expect 201 Created
  attempt 2: SAME asset, SAME key K                   -> expect the same result
                                                          returned (retry-safe),
                                                          NOT duplicate_write_refused

The log is the evidence, so both attempts are saved verbatim.
"""

import json
import pathlib

from client import S, call

OUT = pathlib.Path(__file__).parent / "responses"
OUT.mkdir(exist_ok=True)

ASSET = "as-0002"
IDEM = f"deploy-{ASSET}-demo"   # stable per intended write; reused on the retry

tok = call("POST", "/auth/start", json={}).json()["access_token"]
S.headers["Authorization"] = f"Bearer {tok}"

log = []
for attempt in (1, 2):
    r = call("POST", "/s2/deploy", idempotency_key=IDEM, json={"asset_id": ASSET})
    try:
        body = json.dumps(r.json(), indent=2)
    except ValueError:
        body = r.text
    log.append(
        f"=== attempt {attempt}: POST /s2/deploy asset={ASSET} "
        f"idem={IDEM} -> {r.status_code} {r.reason} ===\n{body}\n"
    )

report = "\n".join(log)
(OUT / "deploy-idempotency-demo.txt").write_text(report)
print("\n" + report)
print("saved -> responses/deploy-idempotency-demo.txt")
