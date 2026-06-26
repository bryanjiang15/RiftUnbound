class_name AIPlayer
extends Node

# AI player that sends the current game state to the Python agent service and
# executes whatever command the agent returns.  Falls back to the built-in
# heuristic when the service is unreachable or returns an error.
#
# The node must be named "AIPlayer" (GameController looks it up by that name).
# GameScene wires it up via: _ai.setup(_controller, 1)

# Emitted whenever the AI commits an accepted move, so the UI can offer live
# per-move feedback. Carries a human-readable description, the current turn,
# and a per-game move sequence number for telemetry alignment.
signal ai_move_completed(description: String, turn: int, move_seq: int)

var controller: GameController
var player_index: int = 1
var _think_delay: float = THINK_DELAY

const AGENT_PORT := 8765
const THINK_DELAY := 0.5       # seconds before each decision (default; override
							   # per-instance via RIFTBOUND_AI_THINK_DELAY env)
const HTTP_TIMEOUT := 30.0     # seconds before falling back to heuristic
							   # (the agent may make several sequential LLM
							   # calls per decision; 8s was far too short)
const MAX_RETRIES := 3         # max rejection retry attempts
const TurnSearchScript = preload("res://Scripts/Game/TurnSearch.gd")
const ScoringProfileScript = preload("res://Scripts/Game/ScoringProfile.gd")
const MulliganHeuristicScript = preload("res://Scripts/AI/MulliganHeuristic.gd")

# Resolved in setup() so it can differ per OS (see _agent_base_url()).
var AGENT_URL := ""

# Mulligan keep/set-aside priors, loaded from scoring_profile.json["mulligan"].
# Handled locally by MulliganHeuristic instead of deferring to the agent server.
var _mulligan_config: Dictionary = {}

# Path to this seat's scoring profile JSON. Empty = the live default profile.
# Set per-instance (e.g. by SelfPlaySim) so two seats can search under different
# weights for A/B self-play; threaded into every TurnSearch this seat creates and
# into the local mulligan config load.
var _scoring_profile_path: String = "res://Data/AI/candidate_profile.json"

# Raw JSON text of this seat's scoring profile, sent with each search decision so
# the server can attribute the captured row to the EXACT weights that produced it
# (per-seat). Without this the server would stamp every row with the single
# profile it read at startup, mislabelling two-profile self-play runs.
var _scoring_profile_json: String = ""

# Whether to run the engine-side turn search and ship candidate lines to the
# agent. The agent service is the single source of truth (it reads RIFTBOUND_SEARCH
# from its own environment); the engine and agent are separate processes that do
# not share an environment, so the engine fetches the flag from the service's
# /health endpoint at setup. The RIFTBOUND_SEARCH env var, if present in the
# engine's own environment, is used as the pre-handshake default.
var _search_mode: bool = false

var _http: HTTPRequest = null
# Dedicated request for the one-shot search-config handshake (HTTPRequest handles
# a single request at a time, so it cannot share _http).
var _config_http: HTTPRequest = null
var _pending_brief_state: Dictionary = {}
var _retry_count: int = 0
var _last_rejected_move: Dictionary = {}
var _last_rejection_reason: String = ""
var _waiting_for_http: bool = false
var _candidate_lines: Array = []
var _search_stats: Dictionary = {}
var _committed_line: Dictionary = {}
var _committed_line_index: int = 0

# Eval (reliability track): wall-clock start of the in-flight decision request,
# used to report engine-observed latency back to the agent service.
var _decision_start_ms: int = 0

# Phase 1 additions
var _current_game_id: String = ""
var _game_over_reported: bool = false

# Per-game counter of accepted AI moves, used to key live per-move feedback.
var _move_seq: int = 0


