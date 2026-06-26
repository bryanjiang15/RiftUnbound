extends SceneTree

# Headless AI-vs-AI self-play driver for bulk tuning-data generation.
#
# Both seats run TurnSearch + ScoringProfile and select the top-scored line via
# argmax (no LLM round-trip). Two modes capture the resulting dataset
# (search_decisions / candidate_lines / decision_snapshots + /game_over backfill):
#
#   ONLINE  — the agent server must be running with:
#       RIFTBOUND_SEARCH=on RIFTBOUND_SEARCH_ARGMAX=on RIFTBOUND_DATA_ORIGIN=self_play
#     Point the engine at it with RIFTBOUND_AGENT_PORT. The server picks the
#     argmax line and writes SQL.
#
#   OFFLINE — set RIFTBOUND_SELFPLAY_CAPTURE=<log path> (or 1). No server runs:
#     each seat computes argmax locally and appends every server-bound payload to
#     a JSONL log. Replay it into SQLite afterward with:
#       python -m ai_agent.import_selfplay_logs <log> --db ai_agent/selfplay.db
#     This removes all per-decision HTTP and is the fast path for bulk runs.
#
# Usage (from repo root):
#   <godot> --headless --script res://Scripts/Tools/SelfPlaySim.gd -- \
#       --games 10 --seed 1000 [--p1 res://Data/Decks/...] [--p2 ...] [--turn-cap 200] \
#       [--p1-profile res://Data/AI/candidate.json] [--p2-profile res://Data/AI/scoring_profile.json]
#
# --p1-profile / --p2-profile point a seat at a specific scoring-profile JSON
# (omit for the live default). Use this to A/B a tuned candidate against the
# baseline: the win-rate over many games gates whether to commit the candidate.
#
# Set RIFTBOUND_AI_THINK_DELAY=0 to remove the per-move readability delay.

const AIPlayerScript = preload("res://Scripts/AI/AIPlayer.gd")

var _games: int = 2
var _seed_base: int = 1000
var _p1_deck: String = "res://Data/Decks/starter-deck-p2.json"
var _p2_deck: String = "res://Data/Decks/starter-deck-p2.json"
var _turn_cap: int = 200
# Optional per-seat scoring profile JSON. Empty = the live default profile. Lets
# a run pit one weight set against another (e.g. a Texel candidate vs baseline)
# so win-rate gates a tuning proposal.
var _p1_profile: String = "res://Data/AI/scoring_profile.json"
var _p2_profile: String = "res://Data/AI/scoring_profile.json"

# Per-game node state (members so the deferred driver can reach them safely
# without capturing them in a signal-emitted lambda).
var _controller: GameController = null
var _ai0 = null
var _ai1 = null
var _driving: bool = false

# Tally of suppressed engine [ERROR]/[WARNING] log lines, normalized to a type
# (variable parts collapsed) -> count. Printed once at the end instead of letting
# the per-move spam drown the progress output.
var _problem_counts: Dictionary = {}
var _problem_total: int = 0
var _problem_regexes_ready: bool = false
var _re_quoted: RegEx = null
var _re_number: RegEx = null


func _initialize() -> void:
	_parse_args(OS.get_cmdline_user_args())
	_run()


func _parse_args(args: PackedStringArray) -> void:
	var i := 0
	while i < args.size():
		var a := args[i]
		match a:
			"--games":
				i += 1
				if i < args.size():
					_games = maxi(1, int(args[i]))
			"--seed":
				i += 1
				if i < args.size():
					_seed_base = int(args[i])
			"--p1":
				i += 1
				if i < args.size():
					_p1_deck = args[i]
			"--p2":
				i += 1
				if i < args.size():
					_p2_deck = args[i]
			"--turn-cap":
				i += 1
				if i < args.size():
					_turn_cap = maxi(1, int(args[i]))
			"--p1-profile":
				i += 1
				if i < args.size():
					_p1_profile = args[i]
			"--p2-profile":
				i += 1
				if i < args.size():
					_p2_profile = args[i]
		i += 1


func _base_url() -> String:
	var host := "127.0.0.1" if OS.get_name() == "Windows" else "localhost"
	var port := 8765
	var override_port := OS.get_environment("RIFTBOUND_AGENT_PORT").strip_edges()
	if override_port != "" and int(override_port) > 0:
		port = int(override_port)
	return "http://%s:%d" % [host, port]


# Fail fast: confirm the agent server is up before running any games, so a
# missing server aborts with a clear message instead of silently degrading every
# decision to the engine heuristic (and producing no tuning data).
func _server_reachable() -> bool:
	var http := HTTPRequest.new()
	http.timeout = 5.0
	get_root().add_child(http)
	await process_frame
	var err := http.request(_base_url() + "/health")
	if err != OK:
		http.queue_free()
		return false
	var res = await http.request_completed
	http.queue_free()
	return res[0] == HTTPRequest.RESULT_SUCCESS and int(res[1]) == 200


