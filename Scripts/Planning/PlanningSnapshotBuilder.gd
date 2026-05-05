extends RefCounted
class_name PlanningSnapshotBuilder

## Builds a PlanningSnapshot header + copied references for combat (Phase D duplicates if mutating).

static func build(board: BoardState, run_state: RunState) -> PlanningSnapshot:
	var snap := PlanningSnapshot.new()
	if run_state != null:
		snap.round_index = run_state.current_round_index
		snap.run_id = run_state.run_id
	snap.player_champions = board.player_champions.duplicate()
	snap.opponent_champions = board.opponent_champions.duplicate()
	snap.deployed_allies = board.deployed_allies.duplicate()
	snap.occupancy = board.occupancy.duplicate()
	return snap
