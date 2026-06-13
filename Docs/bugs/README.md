# Bug Backlog

Local entries under `Docs/bugs/` are the detailed spec and log archive. **GitHub Issues are created automatically** when you file or update bugs (requires `gh` auth). Use `--no-github` for offline-only capture.

## Quick start

```bash
# Interactive — creates local entry + GitHub issue
python3 Scripts/bugs/report_bug.py new

# Non-interactive with a saved log file
python3 Scripts/bugs/report_bug.py new \
  --title "Flame Chompers does not prompt on discard" \
  --severity high --area engine \
  --cards flame-chompers \
  --commands "play chemtech-enforcer" \
  --log-file /path/to/console.txt

# Offline: local entry only (no gh)
python3 Scripts/bugs/report_bug.py new --no-github --title "..."

# List all bugs
python3 Scripts/bugs/report_bug.py list

# Mark status (syncs comment/close to GitHub)
python3 Scripts/bugs/report_bug.py status BUG-003 investigating
python3 Scripts/bugs/report_bug.py status BUG-003 fixed --fixed-in "PR #15"

# Re-link or promote an older local-only entry
python3 Scripts/bugs/promote_to_github.py BUG-003

# Sync from GitHub: update status + remove closed bugs from active backlog
python3 Scripts/bugs/bug_github.py sync
python3 Scripts/bugs/bug_github.py sync --dry-run   # preview
```

## Where things live

| Path | Purpose |
|------|---------|
| `Docs/bugs/backlog.md` | Summary table (auto-updated by scripts) |
| `Docs/bugs/entries/BUG-NNN-*.md` | Active bugs — full repro, expected/actual |
| `Docs/bugs/archive/backlog.md` | Closed bugs summary (one table, no per-bug files) |
| `Docs/bugs/logs/BUG-NNN-console.log` | Raw console / game log paste (active bugs only) |
| `.github/ISSUE_TEMPLATE/bug_report.yml` | GitHub web form (same fields) |

## Workflow

1. **During playtest** — copy the Godot Output / command console log.
2. **File** — `report_bug.py new` → local entry + GitHub issue (or `--no-github` offline).
3. **Triage** — `report_bug.py status BUG-NNN investigating` (comments on GitHub).
4. **Fix & close** — `report_bug.py status BUG-NNN fixed --fixed-in "PR #N"` (closes GitHub issue).
5. **Agent fix loop** — `bug_github.py context/start/resolve` for Cursor (same GitHub link).
6. **Prune closed** — `bug_github.py sync` archives bugs whose GitHub issue is closed (or local-only `fixed`/`wontfix`/`duplicate`).

## Sync & archive

GitHub is the source of truth for open/closed. Local `entries/` holds **active** work; closed bugs are recorded in `archive/backlog.md` and their entry/log files are removed.

```bash
# Default: align local status from GitHub, archive closed issues
python3 Scripts/bugs/bug_github.py sync

# Preview without moving files
python3 Scripts/bugs/bug_github.py sync --dry-run

# Update status only — keep fixed entries in entries/
python3 Scripts/bugs/bug_github.py sync --keep-closed
```

**What `sync` does:**

| Step | Behavior |
|------|----------|
| Pull | For each linked entry, fetch GitHub issue state |
| Update | GitHub `CLOSED` + local `open`/`investigating` → local `fixed` |
| Archive | Append row to `archive/backlog.md`, delete entry + log |
| Rebuild | `backlog.md` lists only remaining `entries/` |

Drift warning if local is `fixed` but GitHub is still open — close via `report_bug.py status BUG-NNN fixed` or `bug_github.py resolve`.

## Status values

`open` · `investigating` · `confirmed` · `fixed` · `wontfix` · `duplicate`

## Severity

`critical` — game broken / data loss  
`high` — wrong rules, blocks play  
`medium` — workaround exists  
`low` — cosmetic / minor

## Area tags

`engine` · `ui` · `ai` · `cards` · `tests` · `docs`

## Tips for good reports

- Include **exact commands** you typed (`play get-excited target blazing-scorcher`).
- Note **turn / phase** from the log (`Turn 3 Main Phase`).
- Paste the **full console block** from first wrong line through `[ERROR]` or unexpected result.
- Name **cards involved** by instance id when relevant (`flame-chompers-2`).

## GitHub-only option

Skip local files and file directly:

```bash
gh issue create --template bug_report.yml
```

Or use **Issues → New issue → Bug report** on GitHub.

## Cursor agent: fix a GitHub issue

Use the project skill **fix-github-bug** (`.cursor/skills/fix-github-bug/SKILL.md`) or run manually:

```bash
# 1. Pull issue + print briefing for the agent
python3 Scripts/bugs/bug_github.py context 42

# 2. Mark investigating (comments on GitHub)
python3 Scripts/bugs/bug_github.py start 42

# ... agent implements fix, runs tests ...

# 3. Mark fixed + close GitHub issue
python3 Scripts/bugs/bug_github.py resolve 42 \
  --summary "Root cause and fix in one sentence." \
  --fixed-in "PR #15"
```

| Command | Purpose |
|---------|---------|
| `bug_github.py import <#>` | Create/update local `BUG-NNN` entry from GitHub |
| `bug_github.py context <#>` | Agent briefing (entry + log + workflow) |
| `bug_github.py start <#>` | Status → `investigating`, GitHub comment |
| `bug_github.py resolve <#>` | Status → `fixed`, GitHub comment + close |
| `bug_github.py sync` | Pull GitHub state, archive closed bugs |
| `promote_to_github.py BUG-NNN` | Re-promote older local-only entries |
| `report_bug.py new` | Local + GitHub (default) |
| `report_bug.py status` | Local + GitHub comment/close (default) |

Refs accept issue numbers (`42`) or local ids (`BUG-002`).

### Example Cursor prompt

> Fix GitHub issue #42 — import it, reproduce, fix, run `./Scripts/run_tcg_tests.sh`, then resolve the issue.

The agent should invoke the skill and run the scripts itself (not just describe them).
