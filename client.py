import requests, time, json, uuid

BASE = "https://cq-screen.bhairav.workers.dev"
KEY  = "cq-fe212e66e2d2732a"

S = requests.Session()
S.headers.update({
    "X-Candidate-Key": KEY,
    "User-Agent": "cq-candidate/1.0",   # REQUIRED — Cloudflare 1010 without it
    "Content-Type": "application/json",
})

def call(method, path, idempotency_key=None, **kw):
    """Log everything. The log is the evidence.

    Pass idempotency_key to make a write retry-safe: the server records the
    result under that key and returns it (instead of duplicate_write_refused)
    on any retry that reuses the same key. Reuse ONE key per intended write.
    """
    if idempotency_key:
        kw.setdefault("headers", {})["x-cq-idempotency-key"] = idempotency_key
    r = S.request(method, f"{BASE}{path}", timeout=30, **kw)
    print(f"{method} {path} -> {r.status_code}")
    print("  headers:", dict(r.headers))
    print("  body:", r.text[:2000])
    return r