#!/usr/bin/env python3
"""Bug backlog — create local entries and sync to GitHub by default."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from bug_io import (
    AREAS,
    ENTRIES_DIR,
    LOGS_DIR,
    ROOT,
    SEVERITIES,
    STATUSES,
    ensure_github_issue,
    find_entry_by_id,
    next_bug_id,
    promote_entry,
    rebuild_backlog,
    slugify,
    sync_status_to_github,
    sync_backlog,
    update_meta,
)


def load_entries() -> list[dict[str, str]]:
    from bug_io import load_entries as _load

    return _load()


def cmd_list(_: argparse.Namespace) -> int:
    entries = load_entries()
    if not entries:
        print("No bugs filed. Run: python3 Scripts/bugs/report_bug.py new")
        return 0
    for e in entries:
        gh = f" (gh #{e['github_issue']})" if e.get("github_issue") else ""
        print(
            f"{e['id']}  [{e.get('status', '?')}]  {e.get('severity', '?')}/{e.get('area', '?')}  "
            f"{e.get('title', '')}{gh}"
        )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    bug_id = args.bug_id.upper()
    path = find_entry_by_id(bug_id)
    if not path:
        print(f"Not found: {bug_id}", file=sys.stderr)
        return 1
    if args.status not in STATUSES:
        print(f"Invalid status. Choose: {', '.join(STATUSES)}", file=sys.stderr)
        return 1

    fields: dict[str, str] = {"status": args.status}
    if args.fixed_in:
        fields["fixed_in"] = args.fixed_in
    meta = update_meta(path, **fields)
    rebuild_backlog()
    print(f"Updated {bug_id} → {args.status}")

    if args.no_github:
        return 0

    issue = ensure_github_issue(path)
    if not issue:
        print("GitHub sync skipped (promote failed or gh unavailable).", file=sys.stderr)
        return 0

    try:
        sync_status_to_github(
            issue,
            args.status,
            bug_id=bug_id,
            entry_name=path.name,
            fixed_in=args.fixed_in or meta.get("fixed_in", ""),
        )
        print(f"GitHub: https://github.com/bryanjiang15/RiftUnbound/issues/{issue}")
    except Exception:
        print("Local status saved; GitHub sync failed.", file=sys.stderr)
        return 0
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    ENTRIES_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    title = args.title or input("Title: ").strip()
    if not title:
        print("Title required.", file=sys.stderr)
        return 1

    severity = args.severity or _prompt_choice("Severity", SEVERITIES, "medium")
    area = args.area or _prompt_choice("Area", AREAS, "engine")
    summary = args.summary or input("One-line summary (optional): ").strip()
    steps = args.steps or _multiline_input("Reproduction steps (blank line to finish)")
    expected = args.expected or input("Expected: ").strip()
    actual = args.actual or input("Actual: ").strip()
    cards = args.cards or input("Cards involved (comma-separated, optional): ").strip()
    commands = args.commands or input("Commands typed (optional): ").strip()

    bug_id = next_bug_id()
    slug = slugify(title)
    entry_path = ENTRIES_DIR / f"{bug_id}-{slug}.md"
    log_path = LOGS_DIR / f"{bug_id}-console.log"

    console_log = ""
    if args.log_file:
        console_log = Path(args.log_file).read_text(encoding="utf-8")
    elif not args.no_log_prompt:
        console_log = _multiline_input("Paste console log (blank line to finish)")

    if console_log.strip():
        log_path.write_text(console_log.strip() + "\n", encoding="utf-8")

    today = date.today().isoformat()
    frontmatter = [
        "---",
        f"id: {bug_id}",
        f"title: {title}",
        "status: open",
        f"severity: {severity}",
        f"area: {area}",
        f"reported: {today}",
        f"cards: {cards}" if cards else "cards:",
        f"commands: {commands}" if commands else "commands:",
        "github_issue:",
        "---",
        "",
        "## Summary",
        "",
        summary or "_Describe what went wrong._",
        "",
        "## Reproduction",
        "",
        steps or "1. _Steps to reproduce_",
        "",
        "## Expected",
        "",
        expected or "_What should happen per rules._",
        "",
        "## Actual",
        "",
        actual or "_What happened instead._",
        "",
        "## Console log",
        "",
    ]
    if console_log.strip():
        frontmatter.append(f"See `logs/{log_path.name}`")
    else:
        frontmatter.append("_No log captured — paste into `logs/{}` later._".format(log_path.name))
    frontmatter.append("")

    entry_path.write_text("\n".join(frontmatter), encoding="utf-8")
    rebuild_backlog()
    print(f"Created {entry_path.relative_to(ROOT)}")
    if console_log.strip():
        print(f"Log saved to {log_path.relative_to(ROOT)}")

    if args.no_github:
        print("Skipped GitHub (--no-github).")
        return 0

    result = promote_entry(entry_path)
    if result:
        issue_num, url = result
        print(f"GitHub issue #{issue_num}: {url}")
    else:
        print(
            "Local entry saved; GitHub issue not created. "
            f"Retry: python3 Scripts/bugs/promote_to_github.py {bug_id}",
            file=sys.stderr,
        )
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    counts = sync_backlog(prune_closed=not args.keep_closed, dry_run=args.dry_run)
    print(
        f"Sync complete: {counts['updated']} status updated, "
        f"{counts['archived']} archived, {counts['drift']} drift warnings, "
        f"{counts['errors']} errors"
    )
    if counts["archived"]:
        print("Archived bugs recorded in Docs/bugs/archive/backlog.md")
    if not args.dry_run:
        print("Rebuilt Docs/bugs/backlog.md (active bugs only)")
    return 0 if counts["errors"] == 0 else 1


def _prompt_choice(label: str, options: tuple[str, ...], default: str) -> str:
    raw = input(f"{label} {list(options)} [{default}]: ").strip().lower()
    return raw if raw in options else default


def _multiline_input(prompt: str) -> str:
    print(prompt)
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line == "":
            break
        lines.append(line)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Riftbound bug backlog (local entry + GitHub issue by default)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new", help="File a new bug (creates GitHub issue by default)")
    p_new.add_argument("--title", "-t")
    p_new.add_argument("--severity", "-s", choices=SEVERITIES)
    p_new.add_argument("--area", "-a", choices=AREAS)
    p_new.add_argument("--summary")
    p_new.add_argument("--steps")
    p_new.add_argument("--expected")
    p_new.add_argument("--actual")
    p_new.add_argument("--cards")
    p_new.add_argument("--commands")
    p_new.add_argument("--log-file", "-l", help="Path to console log text file")
    p_new.add_argument("--no-log-prompt", action="store_true")
    p_new.add_argument(
        "--no-github",
        action="store_true",
        help="Local entry only (offline / skip gh)",
    )
    p_new.set_defaults(func=cmd_new)

    p_list = sub.add_parser("list", help="List all bugs")
    p_list.set_defaults(func=cmd_list)

    p_status = sub.add_parser("status", help="Update bug status (syncs GitHub by default)")
    p_status.add_argument("bug_id", help="e.g. BUG-003")
    p_status.add_argument("status", choices=STATUSES)
    p_status.add_argument("--fixed-in", help="Commit hash or PR reference")
    p_status.add_argument(
        "--no-github",
        action="store_true",
        help="Update local entry only",
    )
    p_status.set_defaults(func=cmd_status)

    p_rebuild = sub.add_parser("rebuild", help="Regenerate backlog.md from entries")
    p_rebuild.set_defaults(func=lambda _: (rebuild_backlog(), print("Rebuilt Docs/bugs/backlog.md"), 0)[2])

    p_sync = sub.add_parser("sync", help="Pull GitHub state and archive closed bugs")
    p_sync.add_argument(
        "--keep-closed",
        action="store_true",
        help="Update status only; do not archive closed entries",
    )
    p_sync.add_argument("--dry-run", action="store_true")
    p_sync.set_defaults(func=cmd_sync)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
