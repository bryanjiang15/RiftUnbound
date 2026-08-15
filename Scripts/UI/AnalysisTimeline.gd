class_name AnalysisTimeline
extends RefCounted

# Builds a ply-by-ply GameState cache for stepping through a candidate /
# counterfactual line — or a multi-seat outcome-rollout path — from a restored
# analysis-state root.

const MoveSimulatorScript = preload("res://Scripts/Game/MoveSimulator.gd")
const LineReplayerScript = preload("res://Scripts/Game/LineReplayer.gd")

var steps: Array = []  # Array[Dictionary]: {move, label, gs, legal, error, seat, segment}
var cursor: int = 0
var seat: int = 0
var line_id: String = ""
var stopped_reason: String = ""
var path_meta: Dictionary = {}


func clear() -> void:
	steps.clear()
	cursor = 0
	line_id = ""
	stopped_reason = ""
	path_meta = {}


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
		"seat": deciding_seat,
		"segment": 0,
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
				"seat": deciding_seat,
				"segment": 0,
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

		var label := cmd_str
		if not windows.is_empty():
			label = "%s ⚠ opp may respond" % cmd_str
		steps.append({
			"move": cmd_str,
			"label": label,
			"gs": next_gs,
			"legal": true,
			"error": "",
			"seat": deciding_seat,
			"segment": 0,
		})
		prev_gs = next_gs
		applied += 1
		if stopped_reason == "game_over":
			break

	cursor = 0
	return {"ok": true, "error": "", "applied": applied}


## Multi-seat rollout path: ordered segments with {seat, moves, kind, boundary}.
func build_from_path(root_gs: GameState, path: Dictionary, deciding_seat: int = 0) -> Dictionary:
	clear()
	seat = deciding_seat
	line_id = str(path.get("line_id", path.get("root_line_id", "path")))
	path_meta = {
		"root_line_id": path.get("root_line_id"),
		"terminal_reason": path.get("terminal_reason"),
		"depth_player_turns": path.get("depth_player_turns"),
	}
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
		"seat": deciding_seat,
		"segment": -1,
	})

	var replayer = LineReplayerScript.new()
	var prev_gs: GameState = root_clone
	var applied := 0
	var segments: Array = path.get("path_segments", [])
	if segments.is_empty() and path.has("moves"):
		return build_from_line(root_gs, path.get("moves", []), deciding_seat, line_id)

	for seg_i in range(segments.size()):
		var seg: Dictionary = segments[seg_i]
		var seg_seat := int(seg.get("seat", deciding_seat))
		var seg_kind := str(seg.get("kind", "main"))
		var moves: Array = seg.get("moves", [])
		var future_turn := int(seg.get("depth_player_turns", path.get("depth_player_turns", 0)) )
		# Replay each segment move-by-move for stepping, using boundary-aware
		# advance so reactions remain visible.
		for cmd in moves:
			var cmd_str := str(cmd)
			var one: Dictionary = replayer.replay_line(prev_gs, [cmd_str], seg_seat, {
				"stop_at_opponent": true,
			})
			if one.get("gs") == null:
				stopped_reason = str(one.get("error", "replay_failed"))
				steps.append({
					"move": cmd_str,
					"label": "fail[%s seat%d]: %s" % [seg_kind, seg_seat, cmd_str],
					"gs": prev_gs.clone(),
					"legal": false,
					"error": stopped_reason,
					"seat": seg_seat,
					"segment": seg_i,
				})
				cursor = 0
				return {"ok": false, "error": stopped_reason, "applied": applied}
			var next_gs: GameState = one["gs"]
			var boundary: Dictionary = one.get("boundary", {})
			var label := "S%d %s T+%s: %s" % [
				seg_seat,
				seg_kind,
				str(future_turn),
				cmd_str,
			]
			if str(boundary.get("kind", "")) in ["chain", "showdown", "prompt"]:
				label += " ⚠ boundary"
			steps.append({
				"move": cmd_str,
				"label": label,
				"gs": next_gs,
				"legal": bool(one.get("ok", true)),
				"error": str(one.get("error", "")),
				"seat": seg_seat,
				"segment": seg_i,
				"boundary": boundary,
			})
			prev_gs = next_gs
			applied += 1
			if str(one.get("terminal_reason", "")) == "game_over":
				stopped_reason = "game_over"
				cursor = 0
				return {"ok": true, "error": "", "applied": applied}
		# Checkpoint marker between segments
		if seg.has("checkpoint") and seg["checkpoint"] is Dictionary and not seg["checkpoint"].is_empty():
			steps.append({
				"move": "",
				"label": "checkpoint T+%s seat%d" % [str(future_turn), seg_seat],
				"gs": prev_gs.clone() if prev_gs != null else null,
				"legal": true,
				"error": "",
				"seat": seg_seat,
				"segment": seg_i,
				"checkpoint": seg["checkpoint"],
			})

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