func setup(gc: GameController, pi: int, scoring_profile_path: String = "") -> void:
	controller = gc
	player_index = pi
	_scoring_profile_path = scoring_profile_path
	# Pre-handshake default from the engine's own env (usually unset); the agent
	# service's /health response is authoritative and overrides this below.
	_search_mode = _env_flag("RIFTBOUND_SEARCH")
	var delay_override := OS.get_environment("RIFTBOUND_AI_THINK_DELAY").strip_edges()
	if delay_override != "":
		_think_delay = maxf(0.0, float(delay_override))
	var mulligan_profile_path := _scoring_profile_path if _scoring_profile_path != "" else ScoringProfileScript.DEFAULT_PROFILE_PATH
	_mulligan_config = ScoringProfileScript.load_profile(mulligan_profile_path).get("mulligan", {})
	# Raw profile text for server-side weight-version attribution. Read the same
	# file the search scores under; hashing the raw text keeps it consistent with
	# the server's own startup registration of an identical file.
	_scoring_profile_json = FileAccess.get_file_as_string(mulligan_profile_path)
	AGENT_URL = _agent_base_url() + "/decision"
	_http = HTTPRequest.new()
	_http.timeout = HTTP_TIMEOUT
	add_child(_http)
	_http.request_completed.connect(_on_request_completed)
	_config_http = HTTPRequest.new()
	_config_http.timeout = HTTP_TIMEOUT
	add_child(_config_http)
	_config_http.request_completed.connect(_on_config_completed)
	_fetch_search_config()
	# Phase 1: detect game-over and opponent actions
	controller.board_updated.connect(_on_board_updated)
	controller.game_log_message.connect(_on_game_log_message)
	# Phase 3: per-card statistics
	controller.card_event.connect(_on_card_event)


# Ask the agent service whether search mode is enabled, so the engine matches the
# service's RIFTBOUND_SEARCH setting without relying on a shared environment.
func _fetch_search_config() -> void:
	var url := _agent_base_url() + "/health"
	var err := _config_http.request(url)
	if err != OK:
		push_warning("AIPlayer: search config fetch failed to start (err=%d); using env default." % err)


func _on_config_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or response_code != 200:
		push_warning("AIPlayer: search config fetch failed (result=%d, code=%d); using env default." % [result, response_code])
		return
	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if parsed is Dictionary and parsed.has("search_enabled"):
		_search_mode = bool(parsed["search_enabled"])


# Mirror the Python agent's truthy-env parsing so both sides agree on whether
# search mode is enabled.
func _env_flag(name: String) -> bool:
	return OS.get_environment(name).strip_edges().to_lower() in ["1", "true", "yes", "on"]


func _agent_base_url() -> String:
	# Windows resolves "localhost" to IPv6 (::1) first, but the agent binds to
	# IPv4 only, so the connection stalls before falling back to 127.0.0.1.
	# Use the explicit IPv4 loopback on Windows; "localhost" works elsewhere
	# (macOS/Linux) where resolution doesn't incur that stall.
	var host := "127.0.0.1" if OS.get_name() == "Windows" else "localhost"
	var port := AGENT_PORT
	var port_override := OS.get_environment("RIFTBOUND_AGENT_PORT").strip_edges()
	if port_override != "" and int(port_override) > 0:
		port = int(port_override)
	return "http://%s:%d" % [host, port]


func take_turn() -> void:
	if controller == null or controller.gs == null:
		return
	var gs = controller.gs
	if gs.game_over:
		return
	if _waiting_for_http:
		return

	if not _can_act_now(gs):
		return
	if _legal_moves_for(gs).is_empty():
		return

	# Delay slightly so the game log is readable
	await get_tree().create_timer(_think_delay).timeout
	if gs.game_over:
		return

	if not _can_act_now(gs):
		return
	if _legal_moves_for(gs).is_empty():
		return

	# Mulligan is decided by a local cost/type heuristic (priors from
	# scoring_profile.json["mulligan"]) rather than a round-trip to the agent.
	if gs.mulligan_phase and not gs.mulligan_done[player_index]:
		_submit(MulliganHeuristicScript.choose_command(gs, player_index, _mulligan_config))
		return

	if _search_mode and not _committed_line.is_empty():
		if _play_committed_step(gs):
			return
		# The committed line is finished or diverged — fall through to a fresh
		# decision so anything after the planned turn (e.g. an opponent-initiated
		# showdown where the AI must pass) is still handled instead of hanging.

	_retry_count = 0
	_last_rejected_move = {}
	_last_rejection_reason = ""
	await _request_decision(gs)


# ── HTTP request ──────────────────────────────────────────────────────────────