const SelfPlayCaptureLogScript = preload("res://Scripts/AI/SelfPlayCaptureLog.gd")

func _run() -> void:
	# Offline capture mode bypasses the agent server entirely: each seat computes
	# the argmax decision locally and logs every server-bound payload for the
	# post-run importer. Skip the /health gate when capturing.
	var capture_mode := OS.get_environment("RIFTBOUND_SELFPLAY_CAPTURE").strip_edges() != ""
	if not capture_mode and not await _server_reachable():
		printerr("[SELFPLAY] ERROR: agent server not reachable at %s/health. " % _base_url()
			+ "Start it with RIFTBOUND_SEARCH=on RIFTBOUND_SEARCH_ARGMAX=on and set "
			+ "RIFTBOUND_AGENT_PORT to match. Aborting.")
		quit(1)
		return
	_print_header(capture_mode)
	var wins := [0, 0]      # wins[0] = P1, wins[1] = P2
	var unfinished := 0     # games that hit the turn cap without a winner
	for g in range(_games):
		var s := _seed_base + g
		var result := await _run_one_game(s)
		var finished: bool = result["finished"]
		var winner: int = result["winner"]
		if finished and winner >= 0:
			wins[winner] += 1
		else:
			unfinished += 1
		_print_progress(g + 1, wins, unfinished, s, finished, winner, int(result["turns"]))
	print("")  # end the in-place progress line
	_print_summary(wins, unfinished)
	_print_problem_summary()
	if capture_mode and SelfPlayCaptureLogScript.is_open():
		SelfPlayCaptureLogScript.close_log()
		print(" Capture log: %s (%d records)" % [
			SelfPlayCaptureLogScript.path(), SelfPlayCaptureLogScript.count()])
		print(" Import with: python -m ai_agent.import_selfplay_logs %s --db <db>" % SelfPlayCaptureLogScript.path())
		print("============================================================")
	quit(0)


# --- Pretty console output -------------------------------------------------

func _print_header(capture_mode: bool = false) -> void:
	print("")
	print("============================================================")
	print(" RiftBound Self-Play  |  %d games  |  seed base %d" % [_games, _seed_base])
	if capture_mode:
		print(" mode: OFFLINE CAPTURE (no server)")
	else:
		print(" server %s" % _base_url())
	print(" P1 profile: %s" % _profile_label(_p1_profile))
	print(" P2 profile: %s" % _profile_label(_p2_profile))
	print("============================================================")


func _profile_label(path: String) -> String:
	return path if path != "" else "(default scoring_profile.json)"


func _print_progress(done: int, wins: Array, unfinished: int, seed_used: int,
		finished: bool, winner: int, turns: int) -> void:
	var width := 24
	var filled := int(round(float(done) / float(_games) * width)) if _games > 0 else width
	filled = clampi(filled, 0, width)
	var bar := "#".repeat(filled) + "-".repeat(width - filled)
	var last: String
	if not finished:
		last = "turn cap"
	elif winner == 0:
		last = "P1 won"
	elif winner == 1:
		last = "P2 won"
	else:
		last = "draw"
	var line := " [%s] %d/%d | P1 %d  P2 %d  Unfinished %d | last: seed %d -> %s (t%d)" % [
		bar, done, _games, wins[0], wins[1], unfinished, seed_used, last, turns]
	# Pad so leftover characters from a longer previous line are cleared.
	printraw("\r" + line.rpad(100))


func _print_summary(wins: Array, unfinished: int) -> void:
	var completed: int = wins[0] + wins[1]
	print("============================================================")
	print(" Done: %d/%d games finished with a winner" % [completed, _games])
	print("   P1 wins: %d (%s)" % [wins[0], _pct(wins[0], completed)])
	print("   P2 wins: %d (%s)" % [wins[1], _pct(wins[1], completed)])
	print("   Unfinished (turn cap): %d" % unfinished)
	print("============================================================")


func _pct(n: int, total: int) -> String:
	if total <= 0:
		return "--"
	return "%.1f%%" % (float(n) / float(total) * 100.0)


# Tally suppressed engine [ERROR]/[WARNING] lines by normalized type. The lines
# are muted from the console (quiet_errors) so they don't drown the progress bar;
# this records them for the end-of-run summary.
func _on_game_log_for_problems(text: String) -> void:
	if not (text.begins_with("[ERROR]") or text.begins_with("[WARNING]")):
		return
	var key := _normalize_problem(text)
	_problem_counts[key] = int(_problem_counts.get(key, 0)) + 1
	_problem_total += 1


# Collapse the variable parts of a log line so different instances of the same
# error fold into one "type": quoted tokens → '…' and digit runs → N. Keeps the
# [ERROR]/[WARNING] severity prefix so the two are not merged.
func _normalize_problem(text: String) -> String:
	if not _problem_regexes_ready:
		_re_quoted = RegEx.new()
		_re_quoted.compile("'[^']*'")
		_re_number = RegEx.new()
		_re_number.compile("[0-9]+")
		_problem_regexes_ready = true
	var s := _re_quoted.sub(text, "'…'", true)
	s = _re_number.sub(s, "N", true)
	return s


