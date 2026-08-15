class_name LineReplayer
extends RefCounted

# Replays a TurnSearch candidate line onto a cloned GameState, stopping at the
# first decision boundary for another seat (or at line completion / game over).
# Used by OutcomeRollout to hand state across seats without relying on TurnSearch
# leaf controllers (which are freed after search).

const MoveSimulatorScript = preload("res://Scripts/Game/MoveSimulator.gd")
const ScoreModelScript = preload("res://Scripts/Game/ScoreModel.gd")

var _sim: RefCounted = MoveSimulatorScript.new()


## Replay `moves` for `seat` starting from `root_gs`.
## options:
##   stop_at_opponent (bool, default true)
##   choice_ranker (Callable)
## Returns: ok, gs, applied, remaining, stopped_reason, boundary, hashes,
##   search_state, complete, terminal_reason, error, windows
func replay_line(
	root_gs: GameState,
	moves: Array,
	seat: int,
	options: Dictionary = {},
) -> Dictionary:
	if root_gs == null:
		return _fail("null_root")
	var stop_at_opponent := bool(options.get("stop_at_opponent", true))
	var choice_ranker: Callable = options.get("choice_ranker", Callable())
	var sc: GameController = _sim.build_sim_controller(root_gs)
	if sc == null:
		return _fail("clone_failed")
	_sim.ai_index = seat

	var applied: Array = []
	var remaining: Array = []
	var hashes: Array = []
	var windows: Array = []
	var ai_steps: Array = []
	var stopped_reason := "quiescence"
	var last_cmd := ""

	var cmds: Array = []
	for m in moves:
		var s := str(m).strip_edges()
		if s != "":
			cmds.append(s)

	for i in range(cmds.size()):
		var cmd_str: String = cmds[i]
		var pre_hash := ScoreModelScript.structural_hash(
			ScoreModelScript.snapshot(sc.gs, seat)
		)
		hashes.append(pre_hash)
		sc.submit_command(seat, cmd_str)
		if sc.last_command_error:
			var err := str(sc.last_command_error)
			var bad_gs: GameState = sc.gs.clone() if sc.gs != null else null
			sc.free()
			return {
				"ok": false,
				"error": "illegal:%s" % cmd_str,
				"detail": err,
				"gs": bad_gs,
				"applied": applied,
				"remaining": cmds.slice(i),
				"stopped_reason": "illegal",
				"boundary": _sim.describe_decision_boundary(bad_gs if bad_gs else root_gs),
				"hashes": hashes,
				"complete": false,
				"terminal_reason": "illegal",
				"search_state": {},
				"windows": [],
			}
		applied.append(cmd_str)
		last_cmd = cmd_str
		ai_steps.clear()
		windows.clear()
		if stop_at_opponent:
			stopped_reason = _sim.advance_until_decision_boundary(
				sc, cmd_str, windows, ai_steps, choice_ranker
			)
		else:
			stopped_reason = _sim.advance_to_quiescence(
				sc, cmd_str, windows, ai_steps, choice_ranker
			)
		for step in ai_steps:
			applied.append(str(step.get("command", "")))
		if stopped_reason == "game_over":
			remaining = cmds.slice(i + 1)
			break
		if stopped_reason == "decision_boundary":
			remaining = cmds.slice(i + 1)
			break
		if stopped_reason == "ply_budget":
			remaining = cmds.slice(i + 1)
			break

	var leaf_gs: GameState = sc.gs.clone()
	sc.free()
	if leaf_gs == null:
		return _fail("clone_failed_after_replay")

	var boundary: Dictionary = _sim.describe_decision_boundary(leaf_gs, seat)
	var snap := ScoreModelScript.snapshot(leaf_gs, seat)
	var root_snap := ScoreModelScript.snapshot(root_gs, seat)
	var features := ScoreModelScript.build_score_features(root_snap, snap, [])
	var search_state := ScoreModelScript.build_search_state(snap, features, [])
	var complete := false
	var terminal_reason := stopped_reason
	if leaf_gs.game_over:
		complete = true
		terminal_reason = "game_over"
	elif stopped_reason == "decision_boundary":
		complete = false
		terminal_reason = "decision_boundary"
	elif last_cmd == "end turn" and remaining.is_empty():
		complete = true
		terminal_reason = "end_turn"
	elif remaining.is_empty() and str(boundary.get("kind", "")) in ["main_turn", "game_over"]:
		complete = true
		terminal_reason = str(boundary.get("kind", "end_turn"))

	return {
		"ok": true,
		"error": "",
		"gs": leaf_gs,
		"applied": applied,
		"remaining": remaining,
		"stopped_reason": stopped_reason,
		"boundary": boundary,
		"hashes": hashes,
		"complete": complete,
		"terminal_reason": terminal_reason,
		"search_state": search_state,
		"windows": windows,
	}


## Convenience: apply moves with legacy auto-pass quiescence (no opponent branching).
func replay_to_quiescence(root_gs: GameState, moves: Array, seat: int) -> Dictionary:
	return replay_line(root_gs, moves, seat, {"stop_at_opponent": false})


func _fail(reason: String) -> Dictionary:
	return {
		"ok": false,
		"error": reason,
		"gs": null,
		"applied": [],
		"remaining": [],
		"stopped_reason": reason,
		"boundary": {"kind": "none", "acting_seat": -1},
		"hashes": [],
		"complete": false,
		"terminal_reason": reason,
		"search_state": {},
		"windows": [],
	}
