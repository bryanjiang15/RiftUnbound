---
id: BUG-001
title: Power costs did not recycle channeled runes
status: fixed
severity: high
area: engine
reported: 2026-06-06
fixed_in: try_pay_cost wired through all cost paths
cards: flame-chompers, blazing-scorcher
commands: choose yes (Flame Chompers on_discard); play blazing-scorcher accelerate
github_issue:
---

## Summary

Paying domain Power (ability costs, optional triggers, Accelerate) deducted from the
Rune Pool without recycling a channeled rune into the rune deck. Only `_complete_play`
called `_auto_pay_runes`; other paths used `CostCalculator.pay_cost()` directly.

## Reproduction

1. Channel runes but do not manually `recycle rune-N`.
2. Trigger a power cost — e.g. discard Flame Chompers and choose `yes`, or play with Accelerate needing Fury power.
3. Observe pool changes but channeled runes remain on board.

## Expected

Auto-pay recycles matching runes (exhausted first), moves them to bottom of rune deck, adds Power to pool, then spends it.

## Actual

Pool deducted (or went negative); channeled rune count unchanged; no `> [Auto] Rune recycled` log line.

## Fix

`GameController.try_pay_cost()` centralizes auto-pay; used from triggers, chain, activate, react, and optional prompts.

## Console log

See `logs/BUG-001-console.log` (example — not captured at time of report).
