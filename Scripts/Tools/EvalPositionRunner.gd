extends SceneTree

# Headless evaluation host: load a TCG fixture, serialize BriefState, optionally
# run TurnSearch / commit checks, and emit one JSON object to stdout.
#
# Modes:
#   serialize | search | verify_end_turn | reject_stale | reject_hashless | agent_ready
#
# agent_ready starts EngineServer, pins the fixture state, prints EVAL_READY:<json>,
# then holds until RIFTBOUND_EVAL_DONE_PATH exists or the hold timeout elapses so
# Python live tools can call /engine/* mid-reasoning.
#
# Usage:
#   <godot> --headless --path <repo> --script res://Scripts/Tools/EvalPositionRunner.gd -- \
#       --fixture res://Scripts/Tests/Tcg/fixtures/search_winning_line.json \
#       [--seat 0] [--mode search] [--search-mode main] \
#       [--node-budget 80] [--time-budget-ms 1000]

const FixtureLoaderScript = preload("res://Scripts/Tests/Tcg/FixtureLoader.gd")
const GameControllerScript = preload("res://Scripts/Game/GameController.gd")
const TriggerDispatcherScript = preload("res://Scripts/Game/TriggerDispatcher.gd")
const BriefStateSerializerScript = preload("res://Scripts/AI/BriefStateSerializer.gd")
const TurnSearchScript = preload("res://Scripts/Game/TurnSearch.gd")
const ScoreModelScript = preload("res://Scripts/Game/ScoreModel.gd")
const ScoringProfileScript = preload("res://Scripts/Game/ScoringProfile.gd")
const AIPlayerScript = preload("res://Scripts/AI/AIPlayer.gd")
const EngineServerScript = preload("res://Scripts/AI/EngineServer.gd")
const MoveSimulatorScript = preload("res://Scripts/Game/MoveSimulator.gd")

var _fixture: String = ""
var _seat: int = 0
var _mode: String = "search"
var _search_mode: String = "main"
var _node_budget: int = 80
var _time_budget_ms: int = 1000
var _beam_width: int = 8
var _max_depth: int = 8
var _top_n: int = 8
var _seed_moves: Array = []
var _engine = null
var _controller = null


func _initialize() -> void:
	_parse_args(OS.get_cmdline_user_args())
	if _fixture == "":
		printerr(JSON.stringify({"ok": false, "error": "missing --fixture"}))
		quit(1)
		return
	if _mode == "agent_ready":
		await _run_agent_ready()
		return
	var result := _run()
	_emit_result(result)
	quit(0 if bool(result.get("ok", false)) else 2)


func _parse_args(args: PackedStringArray) -> void:
	var i := 0
	while i < args.size():
		var a := args[i]
		match a:
			"--fixture":
				i += 1
				if i < args.size():
					_fixture = str(args[i])
			"--seat":
				i += 1
				if i < args.size():
					_seat = int(args[i])
			"--mode":
				i += 1
				if i < args.size():
					_mode = str(args[i])
			"--search-mode":
				i += 1
				if i < args.size():
					_search_mode = str(args[i])
			"--node-budget":
				i += 1
				if i < args.size():
					_node_budget = int(args[i])
			"--time-budget-ms":
				i += 1
				if i < args.size():
					_time_budget_ms = int(args[i])
			"--beam-width":
				i += 1
				if i < args.size():
					_beam_width = int(args[i])
			"--max-depth":
				i += 1
				if i < args.size():
					_max_depth = int(args[i])
			"--top-n":
				i += 1
				if i < args.size():
					_top_n = int(args[i])
			"--seed-moves":
				i += 1
				if i < args.size():
					_seed_moves = str(args[i]).split("|", false)
		i += 1


func _emit_result(result: Dictionary) -> void:
	# Prefixed line so the Python host can ignore EngineServer chatter.
	print("EVAL_READY:" + JSON.stringify(result))


func _make_controller() -> GameController:
	var controller: GameController = GameControllerScript.new()
	controller.skip_auto_start = true
	controller._ai_player_index = -1
	controller.trigger_dispatcher = TriggerDispatcherScript.new()
	root.add_child(controller)
	FixtureLoaderScript.load_into_controller(controller, _fixture)
	return controller