func _request_decision(gs: GameState) -> void:
	_pending_brief_state = BriefStateSerializer.serialize(gs, player_index)
	_on_session_changed(_pending_brief_state.get("game_id", ""))
	_candidate_lines = []
	_search_stats = {}
	if _search_mode and _should_run_search(gs):
		var searcher: TurnSearch = TurnSearchScript.new(_scoring_profile_path)
		var result: Dictionary = searcher.search(gs, player_index, {"mode": "main"})
		_candidate_lines = result.get("candidate_lines", [])
		_search_stats = result.get("search_stats", {})
	elif _search_mode and _should_run_reactive_search(gs):
		var reactive: TurnSearch = TurnSearchScript.new(_scoring_profile_path)
		var rresult: Dictionary = reactive.search(gs, player_index, {"mode": "reactive"})
		_candidate_lines = rresult.get("candidate_lines", [])
		_search_stats = rresult.get("search_stats", {})

	var payload := JSON.stringify(_build_request_payload())
	var headers := PackedStringArray(["Content-Type: application/json"])

	var err = _http.request(AGENT_URL, headers, HTTPClient.METHOD_POST, payload)
	if err != OK:
		push_warning("AIPlayer: HTTPRequest failed to start (err=%d). Using heuristic." % err)
		_report_decision_metrics(true, null)
		_heuristic_fallback(gs)
		return

	_decision_start_ms = Time.get_ticks_msec()
	_waiting_for_http = true


func _build_request_payload() -> Dictionary:
	var payload := {
		"brief_state": _pending_brief_state,
		"game_id": _pending_brief_state.get("game_id", "game"),
	}
	if not _last_rejected_move.is_empty():
		payload["rejection_context"] = {
			"rejected_move": _last_rejected_move,
			"rejection_reason": _last_rejection_reason,
		}
	if _search_mode and not _candidate_lines.is_empty():
		payload["candidate_lines"] = _candidate_lines
		payload["search_stats"] = _search_stats
		if _scoring_profile_json != "":
			payload["scoring_profile_json"] = _scoring_profile_json
	return payload


func _on_request_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	_waiting_for_http = false
	var gs = controller.gs if controller else null
	if gs == null or gs.game_over:
		return

	if result != HTTPRequest.RESULT_SUCCESS or response_code != 200:
		push_warning("AIPlayer: HTTP error (result=%d, code=%d). Using heuristic." % [result, response_code])
		_report_decision_metrics(true, null)
		_heuristic_fallback(gs)
		return

	var text := body.get_string_from_utf8()
	var parsed = JSON.parse_string(text)
	if parsed == null or not parsed is Dictionary:
		push_warning("AIPlayer: Invalid JSON response. Using heuristic.")
		_report_decision_metrics(true, null)
		_heuristic_fallback(gs)
		return

	var decision: Dictionary = parsed
	var move_dict: Dictionary = decision.get("move", {})
	if move_dict.is_empty():
		push_warning("AIPlayer: No 'move' in response. Using heuristic.")
		_report_decision_metrics(true, null)
		_heuristic_fallback(gs)
		return

	var cmd := _move_to_command(move_dict)
	if cmd.is_empty():
		push_warning("AIPlayer: Could not translate move to command. Using heuristic.")
		_report_decision_metrics(true, null)
		_heuristic_fallback(gs)
		return

	# Store decision for potential rejection context on next call
	_last_rejected_move = move_dict
	if _search_mode and decision.has("chosen_line_id"):
		_commit_chosen_line(str(decision.get("chosen_line_id", "")))

	# Submit the command.  submit_command sets controller.last_command_error if it
	# produced an [ERROR] log, letting us distinguish real rejections from normal
	# "still my turn" situations.
	_submit(cmd)
	if _search_mode and not _committed_line.is_empty():
		# The first command (decision.move) is step 0 of the committed line; it
		# was just submitted above. Remaining steps are replayed by take_turn via
		# _play_committed_step. No pre-hash check on step 0 — we are at the root
		# state the search planned from.
		_committed_line_index = 1

	# Rejection detected: retry immediately (synchronously, before any deferred
	# _trigger_ai_turn fires) so _waiting_for_http is set before the next take_turn().
	if controller.last_command_error:
		_drop_committed_line()
		_last_rejection_reason = "Game engine rejected the command."
		_report_outcome(false, _last_rejection_reason)
		if _retry_count < MAX_RETRIES:
			_report_decision_metrics(false, false)
			_retry_count += 1
			push_warning("AIPlayer: Move rejected — retry %d/%d" % [_retry_count, MAX_RETRIES])
			_request_decision(gs)  # synchronous; sets _waiting_for_http = true
		else:
			_report_decision_metrics(true, false)
			push_warning("AIPlayer: Exhausted %d retries — heuristic fallback." % MAX_RETRIES)
			_heuristic_fallback(gs)
	else:
		_report_decision_metrics(false, true)
		_report_outcome(true)
		_report_accepted_ai_state_event(move_dict, cmd, gs)
		_emit_move_completed(move_dict, gs)
	# If the move was accepted the normal _maybe_trigger_ai() → take_turn() cycle
	# (triggered inside submit_command) handles the next decision.  No extra work needed.


