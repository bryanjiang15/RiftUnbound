---
id: BUG-005
title: Console text input drops after a command is sent
status: fixed
severity: medium
area: ui
reported: 2026-06-13
fixed_in: PR #11
cards: 
commands: 
github_issue: 8
---

## Summary

After user typed a prompt in the console, the user must click the console input box again in order to type in the console

## Reproduction

Type a command in the console on game start
Type again

## Expected

Second command should appear in console

## Actual

does not input

## Console log

_No log captured — paste into `logs/BUG-005-console.log` later._
