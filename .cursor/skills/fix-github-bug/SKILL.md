---
name: fix-github-bug
description: >-
  Fix a Riftbound bug from a GitHub issue: import to local backlog, reproduce,
  implement fix, run TCG tests, resolve and close the GitHub issue. Use when
  the user says fix issue #N, work on a GitHub bug, or resolve BUG-NNN.
---

# Fix GitHub Bug

End-to-end workflow for bugs filed on GitHub (or linked local `BUG-NNN` entries).

## Prerequisites

- `gh` CLI installed and authenticated: `gh auth login`
- Godot at `/Applications/Godot.app` or `GODOT` env var (for tests)

## Workflow (follow in order)

### 1. Load context

```bash
python3 Scripts/bugs/bug_github.py context <issue#>
# or: python3 Scripts/bugs/bug_github.py context BUG-002
```

Read the printed entry path, area hint, and console log. Open:

- `Docs/bugs/entries/BUG-NNN-*.md`
- `Docs/bugs/logs/BUG-NNN-console.log` (if present)
- `Docs/Game Rules/riftbound-implementation-rules.md` when rules are unclear

### 2. Mark work started

```bash
python3 Scripts/bugs/bug_github.py start <issue#>
```

Sets local status `investigating` and comments on the GitHub issue.

### 3. Reproduce and fix

- **Engine bugs** → `Scripts/Game/`, use `try_pay_cost()` for costs, `begin_discard()` for discards
- **AI bugs** → `Scripts/AI/`, `ai_agent/`
- **Card bugs** → `Data/Cards/*.json` + `AbilityResolver.gd`
- Add or extend a test in `Scripts/Tests/Tcg/suites/` when the bug is regressable

Reproduce with harness when possible:

```bash
./Scripts/run_tcg_tests.sh CardScenario   # one suite
./Scripts/run_tcg_tests.sh                # full suite before resolve
```

### 4. Verify

Run the narrowest test suite that covers the fix, then full suite if the change touches core engine (`GameController`, `ChainProcessor`, `TriggerDispatcher`, `CostCalculator`).

### 5. Resolve on GitHub

After tests pass:

```bash
python3 Scripts/bugs/bug_github.py resolve <issue#> \
  --summary "One sentence: root cause and what changed." \
  --fixed-in "PR #12 or commit abc1234"
```

This sets local status `fixed`, comments on GitHub, and closes the issue.

Use `--leave-open` if the user wants the issue kept open until a PR merges.

### 6. Optional: create PR

If the user asks for a PR, link the issue:

```bash
gh pr create --title "Fix: <title>" --body "Fixes #<issue#>. ..."
```

## Import-only (issue exists on GitHub, not locally)

```bash
python3 Scripts/bugs/bug_github.py import 42
```

New bugs filed via `report_bug.py new` create both local entry and GitHub issue automatically.
Use `promote_to_github.py BUG-NNN` only for older local-only entries.

## Cursor chat prompts

User can say:

- `Fix GitHub issue #42`
- `Work on BUG-002 from the bug backlog`
- `https://github.com/bryanjiang15/RiftUnbound/issues/42 — investigate and fix`

Agent should run `context` → `start` → fix → tests → `resolve` without skipping steps.

## Do not

- Close GitHub issues without running relevant tests
- Edit `Docs/bugs/backlog.md` by hand (scripts regenerate it)
- Call `CostCalculator.pay_cost()` directly for player-facing costs (use `try_pay_cost`)