func _emit_move_completed(move_dict: Dictionary, gs: GameState) -> void:
	var turn: int = gs.turn_number if gs != null else 0
	var desc := _describe_move(move_dict)
	ai_move_completed.emit(desc, turn, _move_seq)
	_move_seq += 1


func _describe_move(move: Dictionary) -> String:
	# Human-readable one-liner for the feedback box (e.g. "play card to bf-a").
	var action: String = move.get("action", "")
	var p: Dictionary = move.get("parameters", {})
	match action:
		"play_card":
			var s := "Play %s" % p.get("card_id", "card")
			if p.get("destination", "") not in ["", "base"]:
				s += " to %s" % p["destination"]
			if p.get("target_id", "") != "":
				s += " -> %s" % p["target_id"]
			return s
		"move_unit":
			var ids = p.get("unit_ids", [])
			if ids is String:
				ids = [ids]
			return "Move %s to %s" % [" ".join(ids), p.get("destination", "base")]
		"use_ability":
			return "Use %s" % p.get("card_id", "ability")
		"react":
			return "React with %s" % p.get("card_id", "card")
		"hide_card":
			return "Hide a card at %s" % p.get("battlefield_id", "")
		"assign_damage":
			return "Assign %d damage to %s" % [p.get("amount", 0), p.get("target_id", "")]
		"choose":
			return "Choose %s" % p.get("target_id", "")
		"choose_none":
			return "Choose none"
		"mulligan", "mulligan_keep":
			return "Mulligan"
		"pass":
			return "Pass"
		"end_turn":
			return "End turn"
		_:
			return action if action != "" else "AI move"


# ── Command translation ───────────────────────────────────────────────────────

func _move_to_command(move: Dictionary) -> String:
	var action: String = move.get("action", "")
	var p: Dictionary = move.get("parameters", {})

	match action:
		"mulligan_keep":
			return "mulligan keep"
		"mulligan":
			var ids := " ".join(p.get("card_ids", []))
			return ("mulligan %s" % ids) if ids != "" else "mulligan keep"
		"play_card":
			var cmd := "play %s" % p.get("card_id", "")
			var dest: String = p.get("destination", "")
			if dest != "" and dest != "base":
				cmd += " to %s" % dest
			if p.get("target_id", "") != "":
				cmd += " target %s" % p["target_id"]
			if p.get("from_champion", false):
				cmd += " from champion"
			if p.get("from_hidden", false):
				cmd += " from hidden"
			if p.get("accelerate", false):
				cmd += " accelerate"
			return cmd
		"move_unit":
			var ids = p.get("unit_ids", [])
			if ids is String:
				ids = [ids]
			return "move %s to %s" % [" ".join(ids), p.get("destination", "base")]
		"pass":
			return "pass"
		"end_turn":
			return "end turn"
		"use_ability":
			var cmd := "use %s" % p.get("card_id", "")
			if p.get("target_id", "") != "":
				cmd += " target %s" % p["target_id"]
			return cmd
		"react":
			var cmd := "react %s" % p.get("card_id", "")
			if p.get("target_id", "") != "":
				cmd += " target %s" % p["target_id"]
			return cmd
		"hide_card":
			return "hide %s at %s" % [p.get("card_id", ""), p.get("battlefield_id", "")]
		"assign_damage":
			return "assign %d to %s" % [p.get("amount", 0), p.get("target_id", "")]
		"assign_done":
			return "assign done"
		"choose":
			return "choose %s" % p.get("target_id", "")
		"choose_none":
			return "choose none"
		_:
			return ""


