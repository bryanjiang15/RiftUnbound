# Archived Bugs

> Closed bugs removed from active backlog by `bug_github.py sync`.

| ID | Status | Sev | Area | Title | Reported | GitHub | Fixed in |
|----|--------|-----|------|-------|----------|--------|----------|
| BUG-001 | fixed | high | engine | Power costs did not recycle channeled runes | 2026-06-06 | #1 | RuleResourcesTests (accelerate + flame-chompers on_discard) |
| BUG-002 | fixed | medium | ai | AI player does not execute any action at turn 2 start | 2026-06-06 | #2 | GameController._handle_choose_discard + CardScenarioTests |
| BUG-003 | fixed | high | engine | Combat damaging and resolution does not work | 2026-06-06 | #5 | CombatProcessor.gd, CardInstance.gd, CleanupProcessor.gd |
| BUG-004 | fixed | high | ui | Recycle runes for power does not generate energy | 2026-06-12 | #7 | PR #10 |
| BUG-005 | fixed | medium | ui | Console text input drops after a command is sent | 2026-06-13 | #8 | PR #11 |
| BUG-006 | fixed | low | ai | extra pending choice on traveling merchant conquer | 2026-06-13 | #9 | — |

**Counts:** 6 fixed · 0 wontfix · 0 duplicate
