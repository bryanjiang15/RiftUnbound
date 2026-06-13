---
id: BUG-004
title: Recycle runes for power does not generate energy
status: fixed
severity: high
area: ui
reported: 2026-06-12
fixed_in: PR #10
cards: 
commands: 
github_issue: 7
---

## Summary

When ai/user tries to play a card that has a power cost, it will try to pay the power first without gaining energy form the recycled rune

## Reproduction

player has four runes
play jinx-demolitionist

## Expected

jinx-demolitionist plays

## Actual

jinx-demolitionist does not play, 1 rune is recycled and three rune tapped

## Console log

See `logs/BUG-004-console.log`
