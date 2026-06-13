---
id: BUG-003
title: Combat damaging and resolution does not work
status: fixed
severity: high
area: engine
reported: 2026-06-06
fixed_in: CombatProcessor.gd, CardInstance.gd, CleanupProcessor.gd
cards: 
commands: 
github_issue: 5
---

## Summary

Units are not killed in combat when they should be

## Reproduction

Chemtech enforcer holding in battlefield A
p2 move chemtech enforcer to battlefield A with assualt 2 so 4 power
p2 has 4M and p1 has 2M

## Expected

p1's chemtech enforcer dies and go into the trash and p2 conquer battlefield a

## Actual

combat does not kill either unit and p2's chemtech enforcer move back to base

## Console log

See `logs/BUG-003-console.log`