# ── Heuristic fallback ────────────────────────────────────────────────────────

func _heuristic_fallback(gs: GameState) -> void:
	if gs.game_over or not _can_act_now(gs):
		return

	var legal := _legal_moves_for(gs)
	if legal.is_empty():
		return

	# Mulligan: use the local cost/type heuristic (same as the main path)
	if gs.mulligan_phase and not gs.mulligan_done[player_index]:
		_submit(MulliganHeuristicScript.choose_command(gs, player_index, _mulligan_config))
		return

	# Pending prompt: pick first option
	if not gs.pending_prompt.is_empty() and \
	   gs.pending_prompt.get("player_index", -1) == player_index:
		var choices = gs.pending_prompt.get("valid_choices", [])
		_submit("choose %s" % choices[0] if not choices.is_empty() else "choose none")
		return

	# Showdown / chain: pass
	if gs.is_showdown_state() and gs.focus_player_index == player_index:
		_submit("pass")
		return
	if gs.is_closed_chain_state() or not gs.chain.is_empty():
		if gs.priority_player_index == player_index:
			_submit("pass")
		return

	# Combat damage assignment: assign everything to first unit and confirm
	if gs.combat_assignment_active and gs.attacker_player_index == player_index:
		if gs.combat_bf_index >= 0:
			var bf = gs.board.battlefields[gs.combat_bf_index]
			var defenders = bf.units[1 - player_index]
			var remaining = gs.remaining_attacker_might
			for unit in defenders:
				if unit.instance_id not in gs.damage_assignments and remaining > 0:
					_submit("assign %d to %s" % [remaining, unit.instance_id])
					await get_tree().create_timer(0.1).timeout
					remaining = 0
		_submit("assign done")
		return

	# Main phase
	if gs.current_phase == TurnStateMachine.Phase.MAIN and \
	   gs.current_state == TurnStateMachine.State.NEUTRAL_OPEN and \
	   gs.turn_player_index == player_index:
		await _heuristic_main_phase(gs)
		return

	if gs.turn_player_index == player_index:
		_submit("end turn")


func _heuristic_main_phase(gs: GameState) -> void:
	var ps: PlayerState = gs.players[player_index]

	# Play highest-cost affordable card (runes auto-pay on play)
	var played := true
	while played:
		played = false
		var best := _best_playable_card(gs, ps)
		if best != null:
			var dest := _choose_destination(gs)
			var cmd := "play %s" % best.instance_id
			if best.definition.card_type == "unit" and dest != "":
				cmd += " to %s" % dest
			_submit(cmd)
			await get_tree().create_timer(0.2).timeout
			played = true
			if gs.game_over or not _can_act_now(gs):
				return

	# Move ready base units toward objectives
	for unit in _get_ready_units_at_base(gs):
		var target := _best_move_target(gs)
		if target != "":
			_submit("move %s to %s" % [unit.instance_id, target])
			await get_tree().create_timer(0.2).timeout
			if gs.game_over or not _can_act_now(gs):
				return

	await get_tree().create_timer(0.1).timeout
	if _can_act_now(gs) and gs.turn_player_index == player_index:
		_submit("end turn")


func _best_playable_card(gs: GameState, ps: PlayerState) -> CardInstance:
	var best: CardInstance = null
	var best_cost := -1
	for card in ps.hand:
		if card.definition.card_type == "rune" or card.definition.is_reaction:
			continue
		var cost = CostCalculator.compute_play_cost(card, player_index, gs)
		if CostCalculator.can_afford(player_index, cost, gs):
			var ec: int = cost.get("energy", 0)
			if ec > best_cost:
				best_cost = ec
				best = card
	return best


