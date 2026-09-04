#!/usr/bin/env python3
"""Probe for sibling endpoints under /s2/ using a bearer token.

With auth, a real 404 ({"error":"not_found"}) means the route doesn't exist,
so anything that ISN'T a plain not_found is interesting.
"""

import json
import pathlib
import time

from client import S, call

OUT = pathlib.Path(__file__).parent / "responses"
OUT.mkdir(exist_ok=True)

# Guesses drawn from the vocabulary the API already uses: the /s2/assets shape
# (assets, next_cursor, total, depends_on, checksum, approved_at) and the
# asset "kind" values (landing_page, form, cta, email).
CANDIDATES = [
    "/s2/assets/as-0001",       # single-item lookup
    "/s2/assets/as-0010",       # the one with a dependency
    "/s2/asset",
    "/s2/manifests",
    "/s2/dependencies",
    "/s2/deps",
    "/s2/graph",
    "/s2/kinds",
    "/s2/types",
    "/s2/checksums",
    "/s2/approvals",
    "/s2/approved",
    "/s2/status",
    "/s2/health",
    "/s2/info",
    "/s2/meta",
    "/s2/schema",
    "/s2/version",
    "/s2/config",
    "/s2/submit",
    "/s2/submissions",
    "/s2/build",
    "/s2/builds",
    "/s2/render",
    "/s2/quilt",
    "/s2/screen",
    "/s2/task",
    "/s2/tasks",
    "/s2/challenge",
    "/s2/instructions",
    "/s2/readme",
    "/s2/docs",
    "/s2/report",
    "/s2/results",
    "/s2/validate",
    "/s2/verify",
    "/s2/check",
    "/s2/users",
    "/s2/me",
    "/s2/candidate",
    "/s2/session",
    "/s2/runs",
    "/s2/events",
    "/s2/log",
    "/s2/logs",
]


def authenticate():
    r = call("POST", "/auth/start", json={})
    tok = r.json()["access_token"]
    S.headers["Authorization"] = f"Bearer {tok}"
    return time.time()


def slug(path):
    return path.strip("/").replace("/", "-")


authed_at = authenticate()
summary = []

for i, path in enumerate(CANDIDATES):
    if time.time() - authed_at > 240:      # token lives 300s; refresh with margin
        authed_at = authenticate()
    if i:
        time.sleep(0.4)

    r = S.get(f"https://cq-screen.bhairav.workers.dev{path}", timeout=30)
    body = r.text
    try:
        body = json.dumps(r.json(), indent=2)
    except ValueError:
        pass

    not_found = r.status_code == 404 and '"not_found"' in r.text
    flag = "" if not_found else "  <-- INTERESTING"
    line = f"{r.status_code}  {path}{flag}"
    print(line)
    summary.append(line)

    # Only save bodies for the interesting hits, to keep responses/ readable.
    if not not_found:
        dest = OUT / f"probe-{slug(path)}.txt"
        dest.write_text(
            f"GET {r.url} -> {r.status_code} {r.reason}\n"
            f"--- body ({len(r.content)} bytes) ---\n{body}\n"
        )

(OUT / "sibling-probe-summary.txt").write_text("\n".join(summary) + "\n")
print(f"\nSummary saved -> responses/sibling-probe-summary.txt")
