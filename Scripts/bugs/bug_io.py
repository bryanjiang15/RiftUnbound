"""Shared helpers for Docs/bugs/ entries and GitHub sync."""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENTRIES_DIR = ROOT / "Docs" / "bugs" / "entries"
LOGS_DIR = ROOT / "Docs" / "bugs" / "logs"
ARCHIVE_DIR = ROOT / "Docs" / "bugs" / "archive"
ARCHIVE_BACKLOG = ARCHIVE_DIR / "backlog.md"
BACKLOG = ROOT / "Docs" / "bugs" / "backlog.md"
REPO = "bryanjiang15/RiftUnbound"

STATUSES = ("open", "investigating", "confirmed", "fixed", "wontfix", "duplicate")
TERMINAL_STATUSES = ("fixed", "wontfix", "duplicate")
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


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    meta: dict[str, str] = {}
    for line in text[3:end].strip().splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            meta[key.strip()] = val.strip()
    body = text[end + 4 :].lstrip()
    return meta, body


def render_entry(meta: dict[str, str], body: str) -> str:
    lines = ["---"]
    order = [
        "id", "title", "status", "severity", "area", "reported",
        "fixed_in", "cards", "commands", "github_issue",
    ]
    seen: set[str] = set()
    for key in order:
        if key in meta:
            lines.append(f"{key}: {meta[key]}")
            seen.add(key)
    for key, val in meta.items():
        if key not in seen:
            lines.append(f"{key}: {val}")
    lines.extend(["---", "", body.rstrip(), ""])
    return "\n".join(lines)


def find_entry_by_id(bug_id: str) -> Path | None:
    bug_id = bug_id.upper()
    matches = list(ENTRIES_DIR.glob(f"{bug_id}*.md"))
    return matches[0] if matches else None


def find_entry_by_github_issue(issue_number: str) -> Path | None:
    for path in ENTRIES_DIR.glob("BUG-*.md"):
        meta, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        if meta.get("github_issue", "") == str(issue_number):
            return path
    return None


def load_entries() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(ENTRIES_DIR.glob("BUG-*.md")):
        meta, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        meta["_path"] = str(path)
        meta["_file"] = path.name
        if "id" not in meta:
            parts = path.stem.split("-", 2)
            meta["id"] = f"{parts[0]}-{parts[1]}" if len(parts) >= 2 else path.stem
        rows.append(meta)
    return rows


def rebuild_backlog() -> None:
    entries = load_entries()
    counts = {s: 0 for s in STATUSES}
    lines = [
        "# Bug Backlog Index",
        "",
        "> Auto-updated by bug scripts. Edit entries in `entries/`, not this table.",
        "",
        "| ID | Status | Sev | Area | Title | Reported | GitHub |",
        "|----|--------|-----|------|-------|----------|--------|",
    ]
    for e in entries:
        status = e.get("status", "open")
        counts[status] = counts.get(status, 0) + 1
        gh = f"#{e['github_issue']}" if e.get("github_issue") else "—"
        link = f"[{e['id']}](entries/{e['_file']})"
        lines.append(
            f"| {link} | {status} | {e.get('severity', '?')} | {e.get('area', '?')} "
            f"| {e.get('title', e['_file'])} | {e.get('reported', '?')} | {gh} |"
        )
    if not entries:
        lines.append("| — | — | — | — | *No bugs filed yet* | — | — |")
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