func _choose_destination(gs: GameState) -> String:
	for bf in gs.board.battlefields:
		if bf.controller_index == -1 and bf.units[1 - player_index].is_empty():
			return bf.battlefield_id
	for bf in gs.board.battlefields:
		if bf.controller_index == 1 - player_index:
			return bf.battlefield_id
	return ""


func _best_move_target(gs: GameState) -> String:
	for bf in gs.board.battlefields:
		if bf.controller_index != player_index and bf.units[player_index].is_empty():
			return bf.battlefield_id
	return ""


func _get_ready_units_at_base(gs: GameState) -> Array:
	var result: Array = []
	for u in gs.players[player_index].get_units_at_base():
		if not u.is_exhausted:
			result.append(u)
	return result


# ── Search line execution ──────────────────────────────────────────────────────

func _should_run_search(gs: GameState) -> bool:
	return _search_mode \
		and _committed_line.is_empty() \
		and _last_rejected_move.is_empty() \
		and gs.turn_player_index == player_index \
		and gs.current_phase == TurnStateMachine.Phase.MAIN \
		and gs.current_state == TurnStateMachine.State.NEUTRAL_OPEN


# Reactive search fires when the AI holds a response window in a chain or
# showdown — on EITHER player's turn. This covers two cases the user asked for:
#   1. The opponent interferes mid-line (their reaction opens a chain / contests
#      a showdown): the committed line diverges, take_turn falls through here,
#      and we search the AI's responses until the window resolves.
#   2. It is the opponent's turn and the AI gets a chance to interfere: same
#      window, same reactive search.
# It deliberately does NOT require the AI's own turn. pending_choice / mulligan /
# combat_assignment are left to the staged agent (not chain/showdown windows).
func _should_run_reactive_search(gs: GameState) -> bool:
	if not _search_mode or not _committed_line.is_empty() or not _last_rejected_move.is_empty():
		return false
	if not gs.pending_prompt.is_empty() or gs.combat_assignment_active:
		return false
	if gs.is_closed_chain_state() and gs.priority_player_index == player_index:
		return true
	if gs.current_state == TurnStateMachine.State.SHOWDOWN_OPEN and gs.focus_player_index == player_index:
		return true
	return false


func _commit_chosen_line(line_id: String) -> void:
	_committed_line = {}
	_committed_line_index = 0
	for line in _candidate_lines:
		if str(line.get("line_id", "")) == line_id:
			_committed_line = line
			return


# Play the next step of the committed line. Each step carries the state hash
# the search expected to see at this point (pre_hash). If the live state no
# longer matches — the opponent interacted, or anything diverged from the
# simulated "if-unanswered" line — the line is abandoned.
# Intermediate steps (the AI's own target choices / showdown-focus passes) are
# regular steps here, so the line carries across them without a fresh search.
#
# Returns true if a committed step was submitted (the line is still in control);
# false if the line is finished or diverged and the caller should request a
# fresh decision. Returning false instead of dead-ending is what prevents the AI
# from hanging once its planned turn is exhausted but it is later asked to act
# again (e.g. passing an opponent-initiated showdown).
func _play_committed_step(gs: GameState) -> bool:
	var moves: Array = _committed_line.get("moves", [])
	if _committed_line_index >= moves.size():
		_drop_committed_line()
		return false
	var hashes: Array = _committed_line.get("expected_pre_hashes", [])
	var idx := _committed_line_index
	if idx < hashes.size():
		var expected := str(hashes[idx])
		if expected != "" and _live_hash(gs) != expected:
			_drop_committed_line()
			return false
	var cmd := str(moves[idx])
	_submit(cmd)
	_committed_line_index += 1
	if controller.last_command_error:
		_drop_committed_line()
		return false
	return true


func _drop_committed_line() -> void:
	_committed_line = {}
	_committed_line_index = 0


func _live_hash(gs: GameState) -> String:
	return ScoreModel.structural_hash(ScoreModel.snapshot(gs, player_index))


# ── Helpers ───────────────────────────────────────────────────────────────────

func _can_act_now(gs: GameState) -> bool:
	if gs.mulligan_phase:
		return not gs.mulligan_done[player_index]
	return gs.can_player_act(player_index)


func _legal_moves_for(gs: GameState) -> Array:
	return LegalMoveEnumerator.enumerate(gs, player_index)


