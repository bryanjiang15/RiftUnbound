Convert the preceding recommendation into one raw JSON object and nothing else.

For a direct line:
{"schema_version":"1.0","kind":"line","confidence":"commit","moves":["exact command 1","exact command 2"],"chosen_line_id":"line-id-or-null","goal_set":null,"rationale":"brief evidence"}

Use only an exact move sequence observed in search_turn, search_for, deepen, or
confirmed by live simulation. If using chosen_line_id, copy its exact moves.

For a search handoff:
{"schema_version":"1.0","kind":"goals","confidence":"goals","moves":null,"chosen_line_id":null,"goal_set":{"schema_version":"1.0","turn":0,"rationale":"brief strategy","goals":[]},"rationale":"brief evidence"}

The nested GoalSet must use only goals recommended in the think phase and only
the supplied goal vocabulary. Prefer the goals form whenever a line was not
engine-confirmed, is contested and uncertain, or still needs tactical search.
