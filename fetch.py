#!/usr/bin/env python3
"""GET each probe path via client.call and save the full response to responses/."""

import json
import pathlib
import time

from client import call

PATHS = ["/", "/s2/", "/s2/assets", "/s2/manifest"]
OUT = pathlib.Path(__file__).parent / "responses"
OUT.mkdir(exist_ok=True)


def slug(path):
    name = path.strip("/").replace("/", "-")
    return name or "root"


for i, path in enumerate(PATHS):
    if i:
        time.sleep(1)  # be gentle with the screening worker
    r = call("GET", path)

    body = r.text
    try:
        body = json.dumps(r.json(), indent=2)
    except ValueError:
        pass

    dest = OUT / f"{slug(path)}.txt"
    dest.write_text(
        f"GET {r.url} -> {r.status_code} {r.reason}\n"
        f"--- headers ---\n"
        + "\n".join(f"{k}: {v}" for k, v in r.headers.items())
        + f"\n--- body ({len(r.content)} bytes) ---\n{body}\n"
    )
    print(f"  saved -> {dest.relative_to(dest.parent.parent)}\n")
