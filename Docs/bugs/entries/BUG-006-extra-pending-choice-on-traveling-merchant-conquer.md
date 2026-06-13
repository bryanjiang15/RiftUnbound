---
id: BUG-006
title: extra pending choice on traveling merchant conquer
status: open
severity: low
area: ai
reported: 2026-06-13
cards: traveling merchant
commands: 
github_issue: 9
---

## Summary

the ai provide an extra choice selection after traveling merchant moved and conquered

## Reproduction

ai player has traveling merchant in base ready
move traveling merchant to battlefield
its choice discard trigger
the showdonw focus passed

## Expected

the ai finishes making choices

## Actual

the ai chooses another card for a pending choice

## Console log

See `logs/BUG-006-console.log`