func _submit(cmd: String) -> void:
	if controller and not controller.gs.game_over:
		controller.submit_command(player_index, cmd)
		controller.board_updated.emit()


# ── Phase 1: outcome reporting, game-over, opponent tracking ──────────────────

func _on_session_changed(new_id: String) -> void:
	if new_id.is_empty() or new_id == _current_game_id:
		return
	_current_game_id = new_id
	_game_over_reported = false
	_retry_count = 0
	_last_rejected_move = {}
	_last_rejection_reason = ""
	_move_seq = 0
	_drop_committed_line()


func _active_game_id(gs: GameState) -> String:
	if gs != null and not gs.game_session_id.is_empty():
		return gs.game_session_id
	return _current_game_id


func _report_outcome(accepted: bool, rejection_reason: String = "") -> void:
	var game_id := _active_game_id(controller.gs if controller else null)
	if game_id.is_empty():
		return
	var body := {
		"game_id": game_id,
		"accepted": accepted,
	}
	if not accepted and not rejection_reason.is_empty():
		body["rejection_reason"] = rejection_reason
	_fire_and_forget(AGENT_URL.replace("/decision", "/outcome"), body)


func _report_decision_metrics(heuristic_fallback: bool, accepted) -> void:
	# Engine-observed reliability metrics for one AI decision attempt (eval track).
	# accepted may be true / false / null (Variant) to mirror "unknown".
	var gs: GameState = controller.gs if controller else null
	var game_id := _active_game_id(gs)
	if game_id.is_empty():
		return
	var latency_ms := 0
	if _decision_start_ms > 0:
		latency_ms = Time.get_ticks_msec() - _decision_start_ms
	var body := {
		"game_id": game_id,
		"turn": (gs.turn_number if gs != null else 0),
		"decision_type": _pending_brief_state.get("decision_type", ""),
		"latency_ms": latency_ms,
		"rejection_retries": _retry_count,
		"heuristic_fallback": heuristic_fallback,
	}
	if accepted != null:
		body["accepted"] = accepted
	_fire_and_forget(AGENT_URL.replace("/decision", "/decision_metrics"), body)


func _report_accepted_ai_state_event(move_dict: Dictionary, command: String, gs: GameState) -> void:
	if not _should_log_ai_state_event(move_dict):
		return
	var game_id := _active_game_id(gs)
	if game_id.is_empty():
		return
	var state := BriefStateSerializer.serialize(gs, player_index)
	_fire_and_forget(AGENT_URL.replace("/decision", "/game_state_event"), {
		"game_id": game_id,
		"turn": gs.turn_number,
		"event_type": "ai_decision",
		"actor": "ai",
		"description": _describe_move(move_dict),
		"command": command,
		"decision_type": _pending_brief_state.get("decision_type", ""),
		"state": state,
	})


func _should_log_ai_state_event(move_dict: Dictionary) -> bool:
	var legal_moves = _pending_brief_state.get("legal_moves", [])
	if legal_moves is Array and legal_moves.size() <= 1:
		return false
	var action: String = move_dict.get("action", "")
	return action not in ["pass", "end_turn"]


func _report_game_state_event(event_type: String, description: String, include_state: bool) -> void:
	var gs: GameState = controller.gs if controller else null
	var game_id := _active_game_id(gs)
	if game_id.is_empty():
		return
	var body := {
		"game_id": game_id,
		"turn": (gs.turn_number if gs != null else 0),
		"event_type": event_type,
		"description": description,
	}
	if include_state and gs != null:
		body["state"] = BriefStateSerializer.serialize(gs, player_index)
	_fire_and_forget(AGENT_URL.replace("/decision", "/game_state_event"), body)


func _on_board_updated() -> void:
	if _game_over_reported or controller == null or controller.gs == null:
		return
	var gs = controller.gs
	if not gs.game_over or gs.winner_index < 0:
		return
	_game_over_reported = true
	var game_id := _active_game_id(gs)
	var first_player := -1
	if controller and controller.has_method("_determine_first_player"):
		first_player = controller._determine_first_player()
	var body := {
		"game_id": game_id,
		"winner_index": gs.winner_index,
		"my_player_index": player_index,
		"my_score": gs.players[player_index].score,
		"opp_score": gs.players[1 - player_index].score,
		"total_turns": gs.turn_number,
		"first_player_index": first_player,
		"seed": gs.rng_seed,
	}
	_fire_and_forget(AGENT_URL.replace("/decision", "/game_over"), body)