def parse_archive_backlog() -> list[dict[str, str]]:
    if not ARCHIVE_BACKLOG.exists():
        return []
    text = ARCHIVE_BACKLOG.read_text(encoding="utf-8")
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        if not line.startswith("| BUG-"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 7:
            continue
        gh = cells[6].lstrip("#") if cells[6] not in ("—", "-", "") else ""
        fixed_in = cells[7] if len(cells) > 7 and cells[7] not in ("—", "-") else ""
        rows.append(
            {
                "id": cells[0],
                "status": cells[1],
                "severity": cells[2],
                "area": cells[3],
                "title": cells[4],
                "reported": cells[5],
                "github_issue": gh,
                "fixed_in": fixed_in,
            }
        )
    return rows


def rebuild_archive_backlog(rows: list[dict[str, str]]) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    counts = {s: 0 for s in TERMINAL_STATUSES}
    lines = [
        "# Archived Bugs",
        "",
        "> Closed bugs removed from active backlog by `bug_github.py sync`.",
        "",
        "| ID | Status | Sev | Area | Title | Reported | GitHub | Fixed in |",
        "|----|--------|-----|------|-------|----------|--------|----------|",
    ]
    for e in sorted(rows, key=lambda r: r.get("id", "")):
        status = e.get("status", "fixed")
        if status in counts:
            counts[status] = counts.get(status, 0) + 1
        gh = f"#{e['github_issue']}" if e.get("github_issue") else "—"
        fixed = e.get("fixed_in") or "—"
        lines.append(
            f"| {e['id']} | {status} | {e.get('severity', '?')} | {e.get('area', '?')} "
            f"| {e.get('title', '?')} | {e.get('reported', '?')} | {gh} | {fixed} |"
        )
    if not rows:
        lines.append("| — | — | — | — | *No archived bugs yet* | — | — | — |")
    lines.extend(
        [
            "",
            "**Counts:** "
            + f"{counts.get('fixed', 0)} fixed · "
            + f"{counts.get('wontfix', 0)} wontfix · "
            + f"{counts.get('duplicate', 0)} duplicate",
            "",
        ]
    )
    ARCHIVE_BACKLOG.write_text("\n".join(lines), encoding="utf-8")


def migrate_legacy_archive() -> int:
    """Import old archive/entries/*.md into archive/backlog.md, then delete legacy files."""
    legacy_dir = ARCHIVE_DIR / "entries"
    if not legacy_dir.is_dir():
        return 0

    rows = parse_archive_backlog()
    known = {r["id"] for r in rows}
    migrated = 0

    for path in sorted(legacy_dir.glob("BUG-*.md")):
        meta, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        bug_id = meta.get("id", "")
        if not bug_id:
            parts = path.stem.split("-", 2)
            bug_id = f"{parts[0]}-{parts[1]}" if len(parts) >= 2 else path.stem
            meta["id"] = bug_id
        if bug_id not in known:
            rows.append(meta)
            known.add(bug_id)
            migrated += 1
        path.unlink()

    legacy_logs = ARCHIVE_DIR / "logs"
    if legacy_logs.is_dir():
        for log in legacy_logs.glob("*.log"):
            log.unlink()
        try:
            legacy_logs.rmdir()
        except OSError:
            pass
    try:
        legacy_dir.rmdir()
    except OSError:
        pass

    if migrated:
        rebuild_archive_backlog(rows)
    return migrated


def update_meta(path: Path, **fields: str) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)
    meta.update(fields)
    path.write_text(render_entry(meta, body), encoding="utf-8")
    return meta


def extract_section(body: str, heading: str) -> str:
    pattern = rf"^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)"
    m = re.search(pattern, body, re.MULTILINE | re.DOTALL)
    return m.group(1).strip() if m else ""


def parse_issue_labels(labels: list[str]) -> tuple[str, str]:
    severity = "medium"
    area = "engine"
    for label in labels:
        if label.startswith("severity:"):
            severity = label.split(":", 1)[1]
        elif label in AREAS:
            area = label
        elif label == "bug":
            continue
    if severity not in SEVERITIES:
        severity = "medium"
    if area not in AREAS:
        area = "engine"
    return severity, area


def parse_bug_id_from_title(title: str) -> str | None:
    m = re.match(r"\[(BUG-\d+)\]", title, re.IGNORECASE)
    return m.group(1).upper() if m else None


