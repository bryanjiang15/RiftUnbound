class_name AnalysisTimeline
extends RefCounted

# Builds a ply-by-ply GameState cache for stepping through a candidate /
# counterfactual line from a restored analysis-state root.
#
# simulate_line only returns leaf deltas — intermediate boards are produced
# here by cloning + applying one move at a time via MoveSimulator.

const MoveSimulatorScript = preload("res://Scripts/Game/MoveSimulator.gd")

var steps: Array = []  # Array[Dictionary]: {move: String, label: String, gs: GameState, legal: bool, error: String}
var cursor: int = 0
var seat: int = 0
var line_id: String = ""
var stopped_reason: String = ""


func clear() -> void:
	steps.clear()
	cursor = 0
	line_id = ""
	stopped_reason = ""


func is_empty() -> bool:
	return steps.is_empty()


func size() -> int:
	return steps.size()


func current_gs() -> GameState:
	if steps.is_empty():
		return null
	return steps[cursor].get("gs") as GameState


func current_move() -> String:
	if steps.is_empty():
		return ""
	return str(steps[cursor].get("move", ""))


func current_label() -> String:
	if steps.is_empty():
		return ""
	return str(steps[cursor].get("label", ""))


func set_cursor(index: int) -> bool:
	if steps.is_empty():
		return false
	var clamped := clampi(index, 0, steps.size() - 1)
	if clamped == cursor:
		return false
	cursor = clamped
	return true


func step_prev() -> bool:
	return set_cursor(cursor - 1)


func step_next() -> bool:
	return set_cursor(cursor + 1)


## Build timeline from a restored root GameState and a list of move commands.
## Returns {ok: bool, error: String, applied: int}.
func build_from_line(root_gs: GameState, move_commands: Array, deciding_seat: int = 0, id: String = "") -> Dictionary:
	clear()
	seat = deciding_seat
	line_id = id
	if root_gs == null:
		return {"ok": false, "error": "null_root", "applied": 0}

	var root_clone: GameState = root_gs.clone()
	if root_clone == null:
		return {"ok": false, "error": "clone_failed", "applied": 0}

	steps.append({
		"move": "",
		"label": "root",
		"gs": root_clone,
		"legal": true,
		"error": "",
	})

	var sim: MoveSimulator = MoveSimulatorScript.new()
	sim.ai_index = deciding_seat
	var prev_gs: GameState = root_clone
	var applied := 0

	for cmd in move_commands:
		var cmd_str := str(cmd)
		var sc: GameController = sim.build_sim_controller(prev_gs)
		if sc == null:
			stopped_reason = "clone_failed"
			return {"ok": false, "error": "clone_failed", "applied": applied}

		sc.submit_command(deciding_seat, cmd_str)
		var illegal := false
		var err := ""
		if sc.last_command_error:
			illegal = true
			err = str(sc.last_command_error)
			stopped_reason = "illegal"
			steps.append({
				"move": cmd_str,
				"label": "illegal: %s" % cmd_str,
				"gs": sc.gs.clone() if sc.gs != null else prev_gs.clone(),
				"legal": false,
				"error": err,
			})
			sc.free()
			break

		var windows: Array = []
		stopped_reason = sim.advance_to_quiescence(sc, cmd_str, windows)
		var next_gs: GameState = sc.gs.clone()
		sc.free()
		if next_gs == null:
			stopped_reason = "clone_failed"
			return {"ok": false, "error": "clone_failed_after_move", "applied": applied}

		steps.append({
			"move": cmd_str,
			"label": cmd_str,
			"gs": next_gs,
			"legal": true,
			"error": "",
		})
		prev_gs = next_gs
		applied += 1
		if stopped_reason == "game_over":
			break

	cursor = 0
	return {"ok": true, "error": "", "applied": applied}


## Root-only timeline (view checkpoint without a line).
func build_root_only(root_gs: GameState, deciding_seat: int = 0) -> Dictionary:
	return build_from_line(root_gs, [], deciding_seat, "root")


func move_labels() -> PackedStringArray:
	var out := PackedStringArray()
	for i in range(steps.size()):
		var s: Dictionary = steps[i]
		var label := str(s.get("label", ""))
		if i == 0:
			out.append("0  root")
		else:
			out.append("%d  %s" % [i, label])
	return out
