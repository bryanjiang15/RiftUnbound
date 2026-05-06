extends Object
class_name RoundPhase

## Enumeration of the three phases that make up a single run round.
##
##   PLANNING       — player arranges champions on the board.
##   COMBAT_RESOLVE — stub/real combat is evaluated from the locked snapshot.
##   ROUND_RESULT   — damage/healing is applied and the next round begins.

enum Phase {
	PLANNING,
	COMBAT_RESOLVE,
	ROUND_RESULT,
}

## Returns a display-friendly name for `p` (used in HUD labels and debug logs).
static func phase_to_string(p: Phase) -> String:
	match p:
		Phase.PLANNING:
			return "Planning"
		Phase.COMBAT_RESOLVE:
			return "CombatResolve"
		Phase.ROUND_RESULT:
			return "RoundResult"
		_:
			return "Unknown"
