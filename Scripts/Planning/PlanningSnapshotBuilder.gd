extends RefCounted
class_name PlanningSnapshotBuilder

## Converts the live BoardState into an immutable PlanningSnapshot for combat.
##
## Arrays are shallow-duplicated so subsequent board mutations during combat do not
## alter the snapshot. Phase D should deep-copy ChampionInstance objects if combat
## resolution needs to mutate them independently of the planning state.

## Builds and returns a PlanningSnapshot from `board` stamped with metadata from
## `run_state`. Passing a null `run_state` produces a snapshot with zeroed metadata.
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