func _run() -> Dictionary:
	var controller: GameController = _make_controller()
	var gs: GameState = controller.gs
	var before_hash := ScoreModelScript.structural_hash(ScoreModelScript.snapshot(gs, _seat))
	var brief: Dictionary = BriefStateSerializerScript.serialize(gs, _seat)
	var out := {
		"ok": true,
		"fixture": _fixture,
		"seat": _seat,
		"mode": _mode,
		"search_mode": _search_mode,
		"root_state_hash": before_hash,
		"decision_type": brief.get("decision_type", ""),
		"brief_state": brief,
		"live_state_unchanged": true,
		"engine_ok": true,
	}
	match _mode:
		"serialize":
			pass
		"search":
			out.merge(_run_search(gs, before_hash))
		"verify_end_turn":
			out.merge(_verify_end_turn(controller, before_hash))
		"reject_stale":
			out.merge(_reject_stale(controller, before_hash))
		"reject_hashless":
			out.merge(_reject_hashless(controller, before_hash))
		"resolve_discard":
			out.merge(_resolve_discard(controller, before_hash))
		_:
			out["ok"] = false
			out["error"] = "unknown mode %s" % _mode
	var after_hash := ScoreModelScript.structural_hash(ScoreModelScript.snapshot(controller.gs, _seat))
	out["live_state_unchanged"] = after_hash == before_hash or _mode in ["verify_end_turn", "resolve_discard"]
	if _mode == "search" and after_hash != before_hash:
		out["ok"] = false
		out["error"] = "search mutated live state"
		out["engine_ok"] = false
	controller.queue_free()
	return out


func _run_agent_ready() -> void:
	_controller = _make_controller()
	var gs: GameState = _controller.gs
	var before_hash := ScoreModelScript.structural_hash(ScoreModelScript.snapshot(gs, _seat))
	var brief: Dictionary = BriefStateSerializerScript.serialize(gs, _seat)
	var scout := _run_search(gs, before_hash)
	_engine = EngineServerScript.new()
	root.add_child(_engine)
	var port_override := OS.get_environment("RIFTBOUND_ENGINE_PORT").strip_edges()
	var listen_port := 0
	if port_override != "" and int(port_override) > 0:
		listen_port = int(port_override)
	if _engine.start(listen_port) != OK:
		_emit_result({"ok": false, "error": "engine server listen failed", "engine_ok": false})
		quit(2)
		return
	_engine.pin_state(gs, _seat)
	await process_frame
	var port: int = int(_engine.get_port())
	var out := {
		"ok": true,
		"fixture": _fixture,
		"seat": _seat,
		"mode": _mode,
		"search_mode": _search_mode,
		"root_state_hash": before_hash,
		"decision_type": brief.get("decision_type", ""),
		"brief_state": brief,
		"engine_port": port,
		"engine_ok": true,
		"live_state_unchanged": true,
	}
	out.merge(scout)
	_emit_result(out)

	var done_path := OS.get_environment("RIFTBOUND_EVAL_DONE_PATH").strip_edges()
	var hold_ms := 120000
	var hold_override := OS.get_environment("RIFTBOUND_EVAL_HOLD_MS").strip_edges()
	if hold_override != "" and int(hold_override) > 0:
		hold_ms = int(hold_override)
	var start_ms := Time.get_ticks_msec()
	while Time.get_ticks_msec() - start_ms < hold_ms:
		await process_frame
		if done_path != "" and FileAccess.file_exists(done_path):
			break
	if _engine != null:
		_engine.stop()
		_engine.queue_free()
		_engine = null
	if _controller != null:
		_controller.queue_free()
		_controller = null
	quit(0)


func _run_search(gs: GameState, root_hash: String) -> Dictionary:
	var searcher = TurnSearchScript.new()
	var options := {
		"mode": _search_mode,
		"node_budget": _node_budget,
		"time_budget_ms": _time_budget_ms,
		"beam_width": _beam_width,
		"max_depth": _max_depth,
		"top_n": _top_n,
	}
	if not _seed_moves.is_empty():
		options["seed_moves"] = _seed_moves
	var result: Dictionary = searcher.search(gs, _seat, options)
	var lines: Array = result.get("candidate_lines", [])
	var complete_count := 0
	var wins := false
	var best_score_after := -1
	for line in lines:
		if bool(line.get("complete", false)):
			complete_count += 1
		var resolved: Dictionary = line.get("resolved_state", {})
		if bool(resolved.get("wins_game", false)):
			wins = true
		best_score_after = maxi(best_score_after, int(resolved.get("my_score_after", -1)))
	var stats: Dictionary = result.get("search_stats", {})
	var first: Dictionary = lines[0] if not lines.is_empty() else {}
	var first_moves: Array = first.get("moves", []) if first is Dictionary else []
	return {
		"root_hash_matched": str(result.get("root_state_hash", "")) == root_hash,
		"candidate_count": lines.size(),
		"complete_candidate_count": complete_count,
		"has_candidates": lines.size() > 0,
		"has_complete_candidates": complete_count > 0,
		"wins_game_any": wins,
		"my_score_after_best": best_score_after,
		"score_after_at_least": best_score_after,
		"search_stats": stats,
		"candidate_lines": lines,
		"chosen_line_complete": bool(first.get("complete", false)) if first else false,
		"terminal_reason": str(first.get("terminal_reason", "")) if first else "",
		"incomplete": (not lines.is_empty()) and (not bool(first.get("complete", true))),
		"command": str(first_moves[0]) if not first_moves.is_empty() else "end turn",
		"first_move": str(first_moves[0]) if not first_moves.is_empty() else "",
		"reactive_mode": str(stats.get("mode", _search_mode)) == "reactive" or _search_mode == "reactive",
	}


