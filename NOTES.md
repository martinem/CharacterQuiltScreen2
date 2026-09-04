# When is this thing entitled to say "deployed"?

## The answer

Only when a **read of the destination, performed after the write, shows the
asset present exactly once** — with the read's own artifacts removed first.

Everything short of that is a claim, not evidence:

- **A `201`/`200` from `POST /s2/deploy` is not success.** It is a report from
  the write path. The scoring rubric is explicit that the report and the
  destination are allowed to disagree, and that the disagreement is the whole
  point. A response says "I tried and the far end acknowledged"; it does not say
  "there is exactly one copy live right now."
- **A transient failure is not failure.** `504`, `provider_error`, and
  `rate_limited` are ambiguous — the write may well have landed before the
  response died. Treating them as "not deployed" and re-firing is how you
  manufacture the −5 second copy. (The idempotency key is what makes that
  re-fire safe, but the key is a safety net, not a substitute for reading.)
- **"Exactly once" is part of the definition of success, not a separate check.**
  For this system, "deployed" that is silently "deployed twice" is worse than
  "not deployed" — one costs + nothing useful and −5; the other costs −1.
  So a claim of success is only earned when the read shows a count of exactly 1
  — not ≥1.

And the read must be **cleaned before it is counted**. `GET /s2/destination`
repeats records at page boundaries (as `GET /s2/assets` does). Counting raw
rows invents both phantom duplicates and phantom misses. So the honest form of
the claim is: *dedup the listing by record id (`dep-N`), count records per
asset, and only then is a count of 1 a licence to say "deployed."*

Ideally the claim is also backed by a **coverage check** — the number of
distinct assets read equals the server's declared `total` — so that a row
dropped at a boundary cannot pass as a genuine miss.

## Does the code live up to this?

**Mostly yes, in the end — but only after one route that did not.**

Where it holds:

- `fixup_missing.py` and the final verification read the destination *after*
  writing, **dedup by record id**, and count per asset. `report.json` is built
  from that read, and its `deployed` entries mean "one record observed in the
  destination," not "the POST returned 2xx." That is the standard above.
- Transient `504`/`provider_error`/`rate_limited` responses during the fixup
  were **not** trusted in either direction — the final destination read is what
  decided each asset's status, which is exactly right.

Where it fell short:

1. **`deploy_all.py` counted raw destination rows without deduping by record
   id.** Its end-of-run summary therefore *claimed* 3 overdeploys and 10 misses
   that were partly artifacts of the listing repeat. It did not falsely claim
   success — it erred toward alarm, which is the safe direction — but it failed
   the "clean the read before you count it" rule, and I only caught it by
   re-reading by hand. That logic was fixed in `fixup_missing.py`, not in
   `deploy_all.py` itself, so the flawed counter still lives in the repo.
2. **The very first version treated `duplicate_write_refused` as `deployed` on
   faith** — asserting success from a write-path error with no read at all. That
   was the exact sin this question is about. It was removed before any bulk run,
   but it is worth naming: the instinct to believe the write path is the
   default failure mode.
3. **No automated coverage guard.** `fixup_missing.py` prints
   `deployed=300` because 300 assets each showed one record — but it does not
   assert `distinct_assets == server total` before saying so. If the listing
   had dropped a row at a boundary, the code would have under-claimed silently
   (a −1 risk, not a −5 — the safe side, but still a gap). The coverage check
   was done once, by hand, in the final verification step; it is not baked into
   the code that writes the report.

**Summary:** the code is entitled to the "deployed" claims in the final
`report.json`, because those come from a post-write, record-id-deduped read of
the destination. The path that got there included a counter that broke the
rule (raw-row counting) and an early version that ignored it entirely
(trusting the write path). The standard is met at the finish line; it was not
met at every step, and the repo still contains one function that does not meet
it.
