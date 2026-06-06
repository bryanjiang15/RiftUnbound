#!/usr/bin/env python3
"""
GitHub ↔ local bug backlog sync for Cursor agent workflows.

  import <issue#>   Pull GitHub issue into Docs/bugs/entries/
  start  <ref>      Mark investigating + comment on GitHub
  resolve <ref>     Mark fixed locally + close GitHub issue
  context <ref>     Print agent briefing (entry path, tests to run)

<ref> = GitHub issue number (42) or local id (BUG-003).
Requires: gh CLI authenticated (`gh auth login`).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from bug_io import (
    REPO,
    ROOT,
    LOGS_DIR,
    ensure_github_issue,
    find_entry_by_github_issue,
    find_entry_by_id,
    parse_bug_id_from_title,
    parse_frontmatter,
    rebuild_backlog,
    create_entry_from_issue,
    run_gh,
    update_meta,
)


def _run_gh(args: list[str]) -> str:
    try:
        return run_gh(args)
    except Exception:
        sys.exit(1)


def _fetch_issue(issue_number: str) -> dict:
    raw = _run_gh(
        [
            "issue",
            "view",
            issue_number,
            "--repo",
            REPO,
            "--json",
            "number,title,body,labels,state,url",
        ]
    )
    data = json.loads(raw)
    data["label_names"] = [lb["name"] for lb in data.get("labels", [])]
    return data


def _resolve_ref(ref: str, *, require_github: bool = False) -> tuple[str, Path | None]:
    ref = ref.strip()
    if re.fullmatch(r"BUG-\d+", ref, re.IGNORECASE):
        bug_id = ref.upper()
        path = find_entry_by_id(bug_id)
        if not path:
            print(f"No local entry for {bug_id}", file=sys.stderr)
            sys.exit(1)
        meta, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        issue = meta.get("github_issue", "")
        if not issue and require_github:
            print(
                f"{bug_id} has no github_issue field. "
                f"Run: bug_github.py import <issue#> or report_bug.py status {bug_id} open",
                file=sys.stderr,
            )
            sys.exit(1)
        return issue, path
    issue = ref.lstrip("#")
    if not issue.isdigit():
        print(f"Invalid ref: {ref}", file=sys.stderr)
        sys.exit(1)
    path = find_entry_by_github_issue(issue)
    return issue, path


def cmd_import(args: argparse.Namespace) -> int:
    issue = _fetch_issue(str(args.issue))
    number = str(issue["number"])
    existing = find_entry_by_github_issue(number)
    bug_id = parse_bug_id_from_title(issue["title"])
    if existing and not args.force:
        print(f"Already imported: {existing.relative_to(ROOT)}")
        if bug_id:
            update_meta(existing, id=bug_id)
        return 0
    if existing and args.force:
        existing.unlink()

    by_id = find_entry_by_id(bug_id) if bug_id else None
    if by_id and not existing:
        update_meta(
            by_id,
            github_issue=number,
            title=re.sub(r"^\[BUG-\d+\]\s*", "", issue["title"], flags=re.I).strip(),
        )
        rebuild_backlog()
        print(by_id.relative_to(ROOT))
        return 0

    path = create_entry_from_issue(
        number,
        issue["title"],
        issue["body"] or "",
        issue["label_names"],
        bug_id=bug_id,
    )
    print(path.relative_to(ROOT))
    print(f"GitHub: {issue['url']}")
    return 0


def _ensure_local_entry(issue_num: str) -> Path:
    path = find_entry_by_github_issue(issue_num)
    if path:
        return path
    issue = _fetch_issue(issue_num)
    return create_entry_from_issue(
        issue_num,
        issue["title"],
        issue["body"] or "",
        issue["label_names"],
        bug_id=parse_bug_id_from_title(issue["title"]),
    )


def cmd_start(args: argparse.Namespace) -> int:
    issue_num, path = _resolve_ref(args.ref, require_github=False)
    if path is None:
        path = _ensure_local_entry(issue_num)

    update_meta(path, status="investigating")
    rebuild_backlog()

    agent = args.agent or "Cursor agent"
    print(f"Status → investigating ({path.name})")
    if not issue_num:
        issue_num = ensure_github_issue(path)
    if not issue_num:
        print("No GitHub issue linked — gh unavailable or promote failed.")
        return 0
    comment = f"🔧 **Investigating** — {agent} started work on this issue."
    if not args.dry_run:
        _run_gh(["issue", "comment", issue_num, "--repo", REPO, "--body", comment])
    print(f"https://github.com/{REPO}/issues/{issue_num}")
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    issue_num, path = _resolve_ref(args.ref, require_github=False)
    if path is None:
        print("Import issue first: python3 Scripts/bugs/bug_github.py import", issue_num, file=sys.stderr)
        sys.exit(1)

    fields = {"status": "fixed"}
    if args.fixed_in:
        fields["fixed_in"] = args.fixed_in
    meta = update_meta(path, **fields)
    rebuild_backlog()

    summary = args.summary or "Fixed — see linked commit/PR and local entry for details."
    tests = args.tests or "./Scripts/run_tcg_tests.sh"
    body = "\n".join(
        [
            "✅ **Resolved**",
            "",
            summary,
            "",
            f"**Local entry:** `Docs/bugs/entries/{path.name}`",
            f"**Tests run:** `{tests}`",
        ]
    )
    if args.fixed_in:
        body += f"\n**Fix reference:** {args.fixed_in}"

    if issue_num and not args.dry_run:
        _run_gh(["issue", "comment", issue_num, "--repo", REPO, "--body", body])
        if not args.leave_open:
            _run_gh(["issue", "close", issue_num, "--repo", REPO, "--comment", "Closing as fixed."])
    print(f"Status → fixed ({meta.get('id', path.stem)})")
    if issue_num and not args.leave_open:
        print(f"Closed GitHub issue #{issue_num}")
    elif not issue_num:
        print("No GitHub issue linked — local entry updated only.")
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    issue_num, path = _resolve_ref(args.ref, require_github=False)
    if path is None and issue_num:
        path = _ensure_local_entry(issue_num)
    if path is None:
        print("No bug entry found.", file=sys.stderr)
        sys.exit(1)
    meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    log_path = LOGS_DIR / f"{meta.get('id', 'BUG')}-console.log"

    print("# Bug fix context")
    print()
    if issue_num:
        print(f"- **GitHub:** https://github.com/{REPO}/issues/{issue_num}")
    else:
        print("- **GitHub:** _(not linked — run `report_bug.py status <id> open` or `import`)_")
    print(f"- **Local entry:** `{path.relative_to(ROOT)}`")
    print(f"- **ID:** {meta.get('id', '?')}")
    print(f"- **Area:** {meta.get('area', '?')} → prioritize `Scripts/{_area_hint(meta.get('area', ''))}`")
    print(f"- **Severity:** {meta.get('severity', '?')}")
    print()
    print("## Agent workflow")
    print()
    print("1. Read the local entry and console log.")
    print("2. Reproduce with TCG harness or minimal fixture if possible.")
    print("3. Implement the smallest correct fix.")
    print(f"4. Run tests: `{args.tests}`")
    resolve_ref = issue_num or meta.get("id", args.ref)
    print(f"5. Close loop: `python3 Scripts/bugs/bug_github.py resolve {resolve_ref} --summary \"...\" --fixed-in \"PR #N\"`")
    print()
    print("## Entry body")
    print()
    print(body[:4000])
    if log_path.exists():
        print()
        print(f"## Console log (`{log_path.relative_to(ROOT)}`)")
        print()
        print("```")
        print(log_path.read_text(encoding="utf-8")[:8000])
        print("```")
    return 0


def _area_hint(area: str) -> str:
    return {
        "engine": "Game/",
        "ui": "UI/",
        "ai": "AI/ and ai_agent/",
        "cards": "Data/Cards/",
        "tests": "Tests/Tcg/",
        "docs": "Docs/Game Rules/",
    }.get(area, "Game/")


def main() -> int:
    parser = argparse.ArgumentParser(description="GitHub bug backlog sync")
    sub = parser.add_subparsers(dest="command", required=True)

    p_import = sub.add_parser("import", help="Import GitHub issue to local backlog")
    p_import.add_argument("issue", type=int, help="GitHub issue number")
    p_import.add_argument("--force", action="store_true", help="Re-import over existing link")
    p_import.set_defaults(func=cmd_import)

    p_start = sub.add_parser("start", help="Mark investigating and comment on GitHub")
    p_start.add_argument("ref", help="Issue # or BUG-NNN")
    p_start.add_argument("--agent", default="Cursor agent")
    p_start.add_argument("--dry-run", action="store_true")
    p_start.set_defaults(func=cmd_start)

    p_resolve = sub.add_parser("resolve", help="Mark fixed and close GitHub issue")
    p_resolve.add_argument("ref", help="Issue # or BUG-NNN")
    p_resolve.add_argument("--summary", "-s", help="Resolution summary for GitHub comment")
    p_resolve.add_argument("--fixed-in", help="Commit, PR, or branch reference")
    p_resolve.add_argument("--tests", default="./Scripts/run_tcg_tests.sh")
    p_resolve.add_argument("--leave-open", action="store_true", help="Comment only, do not close issue")
    p_resolve.add_argument("--dry-run", action="store_true")
    p_resolve.set_defaults(func=cmd_resolve)

    p_ctx = sub.add_parser("context", help="Print agent briefing")
    p_ctx.add_argument("ref", help="Issue # or BUG-NNN")
    p_ctx.add_argument("--tests", default="./Scripts/run_tcg_tests.sh")
    p_ctx.set_defaults(func=cmd_context)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
