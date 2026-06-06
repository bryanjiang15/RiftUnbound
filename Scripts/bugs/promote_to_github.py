#!/usr/bin/env python3
"""Promote a local Docs/bugs/entries/BUG-NNN file to a GitHub issue via gh CLI."""

from __future__ import annotations

import argparse
import sys

from bug_io import find_entry_by_id, parse_frontmatter, promote_entry


def main() -> int:
    parser = argparse.ArgumentParser(description="Promote local bug to GitHub issue")
    parser.add_argument("bug_id", help="e.g. BUG-003")
    parser.add_argument("--dry-run", action="store_true", help="Print issue body only")
    args = parser.parse_args()

    entry = find_entry_by_id(args.bug_id)
    if not entry:
        print(f"Not found: {args.bug_id}", file=sys.stderr)
        return 1

    meta, _ = parse_frontmatter(entry.read_text(encoding="utf-8"))
    if meta.get("github_issue") and not args.dry_run:
        print(f"Already linked to GitHub issue #{meta['github_issue']}")
        return 0

    result = promote_entry(entry, dry_run=args.dry_run)
    if args.dry_run:
        return 0
    if not result:
        return 1
    _, url = result
    print(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