func _print_problem_summary() -> void:
	print("")
	print("============================================================")
	if _problem_total == 0:
		print(" Errors/warnings: none")
		print("============================================================")
		return
	print(" Errors/warnings: %d total, %d type(s) (suppressed above)" % [
		_problem_total, _problem_counts.size()])
	print("------------------------------------------------------------")
	# Sort types by descending count for a readable scoreboard.
	var keys := _problem_counts.keys()
	keys.sort_custom(func(a, b): return int(_problem_counts[a]) > int(_problem_counts[b]))
	for k in keys:
		print("   %6d  %s" % [int(_problem_counts[k]), k])
	print("============================================================")


func _run_one_game(s: int) -> Dictionary:
	_controller = GameController.new()
	_controller.name = "GameController"
	_controller.skip_auto_start = true
	_controller.quiet_logs = true
	_controller.quiet_errors = true  # mute error spam; we tally + report at the end
	_controller._ai_player_index = -1  # disable the built-in single-seat trigger
	get_root().add_child(_controller)
	await process_frame  # let the controller settle into the tree

	_ai0 = AIPlayerScript.new()
	_ai0.name = "AIPlayer0"
	_controller.add_child(_ai0)
	_ai1 = AIPlayerScript.new()
	_ai1.name = "AIPlayer1"
	_controller.add_child(_ai1)
	# Critical: the AIPlayer nodes (and the HTTPRequest children they create in
	# setup) must be fully inside the tree before setup() calls request(); calling
	# setup() in the same frame as add_child() triggers !is_inside_tree() errors.
	await process_frame
	_ai0.setup(_controller, 0, _p1_profile)
	_ai1.setup(_controller, 1, _p2_profile)
	await process_frame  # let setup's HTTPRequest children + health probe settle

	_driving = false
	_controller.board_updated.connect(_on_board_updated_drive)
	_controller.game_log_message.connect(_on_game_log_for_problems)

	var cfg := {
		"seed": s,
		"first_player": s % 2,
		"game_session_id": "selfplay-%d-%d" % [_seed_base, s],
	}
	if _p1_deck != "":
		cfg["p1_deck"] = _p1_deck
	if _p2_deck != "":
		cfg["p2_deck"] = _p2_deck
	_controller.start_game_from_config(cfg)

	# Kick the loop after start (deferred so it never runs synchronously inside a
	# board_updated emission, which is what caused the get_tree()==null crash).
	call_deferred("_drive_deferred")

	var guard := 0
	var max_frames := _turn_cap * 2000
	while not _controller.gs.game_over and guard < max_frames and _controller.gs.turn_number <= _turn_cap:
		await process_frame
		guard += 1
		# Safety re-poke if the game stalled with no decision in flight.
		if not _driving and not _any_inflight():
			call_deferred("_drive_deferred")

	var finished := _controller.gs.game_over
	var winner := _controller.gs.winner_index if finished else -1
	var turns := _controller.gs.turn_number
	# Let the fire-and-forget /game_over POST flush before tearing down.
	await create_timer(1.5).timeout

	_controller.board_updated.disconnect(_on_board_updated_drive)
	_controller.game_log_message.disconnect(_on_game_log_for_problems)
	get_root().remove_child(_controller)
	_controller.free()
	_controller = null
	_ai0 = null
	_ai1 = null
	_driving = false
	return {"finished": finished, "winner": winner, "turns": turns}


func _on_board_updated_drive() -> void:
	# Always defer: board_updated fires synchronously from inside engine calls,
	# and take_turn() awaits get_tree() — driving inline can run before the node
	# tree is settled and crash. call_deferred guarantees a safe context.
	call_deferred("_drive_deferred")


func _drive_deferred() -> void:
	if _driving:
		return
	var gs = _controller.gs if _controller else null
	if gs == null or gs.game_over:
		return
	if _any_inflight():
		return
	var actor = _pick_actor(gs)
	if actor == null:
		return
	_driving = true
	# take_turn awaits THINK_DELAY then either replays a committed step (sync) or
	# fires the HTTP decision (sets _waiting_for_http). Await it fully, then wait
	# out any in-flight HTTP so exactly one decision resolves per drive.
	await actor.take_turn()
	while actor != null and actor._waiting_for_http:
		await process_frame
	_driving = false
	# A decision resolved and the board likely changed; poke for the next one.
	call_deferred("_drive_deferred")


func _pick_actor(gs):
	if _ai0._can_act_now(gs) and not _ai0._legal_moves_for(gs).is_empty():
		return _ai0
	if _ai1._can_act_now(gs) and not _ai1._legal_moves_for(gs).is_empty():
		return _ai1
	return null


func _any_inflight() -> bool:
	return (_ai0 != null and _ai0._waiting_for_http) or (_ai1 != null and _ai1._waiting_for_http)
