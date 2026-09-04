#!/usr/bin/env python3
"""Exchange the candidate key for a bearer token, then re-probe the /s2 paths."""

import json
import pathlib
import time

from client import S, call

PATHS = ["/s2/", "/s2/assets", "/s2/manifest"]
OUT = pathlib.Path(__file__).parent / "responses"
OUT.mkdir(exist_ok=True)


def slug(path):
    return path.strip("/").replace("/", "-") or "root"


def save(r, name):
    body = r.text
    try:
        body = json.dumps(r.json(), indent=2)
    except ValueError:
        pass
    dest = OUT / f"{name}.txt"
    dest.write_text(
        f"{r.request.method} {r.url} -> {r.status_code} {r.reason}\n"
        f"--- headers ---\n"
        + "\n".join(f"{k}: {v}" for k, v in r.headers.items())
        + f"\n--- body ({len(r.content)} bytes) ---\n{body}\n"
    )
    print(f"  saved -> responses/{name}.txt\n")


r = call("POST", "/auth/start", json={})
save(r, "auth-start")

payload = r.json() if r.headers.get("Content-Type", "").startswith("application/json") else {}
token = next((payload[k] for k in ("token", "bearer", "access_token", "bearer_token") if payload.get(k)), None)
if not token:
    raise SystemExit(f"No token field in /auth/start response: {list(payload)}")

print(f"token: {token[:12]}… ({len(token)} chars)\n")
S.headers["Authorization"] = f"Bearer {token}"

for i, path in enumerate(PATHS):
    if i:
        time.sleep(1)
    save(call("GET", path), f"{slug(path)}-auth")
