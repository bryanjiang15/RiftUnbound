#!/usr/bin/env python3
"""Promote a local Docs/bugs/entries/BUG-NNN file to a GitHub issue via gh CLI."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENTRIES_DIR = ROOT / "Docs" / "bugs" / "entries"
LOGS_DIR = ROOT / "Docs" / "bugs" / "logs"


def parse_entry(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    meta: dict[str, str] = {}
    for line in text[3:end].strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    body = text[end + 4 :].lstrip()
    return meta, body


def find_entry(bug_id: str) -> Path | None:
    bug_id = bug_id.upper()
    matches = list(ENTRIES_DIR.glob(f"{bug_id}*.md"))
    return matches[0] if matches else None


def build_issue_body(meta: dict[str, str], body: str) -> str:
    bug_id = meta.get("id", "BUG-???")
    log_file = LOGS_DIR / f"{bug_id}-console.log"
    parts = [
        f"**Local backlog:** `Docs/bugs/entries/{bug_id}`",
        f"**Severity:** {meta.get('severity', '?')} · **Area:** {meta.get('area', '?')}",
        "",
    ]
    if meta.get("cards"):
        parts.append(f"**Cards:** {meta['cards']}")
    if meta.get("commands"):
        parts.append(f"**Commands:** `{meta['commands']}`")
    parts.extend(["", body.strip()])
    if log_file.exists():
        log_text = log_file.read_text(encoding="utf-8").strip()
        if log_text:
            parts.extend(["", "## Console log", "", "```", log_text[:12000], "```"])
            if len(log_text) > 12000:
                parts.append("\n_(log truncated — see local file)_")
    return "\n".join(parts)


def update_github_issue_field(entry_path: Path, issue_number: str) -> None:
    text = entry_path.read_text(encoding="utf-8")
    if re.search(r"^github_issue:.*$", text, re.MULTILINE):
        text = re.sub(
            r"^github_issue:.*$",
            f"github_issue: {issue_number}",
            text,
            count=1,
            flags=re.MULTILINE,
        )
    else:
        text = text.replace("---\n", f"---\ngithub_issue: {issue_number}\n", 1)
    entry_path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Promote local bug to GitHub issue")
    parser.add_argument("bug_id", help="e.g. BUG-003")
    parser.add_argument("--dry-run", action="store_true", help="Print issue body only")
    args = parser.parse_args()

    entry = find_entry(args.bug_id)
    if not entry:
        print(f"Not found: {args.bug_id}", file=sys.stderr)
        return 1

    meta, body = parse_entry(entry)
    if meta.get("github_issue"):
        print(f"Already linked to GitHub issue #{meta['github_issue']}")
        return 0

    title = meta.get("title", entry.stem)
    issue_body = build_issue_body(meta, body)
    labels = ["bug", meta.get("area", "engine"), f"severity:{meta.get('severity', 'medium')}"]

    if args.dry_run:
        print(f"Title: [{meta.get('id')}] {title}")
        print(f"Labels: {labels}")
        print("---")
        print(issue_body)
        return 0

    cmd = [
        "gh",
        "issue",
        "create",
        "--title",
        f"[{meta.get('id', 'BUG')}] {title}",
        "--body",
        issue_body,
    ]
    for label in labels:
        cmd.extend(["--label", label])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=ROOT)
    except FileNotFoundError:
        print("gh CLI not found. Install: https://cli.github.com/", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print(e.stderr or e.stdout, file=sys.stderr)
        print(
            "\nTip: create labels first, or remove --label args. "
            "Use --dry-run to preview.",
            file=sys.stderr,
        )
        return 1

    url = result.stdout.strip()
    m = re.search(r"/issues/(\d+)", url)
    if m:
        update_github_issue_field(entry, m.group(1))
        subprocess.run(
            [sys.executable, str(ROOT / "Scripts/bugs/report_bug.py"), "rebuild"],
            cwd=ROOT,
            check=False,
        )
    print(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
