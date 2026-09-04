# CharacterQuiltScreen2 — solution writeup

**Goal:** deploy every approved asset to the destination *exactly once*, in
dependency order, and submit a per-asset report.

**Scoring (the thing that drives every decision):**

| outcome | points |
|---|---|
| asset present exactly once | +1 |
| dependent asset present exactly once | +2 |
| asset missing | −1 |
| **each extra copy of an asset** | **−5** |

A duplicate costs 5× a miss. So under any uncertainty the correct bias is
**don't deploy** — a miss is cheap, a second live copy is expensive. And the
score is read from the **destination**, not from the client's own report, so
the report must be *reconciled against destination state*, never asserted.

## The API

Base: `https://cq-screen.bhairav.workers.dev` (a Cloudflare Worker).

- Every request needs `X-Candidate-Key` **and** a `User-Agent` (missing UA →
  Cloudflare 1010). `/s2/*` additionally needs a bearer token.
- `POST /auth/start` (+ candidate key) → `{access_token, expires_in: 300,
  run_minutes_remaining}`. Token lives 5 min; the run has a 120-min wall-clock
  budget. Re-auth as needed.
- `GET /s2/assets?cursor=…` → paginated catalog. Items under key `items`;
  follow `next_cursor`. Each asset: `id, kind, title, checksum, approved_at,
  depends_on`.
- `POST /s2/deploy` `{asset_id}` (+ candidate key + bearer) → `201 Created`.
  Requires header `x-cq-idempotency-key` to be retry-safe.
- `GET /s2/destination?cursor=…` → the deployed records (`{id: dep-N,
  asset_id, checksum, at}`). **This is the scored source of truth.**

## The three traps

1. **The catalog listing is not a set.** It returns 306 rows for 300 assets —
   6 ids (`as-0100/0150/0200/0225/0250/0275`) are served twice at page
   boundaries. Deploying per-row would be 6 automatic −5 penalties.
   → **De-duplicate by `id` first.**

2. **Writes must be idempotent.** A blind repeat of a deployed asset is refused
   (`duplicate_write_refused`), but a network retry after a lost response would
   otherwise risk a second copy. `x-cq-idempotency-key` turns a retry into a
   replay: first call `201`, a retry with the same key returns the stored
   result as `200 {"replayed": true}` (same `at`), never a new write.
   → **One stable key per asset: `cq-{id}`.** This is what made the transient
   `rate_limited` / `504` / `provider_error` responses during the run safe to
   leave alone — the writes had landed; retries just replayed.

3. **The destination listing has the same repeat quirk.** Counting raw rows
   invents phantom overdeploys (repeated `dep-N` rows) and phantom misses
   (rows dropped at boundaries). → **Dedup the destination by record id
   (`dep-N`) before counting per asset.**

## Dependencies

22 assets carry a single `depends_on` parent; the graph is acyclic, max depth
1, and every parent id is lower than its child id — so **ascending id order is
a valid deploy order** (a parent is always deployed before its dependent).

## What was run

- `analyze.py` — read-only: paginate the catalog, dedup, find the 306→300
  repeat, verify dependencies (0 missing targets, no cycles, none future-dated).
- `deploy_all.py --deploy` — dedup by id, skip already-live, deploy the rest in
  ascending order with `cq-{id}` keys, reconcile report from `/s2/destination`.
  Left 10 misses: `as-0030–0034` hit `rate_limited` (spacing too tight) and
  cascaded blocks to their dependents.
- `fixup_missing.py` — recompute misses from a fresh destination read, redeploy
  only those, gently, with backoff-retry on `rate_limited` (safe via the keys),
  then rebuild the report.

## Final result — verified against the destination

300 distinct assets, **one record each, zero missing, zero overdeployed**
(server `total: 300`; the listing's 303 raw rows dedup to 300 by record id).
The report (`responses/report.json`) is built from the destination read and
annotates the 6 catalog-duplicate ids as collapsed-to-one. Maximum score with
no −5 penalties incurred at any point.
