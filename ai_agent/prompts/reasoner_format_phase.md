Fail-safe only: convert the preceding recommendation into one raw JSON object.
Native commit_line / emit_goals calls should normally terminate the turn.

For a direct line:
{"schema_version":"1.0","kind":"line","confidence":"commit","chosen_line_id":"canonical-line-id","rationale":"brief scout-versus-alternative evidence"}

Reference only a canonical id returned by the request-scoped registry. Never
copy moves. Simulation results are not commit sources.

For a search handoff:
{"schema_version":"1.0","kind":"goals","confidence":"goals","goal_set":{"schema_version":"1.0","turn":7,"rationale":"build scoring pressure","goals":[{"id":"pressure-b","kind":"state_target","description":"Control battlefield B","priority":"high","metric":"bf_control_net","metric_key":"battlefield-b","comparator":">=","threshold":1}]},"rationale":"tactics remain open"}

The nested GoalSet must contain 1-4 valid goals from the supplied vocabulary.
The controller replaces its turn with the current turn. Any invalid goal rejects
the whole output. Use goals when no complete registered line is preferred or
tactical search is intentionally left open; contested alone is not disqualifying.
