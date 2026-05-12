extends RefCounted
class_name CombatResult

## Return value of CombatResolver.resolve().
##
## Carried through CombatOutcome into RunController so RunRoundDamage and
## CombatBoardView both have access to the full event log and survivor counts.

var player_won: bool = false
var player_survivors: int = 0
var opponent_survivors: int = 0
## Ordered list of every action that occurred during combat.
var events: Array[CombatEvent] = []
## True if the combat terminated due to the tick limit rather than elimination.
var timed_out: bool = false
