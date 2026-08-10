Worked investigation traces (follow the pattern, not the exact cards):

Example A — branch in the middle
Scout: play Unit A → move A to battlefield-a → play Unit B → end turn.
Pivot: where Unit A moves; both suffixes pursue immediate scoring.
Test: deepen(line_id=scout-leader, prefix_steps=1) so the engine completes
alternatives after playing Unit A.
Evidence: A-to-b scores the same point but leaves battlefield-a undefended and
spends one fewer card. Compare those facts; use score only if they remain tied.

Example B — failed seed
deepen(line_id=scout) fails at an intermediate choose command.
Correct update: “Hypothesis not tested; the seed representation failed.”
Retry: deepen with prefix_steps before the choose step, or deepen(moves=[...])
with only the strategic actions. Do not say the failed call produced
“no contrary evidence.”

Example C — tiny score gap
Scout score band ~high; alternative in the same band.
Incorrect: “3.93 is higher, so commit scout.”
Correct: classify as a heuristic tie, compare hand size, ready runes, board
control, and response windows, then explain which concrete delta breaks the tie.
