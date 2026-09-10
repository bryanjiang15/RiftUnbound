Investigate this turn.

Before the first tool call, determine:
- scout objective
- pivot step and why it matters
- local alternative suffix
- overturn condition

Prefer a local fork of the scout plan over an unrelated card or objective.
Scout lines are cluster representatives: similar first actions are collapsed
into one line (see cluster_size). If cluster_size > 1, deepen at
cluster_prefix_steps to expand that opener's suffixes. If a legal first
action (including `use` on a ready legend) is absent from every cluster_key,
test it with deepen(moves=[that command]).
If a tool fails, repair the query; do not treat the failure as negative evidence.
Before terminating, compare concrete resulting-state deltas. If the alternatives
are materially tied, preserve flexibility or investigate one more pivot rather
than choosing by a tiny score difference.

The scout baseline is already in this message; do not spend a call rereading it.
Test with search_for or deepen, then call commit_line or emit_goals.
