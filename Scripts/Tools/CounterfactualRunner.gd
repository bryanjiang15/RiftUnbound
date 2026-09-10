extends SceneTree

# Headless snapshot host for offline same-turn counterfactual analysis.
#
# Restores a versioned AnalysisStateCodec dump, optionally pins it in EngineServer,
# and emits EVAL_READY:<json> so Python can call /engine/search and /engine/simulate.
#
# Modes:
#   restore_hash  — restore + structural-hash check, then quit
#   agent_ready   — restore + pin EngineServer, hold until done-file / timeout
#
# Usage:
#   <godot> --headless --path <repo> --script res://Scripts/Tools/CounterfactualRunner.gd -- \
#       --analysis-state-file /tmp/state.json [--seat 0] [--mode agent_ready] \
#       [--expected-hash HASH] [--profile-path res://Data/AI/scoring_profile.json]

const GameControllerScript = preload("res://Scripts/Game/GameController.gd")
const TriggerDispatcherScript = preload("res://Scripts/Game/TriggerDispatcher.gd")
const ScoreModelScript = preload("res://Scripts/Game/ScoreModel.gd")
const EngineServerScript = preload("res://Scripts/AI/EngineServer.gd")
const AnalysisStateCodecScript = preload("res://Scripts/AI/AnalysisStateCodec.gd")

var _state_file: String = ""
var _seat: int = 0
var _mode: String = "restore_hash"
var _expected_hash: String = ""
var _profile_path: String = ""
var _engine = null
var _controller = null


func _initialize() -> void:
	_parse_args(OS.get_cmdline_user_args())
	if _state_file == "":
		_emit({"ok": false, "error": "missing --analysis-state-file"})
		quit(1)
		return
	if _mode == "agent_ready":
		await _run_agent_ready()
		return
	var result := _run_restore()
	_emit(result)
	quit(0 if bool(result.get("ok", false)) else 2)


func _parse_args(args: PackedStringArray) -> void:
	var i := 0
	while i < args.size():
		var a := args[i]
		match a:
			"--analysis-state-file":
				i += 1
				if i < args.size():
					_state_file = str(args[i])
			"--seat":
				i += 1
				if i < args.size():
					_seat = int(args[i])
			"--mode":
				i += 1
				if i < args.size():
					_mode = str(args[i])
			"--expected-hash":
				i += 1
				if i < args.size():
					_expected_hash = str(args[i])
			"--profile-path":
				i += 1
				if i < args.size():
					_profile_path = str(args[i])
		i += 1


func _emit(result: Dictionary) -> void:
	print("EVAL_READY:" + JSON.stringify(result))


func _load_payload() -> Dictionary:
	var path := _state_file
	if not path.begins_with("res://") and not path.begins_with("user://"):
		# Absolute / relative filesystem path.
		pass
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return {}
	var parsed = JSON.parse_string(file.get_as_text())
	file.close()
	return parsed if parsed is Dictionary else {}


func _restore() -> Dictionary:
	var payload := _load_payload()
	if payload.is_empty():
		return {"ok": false, "error": "failed_to_read_analysis_state"}
	var restored: Dictionary = AnalysisStateCodecScript.restore_state(payload)
	if not bool(restored.get("ok", false)):
		return {"ok": false, "error": str(restored.get("error", "restore_failed"))}
	var gs: GameState = restored["gs"]
	var replay: Dictionary = restored.get("replay", {})
	var hash_now := AnalysisStateCodecScript.root_hash(gs, _seat)
	var hash_ok := true
	if _expected_hash != "":
		hash_ok = hash_now == _expected_hash
	return {
		"ok": hash_ok and bool(replay.get("supported", false)),
		"gs": gs,
		"replay": replay,
		"root_state_hash": hash_now,
		"expected_hash": _expected_hash,
		"hash_matched": hash_ok if _expected_hash != "" else true,
		"schema_version": AnalysisStateCodecScript.SCHEMA_VERSION,
		"seat": _seat,
		"mode": _mode,
	}


func _attach_controller(gs: GameState) -> GameController:
	var controller: GameController = GameControllerScript.new()
	controller.skip_auto_start = true
	controller._ai_player_index = -1
	controller.trigger_dispatcher = TriggerDispatcherScript.new()
	controller.log_lines.clear()
	controller.gs = gs
	root.add_child(controller)
	return controller


func _run_restore() -> Dictionary:
	var restored := _restore()
	if restored.has("gs"):
		restored.erase("gs")
	if not restored.get("replay", {}).get("supported", false):
		restored["ok"] = false
		if str(restored.get("error", "")) == "":
			restored["error"] = "unsupported_snapshot"
	if restored.get("expected_hash", "") != "" and not bool(restored.get("hash_matched", true)):
		restored["ok"] = false
		restored["error"] = "hash_mismatch"
	return restored


func _run_agent_ready() -> void:
	var restored := _restore()
	if not bool(restored.get("ok", false)) and restored.get("gs") == null:
		_emit({"ok": false, "error": restored.get("error", "restore_failed"), "engine_ok": false})
		quit(2)
		return
	var gs: GameState = restored["gs"]
	_controller = _attach_controller(gs)
	var replay: Dictionary = restored.get("replay", {})
	if not bool(replay.get("supported", false)):
		_emit({
			"ok": false,
			"error": "unsupported_snapshot",
			"replay": replay,
			"root_state_hash": restored.get("root_state_hash", ""),
			"hash_matched": restored.get("hash_matched", true),
			"engine_ok": false,
		})
		quit(2)
		return
	if restored.get("expected_hash", "") != "" and not bool(restored.get("hash_matched", true)):
		_emit({
			"ok": false,
			"error": "hash_mismatch",
			"root_state_hash": restored.get("root_state_hash", ""),
			"expected_hash": _expected_hash,
			"hash_matched": false,
			"engine_ok": false,
		})
		quit(2)
		return

	_engine = EngineServerScript.new()
	root.add_child(_engine)
	var port_override := OS.get_environment("RIFTBOUND_ENGINE_PORT").strip_edges()
	var listen_port := 0
	if port_override != "" and int(port_override) > 0:
		listen_port = int(port_override)
	if _engine.start(listen_port, _profile_path) != OK:
		_emit({"ok": false, "error": "engine server listen failed", "engine_ok": false})
		quit(2)
		return
	_engine.pin_state(gs, _seat)
	await process_frame
	_emit({
		"ok": true,
		"seat": _seat,
		"mode": _mode,
		"root_state_hash": restored.get("root_state_hash", ""),
		"hash_matched": restored.get("hash_matched", true),
		"replay": replay,
		"engine_port": int(_engine.get_port()),
		"engine_ok": true,
		"schema_version": AnalysisStateCodecScript.SCHEMA_VERSION,
	})

	var done_path := OS.get_environment("RIFTBOUND_EVAL_DONE_PATH").strip_edges()
	var hold_ms := 180000
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
