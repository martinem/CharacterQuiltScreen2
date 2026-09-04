#!/usr/bin/env python3
"""Export a Claude Code session transcript to readable Markdown.

Usage:
    python3 transcripts/export_transcript.py                 # newest session for this project
    python3 transcripts/export_transcript.py --session <id>  # a specific session
    python3 transcripts/export_transcript.py --thinking      # include reasoning blocks
"""

import argparse
import json
import pathlib
import sys
from datetime import datetime

PROJECT_DIR = pathlib.Path.home() / ".claude" / "projects" / "-Users-martinemoses-Challenges-CharacterQuiltScreen2"
OUT_DIR = pathlib.Path(__file__).parent
MAX_BLOCK = 4000  # chars before truncating a tool input/result


def clip(text, limit=MAX_BLOCK):
    text = text.rstrip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [truncated, {len(text) - limit} more chars]"


def blocks(message):
    """Normalize a message's content into a list of blocks."""
    content = message.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content or []


def ts(record):
    raw = record.get("timestamp")
    if not raw:
        return ""
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%H:%M:%S")
    except ValueError:
        return raw


def render(path, include_thinking):
    out = [f"# Session transcript — {path.stem}", ""]
    out.append(f"Exported {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} from `{path}`")
    out.append("")

    last_role = None
    for line in path.open():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        kind = rec.get("type")
        if kind not in ("user", "assistant"):
            continue  # skip attachments, snapshots, and other bookkeeping records
        if rec.get("isSidechain"):
            continue

        for block in blocks(rec.get("message", {})):
            btype = block.get("type")

            if btype == "text":
                text = block.get("text", "").strip()
                # Injected context blocks are harness noise, not conversation.
                if not text or text.startswith("<system-reminder>"):
                    continue
                role = "User" if kind == "user" else "Claude"
                if role != last_role:
                    out.append(f"\n## {role} — {ts(rec)}\n")
                    last_role = role
                out.append(text)

            elif btype == "thinking" and include_thinking:
                out.append(f"\n<details><summary>Reasoning</summary>\n\n{clip(block.get('thinking', ''))}\n\n</details>")

            elif btype == "tool_use":
                params = json.dumps(block.get("input", {}), indent=2)
                out.append(f"\n**→ {block.get('name')}**\n\n```json\n{clip(params, 1500)}\n```")
                last_role = None

            elif btype == "tool_result":
                content = block.get("content")
                if isinstance(content, list):
                    content = "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
                content = (content or "").strip()
                if content:
                    out.append(f"\n<details><summary>result</summary>\n\n```\n{clip(content)}\n```\n\n</details>")
                last_role = None

    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", help="session id (defaults to most recently modified)")
    ap.add_argument("--thinking", action="store_true", help="include reasoning blocks")
    args = ap.parse_args()

    if args.session:
        path = PROJECT_DIR / f"{args.session}.jsonl"
    else:
        sessions = sorted(PROJECT_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        if not sessions:
            sys.exit(f"No session logs found in {PROJECT_DIR}")
        path = sessions[-1]

    if not path.exists():
        sys.exit(f"No such session log: {path}")

    dest = OUT_DIR / f"session-{path.stem}.md"
    dest.write_text(render(path, args.thinking))
    print(f"Wrote {dest} ({dest.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