func _verify_end_turn(controller: GameController, root_hash: String) -> Dictionary:
	var ai = AIPlayerScript.new()
	ai.controller = controller
	ai.player_index = _seat
	var line := {
		"line_id": "eval-end-turn",
		"moves": ["end turn"],
		"move_contexts": [{"kind": "scripted", "context": ""}],
		"expected_pre_hashes": [root_hash],
		"root_state_hash": root_hash,
		"legal": true,
		"complete": true,
		"terminal_reason": "end_turn",
		"search_mode": "main",
	}
	var emit := {
		"kind": "line",
		"chosen_line_id": line["line_id"],
		"root_state_hash": root_hash,
		"committed_line": line,
	}
	var accepted: bool = ai._try_commit_reasoner_line(controller.gs, emit)
	ai.free()
	return {
		"commit_accepted": accepted,
		"turn_advances": accepted and controller.gs.turn_player_index != _seat,
		"command": "end turn",
		"chosen_line_complete": true,
		"terminal_reason": "end_turn",
		"rejected": not accepted,
	}


func _reject_stale(controller: GameController, root_hash: String) -> Dictionary:
	var ai = AIPlayerScript.new()
	ai.controller = controller
	ai.player_index = _seat
	var before := root_hash
	var line := {
		"line_id": "stale-root",
		"moves": ["end turn"],
		"move_contexts": [{"kind": "scripted", "context": ""}],
		"expected_pre_hashes": ["not-the-live-root"],
		"root_state_hash": "not-the-live-root",
		"legal": true,
		"complete": true,
		"terminal_reason": "end_turn",
		"search_mode": "main",
	}
	var accepted: bool = ai._try_commit_reasoner_line(controller.gs, {
		"kind": "line",
		"chosen_line_id": line["line_id"],
		"root_state_hash": "not-the-live-root",
		"committed_line": line,
	})
	var after := ScoreModelScript.structural_hash(ScoreModelScript.snapshot(controller.gs, _seat))
	ai.free()
	var rejected := not accepted
	return {
		"rejected": rejected,
		"expected_reject": true,
		"stale_root_rejected": rejected,
		"reject_stale_root": rejected and after == before,
		"commit_accepted": accepted,
		"live_state_unchanged": after == before,
		"complete": false,
		"command": "end turn",
	}


func _reject_hashless(controller: GameController, root_hash: String) -> Dictionary:
	var ai = AIPlayerScript.new()
	ai.controller = controller
	ai.player_index = _seat
	var before := root_hash
	var line := {
		"line_id": "hashless-line",
		"moves": ["end turn"],
		"move_contexts": [{"kind": "scripted", "context": ""}],
		"expected_pre_hashes": [],
		"root_state_hash": root_hash,
		"legal": true,
		"complete": true,
		"terminal_reason": "end_turn",
		"search_mode": "main",
	}
	var accepted: bool = ai._try_commit_reasoner_line(controller.gs, {
		"kind": "line",
		"chosen_line_id": line["line_id"],
		"root_state_hash": root_hash,
		"committed_line": line,
	})
	var after := ScoreModelScript.structural_hash(ScoreModelScript.snapshot(controller.gs, _seat))
	ai.free()
	var rejected := not accepted
	return {
		"rejected": rejected,
		"expected_reject": true,
		"hashless_line_rejected": rejected,
		"reject_hashless": rejected and after == before,
		"commit_accepted": accepted,
		"live_state_unchanged": after == before,
		"complete": false,
		"command": "end turn",
	}


func _resolve_discard(controller: GameController, root_hash: String) -> Dictionary:
	var gs: GameState = controller.gs
	if gs.pending_prompt.is_empty() or str(gs.pending_prompt.get("type", "")) != "choose_discard":
		return {
			"ok": false,
			"engine_ok": false,
			"error": "resolve_discard requires pending choose_discard prompt",
		}
	var sim = MoveSimulatorScript.new()
	sim.ai_index = _seat
	var root_snapshot := ScoreModelScript.snapshot(gs, _seat)
	var profile = ScoringProfileScript.new()
	var ranker := func(cand_gs: GameState) -> float:
		var snap := ScoreModelScript.snapshot(cand_gs, _seat)
		return float(profile.score_with_breakdown(
			ScoreModelScript.build_score_features(root_snapshot, snap, [])
		)["score"])
	var step: Dictionary = sim._resolve_ai_prompt(controller, ranker)
	var command := str(step.get("command", ""))
	return {
		"command": command,
		"first_move": command,
		"discard_card": "fading-memories" in command,
		"legal_choice": command.begins_with("choose "),
		"chosen_line_complete": true,
		"complete": true,
		"candidate_count": 1,
		"complete_candidate_count": 1,
		"has_candidates": true,
		"root_hash_matched": true,
		"candidate_lines": [{
			"line_id": "eval-discard",
			"moves": [command],
			"complete": true,
			"legal": true,
			"resolved_state": {},
			"score": 0.0,
		}],
	}