def create_entry_from_issue(
    issue_number: str,
    title: str,
    body: str,
    labels: list[str],
    bug_id: str | None = None,
) -> Path:
    ENTRIES_DIR.mkdir(parents=True, exist_ok=True)
    clean_title = re.sub(r"^\[BUG-\d+\]\s*", "", title, flags=re.IGNORECASE).strip()
    bug_id = bug_id or next_bug_id()
    severity, area = parse_issue_labels(labels)

    summary = ""
    repro = ""
    expected = ""
    actual = ""
    console = ""
    cards = ""
    commands = ""
    local_id = ""

    for line in body.splitlines():
        if line.startswith("**Cards:**"):
            cards = line.replace("**Cards:**", "").strip()
        elif line.startswith("**Commands:**"):
            commands = line.replace("**Commands:**", "").strip().strip("`")
        elif "Docs/bugs/entries/" in line:
            m = re.search(r"BUG-\d+", line)
            if m:
                local_id = m.group(0)

    if local_id:
        bug_id = local_id

    if "## Summary" in body or "## Reproduction" in body:
        summary = extract_section(body, "Summary") or clean_title
        repro = extract_section(body, "Reproduction")
        expected = extract_section(body, "Expected")
        actual = extract_section(body, "Actual")
        console_block = extract_section(body, "Console log")
        if console_block and not console_block.startswith("_No log"):
            console = console_block
    else:
        summary = clean_title
        repro = body.strip()[:2000]

    slug = slugify(clean_title)
    path = ENTRIES_DIR / f"{bug_id}-{slug}.md"
    if path.exists() and bug_id != local_id:
        path = ENTRIES_DIR / f"{bug_id}-{slug}-gh{issue_number}.md"

    meta = {
        "id": bug_id,
        "title": clean_title,
        "status": "open",
        "severity": severity,
        "area": area,
        "reported": date.today().isoformat(),
        "cards": cards,
        "commands": commands,
        "github_issue": issue_number,
    }
    body_text = "\n".join(
        [
            "## Summary",
            "",
            summary or "_Imported from GitHub._",
            "",
            "## Reproduction",
            "",
            repro or "1. _See GitHub issue body_",
            "",
            "## Expected",
            "",
            expected or "_Per game rules._",
            "",
            "## Actual",
            "",
            actual or "_See GitHub issue._",
            "",
            "## Console log",
            "",
            f"See `logs/{bug_id}-console.log`" if console else "_Imported from GitHub — see issue for log._",
            "",
        ]
    )
    path.write_text(render_entry(meta, body_text), encoding="utf-8")

    if console:
        log_path = LOGS_DIR / f"{bug_id}-console.log"
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        log_path.write_text(console + "\n", encoding="utf-8")

    rebuild_backlog()
    return path


def run_gh(args: list[str], *, check: bool = True) -> str:
    try:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            check=check,
            cwd=ROOT,
        )
        return result.stdout.strip()
    except FileNotFoundError:
        print("gh CLI not found. Install: https://cli.github.com/", file=sys.stderr)
        raise
    except subprocess.CalledProcessError as e:
        print(e.stderr or e.stdout, file=sys.stderr)
        raise


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


def promote_entry(entry_path: Path, *, dry_run: bool = False) -> tuple[str, str] | None:
    """Create a GitHub issue from a local entry. Returns (issue_number, url), or None on failure."""
    meta, body = parse_frontmatter(entry_path.read_text(encoding="utf-8"))
    bug_id = meta.get("id", "BUG")
    if meta.get("github_issue"):
        issue = meta["github_issue"]
        return issue, f"https://github.com/{REPO}/issues/{issue}"

    title = meta.get("title", entry_path.stem)
    issue_body = build_issue_body(meta, body)
    labels = ["bug", meta.get("area", "engine"), f"severity:{meta.get('severity', 'medium')}"]

    if dry_run:
        print(f"Title: [{bug_id}] {title}")
        print(f"Labels: {labels}")
        print("---")
        print(issue_body)
        return None

    cmd = [
        "issue",
        "create",
        "--repo",
        REPO,
        "--title",
        f"[{bug_id}] {title}",
        "--body",
        issue_body,
    ]
    for label in labels:
        cmd.extend(["--label", label])

    try:
        url = run_gh(cmd)
    except (FileNotFoundError, subprocess.CalledProcessError):
        print(
            "\nTip: run `gh auth login` and ensure labels exist (bug, engine, ai, …, severity:medium). "
            "Use promote_to_github.py --dry-run to preview.",
            file=sys.stderr,
        )
        return None

    m = re.search(r"/issues/(\d+)", url)
    if not m:
        print(f"Could not parse issue number from: {url}", file=sys.stderr)
        return None

    issue_number = m.group(1)
    update_meta(entry_path, github_issue=issue_number)
    rebuild_backlog()
    return issue_number, url


def ensure_github_issue(entry_path: Path, *, dry_run: bool = False) -> str | None:
    """Return linked issue number, promoting the entry first if needed."""
    meta, _ = parse_frontmatter(entry_path.read_text(encoding="utf-8"))
    if meta.get("github_issue"):
        return meta["github_issue"]
    result = promote_entry(entry_path, dry_run=dry_run)
    return result[0] if result else None


