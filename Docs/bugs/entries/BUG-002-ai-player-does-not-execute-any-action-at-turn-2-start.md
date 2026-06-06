---
id: BUG-002
title: AI player does not execute any action at turn 2 start
status: open
severity: medium
area: ai
reported: 2026-06-06
cards: scrapheap, chemtech-enforcer
commands:
github_issue:
---

## Summary

When the ai's turn start, the ai does not execute any actions, it does not seem to recieve a request and the game stalls

## Reproduction

p1 plays chemtech enforcer on turn 1
p1 discard scrapheap due to chemtech enforcer effect
p1 draw and end turn
p2 start turn

## Expected

p2 start turn and ai begins playing and executing commands

## Actual

p2 ai does nothing and the game stalls

## Console log

See `logs/BUG-002-console.log`
