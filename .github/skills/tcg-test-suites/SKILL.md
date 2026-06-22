---
name: tcg-test-suites
description: >-
  Run RiftUnbound TCG test suites with Godot headless mode. Use when asked to
  run tests, run a specific suite (RuleResources, RuleCombat, etc.), list
  available suites, or verify engine/card-rule changes.
---

# TCG Test Suites

Run the repository's Godot-based TCG tests in a consistent way on Windows.

## When to Use

- User asks to run tests
- User asks to run one or more named TCG suites
- You need quick validation after gameplay/rules changes

## Commands

1. List available suites:
   `powershell -ExecutionPolicy Bypass -File ./.github/skills/tcg-test-suites/scripts/run-tcg-tests.ps1 -List`
2. Run all suites:
   `powershell -ExecutionPolicy Bypass -File ./.github/skills/tcg-test-suites/scripts/run-tcg-tests.ps1`
3. Run specific suites:
   `powershell -ExecutionPolicy Bypass -File ./.github/skills/tcg-test-suites/scripts/run-tcg-tests.ps1 RuleResources RuleCombat`

## Notes

- The script auto-detects Godot from `GODOT` env var, local user install, or PATH.
- Test runner: `res://Scripts/Tests/Tcg/TcgTestRunner.gd`
