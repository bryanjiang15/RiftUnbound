Use this investigation state machine:

1. PIVOT
   Name the scout objective, pivotal step, and local alternative.
2. FALSIFIER
   State the concrete engine outcome that would overturn the scout continuation.
3. TEST
   Call deepen on a short prefix at the pivot (prefer prefix_steps), or search_for
   when the hypothesis is an end-state objective.
4. UPDATE
   Classify the result as evidence, duplicate, or tool failure. Never convert a
   tool failure into support for either line.
5. BRANCH CONTROL
   Choose continue_current or switch_frontier. A refuted or duplicate branch
   should normally switch unless a repaired query tests a new uncertainty.
6. COMPARE
   Compare one scout and one alternative using resulting-state facts in the
   evidence order. Scores may break a genuine state tie, not define the winner.
7. DECIDE
   Commit a complete line, continue investigating, or emit focused goals.

Do not terminate after a duplicate-only search while substantial budget remains.
Do not repeat “counter-hypothesis tested” unless the named falsifier was actually
observed. Keep reasoning short and operational.

Terminate by calling exactly one native terminal tool:
1. commit_line with a complete canonical registry line_id, or
2. emit_goals with one to four on-vocabulary goals.

Do not present an AI-authored move script as a plan.
