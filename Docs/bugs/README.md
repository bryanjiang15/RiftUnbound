# Bug Backlog

Track playtest bugs locally first, then promote to GitHub Issues when ready to fix.

## Quick start

```bash
# Interactive — prompts for title, steps, paste console log at the end
python3 Scripts/bugs/report_bug.py new

# Non-interactive with a saved log file
python3 Scripts/bugs/report_bug.py new \
  --title "Flame Chompers does not prompt on discard" \
  --severity high --area engine \
  --cards flame-chompers \
  --commands "play chemtech-enforcer" \
  --log-file /path/to/console.txt

# List all bugs
python3 Scripts/bugs/report_bug.py list

# Mark status
python3 Scripts/bugs/report_bug.py status BUG-003 investigating

# Promote to GitHub (requires `gh` CLI + auth)
python3 Scripts/bugs/promote_to_github.py BUG-003
```

## Where things live

| Path | Purpose |
|------|---------|
| `Docs/bugs/backlog.md` | Summary table (auto-updated by scripts) |
| `Docs/bugs/entries/BUG-NNN-*.md` | One file per bug — full repro, expected/actual |
| `Docs/bugs/logs/BUG-NNN-console.log` | Raw console / game log paste |
| `.github/ISSUE_TEMPLATE/bug_report.yml` | GitHub web form (same fields) |

## Workflow

1. **During playtest** — copy the Godot Output / command console log.
2. **File locally** — `report_bug.py new` (fast, works offline).
3. **Triage** — update `status` in the entry or via `report_bug.py status`.
4. **Fix & close** — set `status: fixed` and optional `fixed_in: <commit or PR>`.
5. **Optional GitHub** — `promote_to_github.py BUG-NNN` creates a linked issue.

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
