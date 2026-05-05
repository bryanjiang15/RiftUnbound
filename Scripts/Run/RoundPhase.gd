extends Object
class_name RoundPhase

enum Phase {
	PLANNING,
	COMBAT_RESOLVE,
	ROUND_RESULT,
}

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