def sync_status_to_github(
    issue_number: str,
    status: str,
    *,
    bug_id: str = "",
    entry_name: str = "",
    fixed_in: str = "",
    dry_run: bool = False,
) -> None:
    """Mirror a local status change to the GitHub issue (comment; close when terminal)."""
    if dry_run:
        print(f"[dry-run] GitHub #{issue_number} → {status}")
        return

    comments = {
        "investigating": "🔧 **Investigating** — work started on this bug.",
        "confirmed": "✓ **Confirmed** — reproduced and acknowledged.",
        "fixed": "✅ **Resolved** — marked fixed in local backlog.",
        "wontfix": "🚫 **Won't fix** — closed without a code change.",
        "duplicate": "🔗 **Duplicate** — closing as duplicate.",
        "open": "📂 **Reopened** — status set back to open in local backlog.",
    }
    body = comments.get(status, f"**Status:** {status}")
    if entry_name:
        body += f"\n\n**Local entry:** `Docs/bugs/entries/{entry_name}`"
    if fixed_in:
        body += f"\n**Fix reference:** {fixed_in}"

    run_gh(["issue", "comment", issue_number, "--repo", REPO, "--body", body])

    if status == "open":
        run_gh(["issue", "reopen", issue_number, "--repo", REPO])
    elif status in ("fixed", "wontfix", "duplicate"):
        close_msg = {
            "fixed": "Closing as fixed.",
            "wontfix": "Closing — won't fix.",
            "duplicate": "Closing as duplicate.",
        }[status]
        run_gh(["issue", "close", issue_number, "--repo", REPO, "--comment", close_msg])


def fetch_issue_state(issue_number: str) -> dict:
    import json

    raw = run_gh(
        [
            "issue",
            "view",
            issue_number,
            "--repo",
            REPO,
            "--json",
            "number,title,state,labels,body",
        ]
    )
    data = json.loads(raw)
    data["label_names"] = [lb["name"] for lb in data.get("labels", [])]
    return data


def archive_entry(entry_path: Path, *, dry_run: bool = False) -> None:
    meta, _ = parse_frontmatter(entry_path.read_text(encoding="utf-8"))
    bug_id = meta.get("id", "")
    if not bug_id:
        parts = entry_path.stem.split("-", 2)
        bug_id = f"{parts[0]}-{parts[1]}" if len(parts) >= 2 else entry_path.stem
        meta["id"] = bug_id

    if dry_run:
        print(f"[dry-run] archive {bug_id} → archive/backlog.md")
        return

    rows = parse_archive_backlog()
    rows = [r for r in rows if r.get("id") != bug_id]
    rows.append(meta)
    rebuild_archive_backlog(rows)

    entry_path.unlink()
    log_path = LOGS_DIR / f"{bug_id}-console.log"
    if log_path.exists():
        log_path.unlink()


def sync_backlog(*, prune_closed: bool = True, dry_run: bool = False) -> dict[str, int]:
    """
    Pull GitHub issue state for linked entries, align local status, and archive closed bugs.

    Returns counts: updated, archived, drift, errors.
    """
    counts = {"updated": 0, "archived": 0, "drift": 0, "errors": 0}
    migrated = migrate_legacy_archive()
    if migrated:
        print(f"Migrated {migrated} legacy archive entries → archive/backlog.md")
    to_archive: list[Path] = []

    for entry_path in sorted(ENTRIES_DIR.glob("BUG-*.md")):
        meta, _ = parse_frontmatter(entry_path.read_text(encoding="utf-8"))
        bug_id = meta.get("id", entry_path.stem)
        status = meta.get("status", "open")
        issue_num = meta.get("github_issue", "")
        github_closed = False

        if issue_num:
            try:
                issue = fetch_issue_state(issue_num)
            except Exception:
                print(f"{bug_id}: could not fetch GitHub #{issue_num}", file=sys.stderr)
                counts["errors"] += 1
                continue

            github_closed = issue.get("state") == "CLOSED"
            if github_closed and status in ("open", "investigating", "confirmed"):
                if dry_run:
                    print(f"[dry-run] {bug_id}: GitHub #{issue_num} closed → status fixed")
                else:
                    update_meta(entry_path, status="fixed")
                counts["updated"] += 1
                status = "fixed"
            elif not github_closed and status in TERMINAL_STATUSES:
                print(
                    f"{bug_id}: local status is {status} but GitHub #{issue_num} is still open",
                    file=sys.stderr,
                )
                counts["drift"] += 1
                continue

        should_archive = prune_closed and (
            github_closed or (not issue_num and status in TERMINAL_STATUSES)
        )
        if should_archive:
            to_archive.append(entry_path)

    for entry_path in to_archive:
        archive_entry(entry_path, dry_run=dry_run)
        counts["archived"] += 1

    if not dry_run:
        rebuild_backlog()
    return counts