func _on_card_event(event: String, card: CardInstance, energy_spent: int, owner_index: int) -> void:
	# Forward this seat's own card lifecycle events to the agent for per-card
	# statistics. Only own-seat cards are reported so two-seat self-play (both
	# AIPlayers on one controller) doesn't double-count, and seats stay separable.
	if owner_index != player_index:
		return
	if card == null or card.definition == null:
		return
	var gs: GameState = controller.gs if controller else null
	var game_id := _active_game_id(gs)
	if game_id.is_empty():
		return
	_fire_and_forget(AGENT_URL.replace("/decision", "/card_event"), {
		"game_id": game_id,
		"turn": gs.turn_number if gs != null else 0,
		"card_def_id": card.definition.id,
		"instance_id": card.instance_id,
		"event": event,
		"my_player_index": player_index,
		"energy_spent": energy_spent,
	})


func _on_game_log_message(text: String) -> void:
	# Detect visible opponent commands in the format "[P{n}] > {command}"
	var opp_index := 1 - player_index
	var prefix := "[P%d] > " % (opp_index + 1)
	if text.begins_with(prefix):
		var cmd := text.substr(prefix.length()).strip_edges()
		var description := _parse_opponent_command(cmd)
		var gs: GameState = controller.gs if controller else null
		var game_id := _active_game_id(gs)
		if not description.is_empty() and not game_id.is_empty():
			var turn: int = gs.turn_number if gs != null else 0
			_fire_and_forget(AGENT_URL.replace("/decision", "/opponent_action"), {
				"game_id": game_id,
				"turn": turn,
				"action": description,
			})
			_report_game_state_event("opponent_action", description, false)
		return

	if text.begins_with("> Resolving:"):
		_report_game_state_event("chain_resolved", text.trim_prefix("> ").strip_edges(), true)
	elif text.begins_with("> Combat at ") and text.ends_with(" resolved"):
		_report_game_state_event("combat_resolved", text.trim_prefix("> ").strip_edges(), true)


func _parse_opponent_command(cmd: String) -> String:
	var tokens := cmd.split(" ", false)
	if tokens.is_empty():
		return ""
	match tokens[0]:
		"play":
			if tokens.size() < 2:
				return ""
			var card_id := tokens[1]
			var dest := ""
			var to_idx := tokens.find("to")
			if to_idx >= 0 and to_idx + 1 < tokens.size():
				dest = tokens[to_idx + 1]
			return "played %s%s" % [card_id, (" to " + dest) if dest else ""]
		"move":
			var to_idx := tokens.find("to")
			if to_idx < 0 or to_idx + 1 >= tokens.size():
				return ""
			var dest := tokens[to_idx + 1]
			var unit_count := to_idx - 1
			var label := "unit" if unit_count <= 1 else "%d units" % unit_count
			return "moved %s to %s" % [label, dest]
		"end":
			return "ended their turn"
		"pass":
			return "passed"
		"use":
			if tokens.size() < 2:
				return ""
			return "used ability %s%s" % [tokens[1], _target_suffix(tokens)]
		"react":
			if tokens.size() < 2:
				return ""
			return "played reaction %s%s" % [tokens[1], _target_suffix(tokens)]
		"choose":
			if tokens.size() < 2:
				return ""
			return "chose %s" % tokens[1]
		_:
			return ""


func _target_suffix(tokens: Array) -> String:
	var target_idx := tokens.find("target")
	if target_idx >= 0 and target_idx + 1 < tokens.size():
		return " targeting %s" % tokens[target_idx + 1]
	return ""


func _fire_and_forget(url: String, body: Dictionary) -> void:
	var http := HTTPRequest.new()
	add_child(http)
	http.request_completed.connect(func(_r, _c, _h, _b): http.queue_free())
	http.request(url, ["Content-Type: application/json"],
		HTTPClient.METHOD_POST, JSON.stringify(body))
