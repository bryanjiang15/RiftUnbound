#!/usr/bin/env python3
"""Local bug backlog — create, list, and update entries under Docs/bugs/."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUGS_DIR = ROOT / "Docs" / "bugs"
ENTRIES_DIR = BUGS_DIR / "entries"
LOGS_DIR = BUGS_DIR / "logs"
BACKLOG = BUGS_DIR / "backlog.md"

STATUSES = ("open", "investigating", "confirmed", "fixed", "wontfix", "duplicate")
SEVERITIES = ("critical", "high", "medium", "low")
AREAS = ("engine", "ui", "ai", "cards", "tests", "docs")


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:60] or "untitled"


def next_bug_id() -> str:
    max_n = 0
    for path in ENTRIES_DIR.glob("BUG-*.md"):
        m = re.match(r"BUG-(\d+)", path.name)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"BUG-{max_n + 1:03d}"


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    block = text[3:end].strip()
    data: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            data[key.strip()] = val.strip()
    return data


def load_entries() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(ENTRIES_DIR.glob("BUG-*.md")):
        meta = parse_frontmatter(path.read_text(encoding="utf-8"))
        meta["_path"] = str(path.relative_to(ROOT))
        meta["_file"] = path.name
        if "id" not in meta:
            meta["id"] = path.stem.split("-")[0] + "-" + path.stem.split("-")[1]
        rows.append(meta)
    rows.sort(key=lambda r: r.get("id", ""))
    return rows


def rebuild_backlog() -> None:
    entries = load_entries()
    counts = {s: 0 for s in STATUSES}
    lines = [
        "# Bug Backlog Index",
        "",
        "> Auto-updated by `python3 Scripts/bugs/report_bug.py`. Edit entries in `entries/`, not this table.",
        "",
        "| ID | Status | Sev | Area | Title | Reported |",
        "|----|--------|-----|------|-------|----------|",
    ]
    for e in entries:
        status = e.get("status", "open")
        counts[status] = counts.get(status, 0) + 1
        link = f"[{e['id']}](entries/{e['_file']})"
        lines.append(
            f"| {link} | {status} | {e.get('severity', '?')} | {e.get('area', '?')} "
            f"| {e.get('title', e['_file'])} | {e.get('reported', '?')} |"
        )
    if not entries:
        lines.append("| — | — | — | — | *No bugs filed yet* | — |")
    lines.extend(
        [
            "",
            "**Counts:** "
            + f"{counts.get('open', 0)} open · "
            + f"{counts.get('investigating', 0)} investigating · "
            + f"{counts.get('confirmed', 0)} confirmed · "
            + f"{counts.get('fixed', 0)} fixed · "
            + f"{counts.get('wontfix', 0)} wontfix",
            "",
        ]
    )
    BACKLOG.write_text("\n".join(lines), encoding="utf-8")


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
    path = _find_entry(bug_id)
    if not path:
        print(f"Not found: {bug_id}", file=sys.stderr)
        return 1
    text = path.read_text(encoding="utf-8")
    if args.status not in STATUSES:
        print(f"Invalid status. Choose: {', '.join(STATUSES)}", file=sys.stderr)
        return 1
    if re.search(r"^status:.*$", text, re.MULTILINE):
        text = re.sub(r"^status:.*$", f"status: {args.status}", text, count=1, flags=re.MULTILINE)
    else:
        text = text.replace("---\n", f"---\nstatus: {args.status}\n", 1)
    if args.fixed_in:
        if re.search(r"^fixed_in:.*$", text, re.MULTILINE):
            text = re.sub(r"^fixed_in:.*$", f"fixed_in: {args.fixed_in}", text, count=1, flags=re.MULTILINE)
        else:
            text = text.replace("---\n", f"---\nfixed_in: {args.fixed_in}\n", 1)
    path.write_text(text, encoding="utf-8")
    rebuild_backlog()
    print(f"Updated {bug_id} → {args.status}")
    return 0


def _find_entry(bug_id: str) -> Path | None:
    for path in ENTRIES_DIR.glob(f"{bug_id}*.md"):
        return path
    return None


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
    print(f"View index: Docs/bugs/backlog.md")
    return 0


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
    parser = argparse.ArgumentParser(description="Riftbound local bug backlog")
    sub = parser.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new", help="File a new bug")
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
    p_new.set_defaults(func=cmd_new)

    p_list = sub.add_parser("list", help="List all bugs")
    p_list.set_defaults(func=cmd_list)

    p_status = sub.add_parser("status", help="Update bug status")
    p_status.add_argument("bug_id", help="e.g. BUG-003")
    p_status.add_argument("status", choices=STATUSES)
    p_status.add_argument("--fixed-in", help="Commit hash or PR reference")
    p_status.set_defaults(func=cmd_status)

    p_rebuild = sub.add_parser("rebuild", help="Regenerate backlog.md from entries")
    p_rebuild.set_defaults(func=lambda _: (rebuild_backlog(), print("Rebuilt Docs/bugs/backlog.md"), 0)[2])

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
