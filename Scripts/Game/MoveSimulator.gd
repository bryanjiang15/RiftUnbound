class_name MoveSimulator
extends RefCounted

# Phase 2.5 — Engine-truth simulation.
#
# Applies a candidate move (or a scripted multi-step line of the AI's own moves)
# to a *clone* of the live GameState, drives the chain/combat to a stable
# (quiescent) point assuming the opponent does not respond, and serializes the
# resulting decision-relevant delta. The live GameState is never touched.
#
# The returned dictionaries match the SimResult / LineResult / ResolvedState /
# ResponseWindow schemas in ai_agent/schemas.py. Empty collections are omitted so
# the presence of a key means "something of this kind changed."
#
# Snapshot + scoring-feature math lives in ScoreModel; this file owns only the
# simulation control flow.
#
# See docs/Phase2_5_Engine_Truth_Simulation.md.

const GameControllerScript = preload("res://Scripts/Game/GameController.gd")
const TriggerDispatcherScript = preload("res://Scripts/Game/TriggerDispatcher.gd")
const ScoreModelScript = preload("res://Scripts/Game/ScoreModel.gd")

# Bound on engine steps (auto-passes / prompt resolutions) per drive so a sim can
# never hang on a pathological loop.
const PLY_BUDGET := 24

# Seat the simulation treats as the AI. Public so the search can target a seat
# without reaching into private state.
var ai_index: int = 1


# ── Public API ────────────────────────────────────────────────────────────────


# Simulate a single move to quiescence. Returns a SimResult dict.
func simulate_move(live_gs: GameState, seat: int, move_command: String) -> Dictionary:
	var line := simulate_line(live_gs, seat, [move_command])
	var result := {"legal": line.get("legal", false)}
	if line.has("error"):
		result["error"] = line["error"]
	if line.has("resolved_if_unanswered"):
		result["resolved_if_unanswered"] = line["resolved_if_unanswered"]
	var windows: Array = line.get("opponent_windows", [])
	if not windows.is_empty():
		result["response_window"] = windows[0]
	if line.has("first_illegal_move") and line["first_illegal_move"] != null:
		result["legal"] = false
	return result


# Simulate a scripted line of the AI's own moves. Returns a LineResult dict.
func simulate_line(live_gs: GameState, seat: int, move_commands: Array) -> Dictionary:
	ai_index = seat
	var sc: GameController = build_sim_controller(live_gs)
	if sc == null:
		return {"legal": false, "error": "failed to clone game state"}

	var before := ScoreModelScript.snapshot(sc.gs, ai_index)
	var applied: Array = []
	var windows: Array = []
	var stopped_reason := "quiescence"
	var first_illegal = null

	for cmd in move_commands:
		var cmd_str := str(cmd)
		sc.submit_command(ai_index, cmd_str)
		if sc.last_command_error:
			first_illegal = cmd_str
			stopped_reason = "illegal"
			break
		applied.append(cmd_str)
		stopped_reason = advance_to_quiescence(sc, cmd_str, windows)
		if stopped_reason == "game_over":
			break

	var result := {
		"legal": first_illegal == null,
		"applied_moves": applied,
		"stopped_reason": stopped_reason,
	}
	if first_illegal != null:
		result["first_illegal_move"] = first_illegal
		# A line that became illegal mid-way still reports the partial resolution
		# so the agent sees how far it got.
	var after := ScoreModelScript.snapshot(sc.gs, ai_index)
	result["resolved_if_unanswered"] = build_delta(before, after, sc.gs)
	if not windows.is_empty():
		result["opponent_windows"] = windows
	# Free the simulated controller Node (created via .new(), never tree-attached).
	sc.free()
	return result


# ── Sim controller setup ──────────────────────────────────────────────────────


func build_sim_controller(live_gs: GameState) -> GameController:
	var clone: GameState = live_gs.clone()
	if clone == null:
		return null
	var sc: GameController = GameControllerScript.new()
	sc.skip_auto_start = true
	sc._ai_player_index = -1
	# Simulation controllers replay hypothetical lines (search / brief-state
	# windows); their log output is internal and must never echo to the console.
	# Suppress errors too — illegal probes during simulation are expected noise.
	sc.quiet_logs = true
	sc.quiet_errors = true
	sc.trigger_dispatcher = TriggerDispatcherScript.new()
	sc.log_lines.clear()
	sc.gs = clone
	# Force deterministic auto combat-damage assignment so combat resolves
	# without an interactive manual-assignment prompt.
	sc.gs.auto_combat_damage = true
	return sc


# ── Quiescence driver ─────────────────────────────────────────────────────────
#
# After the AI's scripted move is applied, resolve the chain / showdown / combat
# by auto-passing for whichever seat currently holds priority or focus — the
# deterministic "if-unanswered" line. Every time the seat being passed for is the
# OPPONENT, a response window is recorded (a class-C branch point the agent must
# reason about). Opponent pending-prompts are auto-resolved with the first valid
# choice.
#
# The AI's OWN forced choices are resolved inline (not branched into the beam, so
# they never crowd out strategically distinct lines). When a choice_ranker is
# supplied and the prompt offers more than one option (e.g. which card to
# discard, which target to pick), the option that yields the highest-scoring
# settled board is chosen greedily; otherwise the first valid option is used.
func advance_to_quiescence(sc: GameController, after_move: String, windows: Array, ai_steps: Array = [], choice_ranker: Callable = Callable()) -> String:
	var steps := 0
	while steps < PLY_BUDGET:
		steps += 1

		if sc.gs.game_over:
			return "game_over"

		# Resolve any outstanding choice prompt first.
		if not sc.gs.pending_prompt.is_empty():
			var prompt_pi: int = sc.gs.pending_prompt.get("player_index", ai_index)
			if prompt_pi == ai_index:
				# The AI's OWN forced choice — resolve it (greedily when a ranker
				# is given) and capture it as an explicit line step (command +
				# human-readable context) so the executor replays it instead of
				# treating it as an unexpected divergence.
				var pre_hash := ScoreModelScript.structural_hash(ScoreModelScript.snapshot(sc.gs, ai_index))
				var cc := _resolve_ai_prompt(sc, choice_ranker)
				if sc.last_command_error:
					return "quiescence"
				ai_steps.append({
					"command": cc["command"], "context": cc["context"],
					"kind": "intermediate", "pre_hash": pre_hash,
				})
			else:
				_resolve_prompt(sc)
				if sc.last_command_error:
					return "quiescence"
			continue

		var seat := _acting_seat(sc.gs)
		if seat < 0:
			return "quiescence"

		if seat == ai_index:
			# The AI's own pass in a showdown/chain window — record it as an
			# intermediate step so the planned line carries the pass forward.
			var pre_hash := ScoreModelScript.structural_hash(ScoreModelScript.snapshot(sc.gs, ai_index))
			var ctx := _describe_ai_pass(sc.gs)
			sc.submit_command(seat, "pass")
			if sc.last_command_error:
				return "quiescence"
			ai_steps.append({
				"command": "pass", "context": ctx,
				"kind": "intermediate", "pre_hash": pre_hash,
			})
		else:
			_record_window(sc.gs, after_move, windows)
			sc.submit_command(seat, "pass")
			if sc.last_command_error:
				return "quiescence"

	return "ply_budget"


# Returns the seat currently obliged to act in a chain/showdown/combat context,
# or -1 if the state is quiescent (neutral-open / nobody forced to respond).
func _acting_seat(gs: GameState) -> int:
	if gs.combat_assignment_active:
		# Auto combat-damage is forced on, so this should not trigger; if it does
		# (AI is the manual attacker) treat as quiescent — it is the AI's choice.
		return -1
	if gs.is_closed_chain_state():
		return gs.priority_player_index
	if gs.current_state == TurnStateMachine.State.SHOWDOWN_OPEN:
		return gs.focus_player_index
	return -1


func _record_window(gs: GameState, after_move: String, windows: Array) -> void:
	var classes: Array = []
	if gs.is_closed_chain_state():
		classes = ["Reaction"]
	elif gs.current_state == TurnStateMachine.State.SHOWDOWN_OPEN:
		classes = ["Action", "Reaction"]
	var opp: PlayerState = gs.players[1 - ai_index]
	windows.append({
		"after_move": after_move,
		"opponent_may_respond": true,
		"legal_response_classes": classes,
		"opponent_unknown_cards": opp.hand.size(),
		"opponent_potential_energy": ScoreModelScript.ready_runes(opp),
		"note": "auto-passed; opponent could respond here (contested branch not resolved)",
	})


# Resolve a pending choice prompt with the first valid option (mirrors the
# engine's deterministic default). Used for both seats so the board resolves.
func _resolve_prompt(sc: GameController) -> void:
	var prompt: Dictionary = sc.gs.pending_prompt
	var prompt_pi: int = prompt.get("player_index", ai_index)
	var ptype: String = prompt.get("type", "")
	var choice := "none"
	var valid: Array = prompt.get("valid_choices", [])
	if ptype == "choose_optional":
		choice = "yes"
	elif not valid.is_empty():
		var v = valid[0]
		choice = v.instance_id if v is CardInstance else str(v)
	sc.submit_command(prompt_pi, "choose %s" % choice)


# Resolve the AI's own pending prompt and return the {command, context} that was
# applied. With a valid choice_ranker and more than one option, the option whose
# settled board scores highest is chosen greedily (so e.g. the AI discards the
# card that best preserves its position rather than valid_choices[0]); otherwise
# it mirrors _resolve_prompt's deterministic first-valid selection.
func _resolve_ai_prompt(sc: GameController, choice_ranker: Callable) -> Dictionary:
	var prompt: Dictionary = sc.gs.pending_prompt
	var prompt_pi: int = prompt.get("player_index", ai_index)
	var ptype: String = prompt.get("type", "")
	var valid: Array = prompt.get("valid_choices", [])
	var choice := "none"
	if ptype == "choose_optional":
		choice = "yes"
	elif valid.size() > 1 and choice_ranker.is_valid():
		choice = _best_choice(sc, valid, choice_ranker)
	elif not valid.is_empty():
		var v = valid[0]
		choice = v.instance_id if v is CardInstance else str(v)
	var ctx := _describe_prompt(prompt, choice)
	sc.submit_command(prompt_pi, "choose %s" % choice)
	return {"command": "choose %s" % choice, "context": ctx}


# Pick the prompt option whose fully-settled board scores highest. Each candidate
# is evaluated on a throwaway clone (resolved to quiescence with the deterministic
# first-valid policy for any nested choices) so the score reflects the option's
# real consequences. Falls back to the first option if none resolve cleanly.
func _best_choice(sc: GameController, valid: Array, choice_ranker: Callable) -> String:
	var best_id := ""
	var best_score := -INF
	for v in valid:
		var cid: String = v.instance_id if v is CardInstance else str(v)
		var cand: GameController = build_sim_controller(sc.gs)
		if cand == null:
			continue
		cand.submit_command(ai_index, "choose %s" % cid)
		if not cand.last_command_error:
			advance_to_quiescence(cand, "", [], [])
			var score: float = choice_ranker.call(cand.gs)
			if score > best_score:
				best_score = score
				best_id = cid
		cand.free()
	if best_id == "":
		var v0 = valid[0]
		best_id = v0.instance_id if v0 is CardInstance else str(v0)
	return best_id


func _describe_prompt(prompt: Dictionary, choice: String) -> String:
	var ptype: String = prompt.get("type", "")
	var src = prompt.get("source", null)
	var src_name := ""
	if src != null and src is CardInstance:
		src_name = src.definition.name
	match ptype:
		"choose_target":
			if src_name != "":
				return "choose target '%s' for %s's ability" % [choice, src_name]
			return "choose target '%s' for a triggered ability" % choice
		"choose_battlefield":
			return "choose battlefield '%s' to resolve its scoring" % choice
		"choose_discard":
			if src_name != "":
				return "discard '%s' (required by %s)" % [choice, src_name]
			return "discard '%s'" % choice
		"choose_optional":
			if src_name != "":
				return "accept %s's optional ability" % src_name
			return "accept an optional ability"
		_:
			return "resolve choice: choose '%s'" % choice


func _describe_ai_pass(gs: GameState) -> String:
	if gs.is_closed_chain_state():
		return "pass priority — let the chain resolve"
	if gs.current_state == TurnStateMachine.State.SHOWDOWN_OPEN:
		return "pass showdown focus — let the showdown resolve"
	return "pass"


# ── State delta ───────────────────────────────────────────────────────────────


func build_delta(before: Dictionary, after: Dictionary, gs: GameState) -> Dictionary:
	var delta: Dictionary = {}

	# ── headline: win condition ──
	delta["wins_game"] = gs.game_over and gs.winner_index == ai_index
	delta["my_score_after"] = after["my_score"]
	delta["opp_score_after"] = after["opp_score"]

	var conquer := false
	var bf_changes: Dictionary = {}
	for bf_id in after["bf"]:
		var before_ctrl: int = before["bf"].get(bf_id, -1)
		var after_ctrl: int = after["bf"][bf_id]
		if before_ctrl != after_ctrl:
			bf_changes[bf_id] = {
				"controller_before": _ctrl_label(before_ctrl),
				"controller_after": _ctrl_label(after_ctrl),
			}
			if after_ctrl == ai_index:
				conquer = true
	delta["conquer"] = conquer
	if not bf_changes.is_empty():
		delta["battlefields"] = bf_changes

	# ── board deltas ──
	var killed: Array = []
	var my_surviving: Array = []
	var damaged: Array = []
	for inst_id in before["units"]:
		if not after["units"].has(inst_id):
			killed.append(inst_id)
	for inst_id in after["units"]:
		var au: Dictionary = after["units"][inst_id]
		if before["units"].has(inst_id):
			var bu: Dictionary = before["units"][inst_id]
			if au["damage"] > bu["damage"]:
				damaged.append({"id": inst_id, "damage": au["damage"]})
		if au["owner"] == ai_index and au["location"] != "base":
			my_surviving.append(inst_id)
	if not killed.is_empty():
		delta["units_killed"] = killed
	if not damaged.is_empty():
		delta["units_damaged"] = damaged
	if not my_surviving.is_empty():
		delta["my_units_surviving"] = my_surviving

	var trade := _trade_string(before, after, killed)
	if trade != "":
		delta["trade"] = trade

	# ── resources / tempo ──
	var drawn: int = after["my_hand"] - before["my_hand"]
	if drawn > 0:
		delta["cards_drawn"] = drawn
	var spent: int = before["my_energy"] - after["my_energy"]
	if spent > 0:
		delta["energy_spent"] = spent

	delta["next_decision"] = _next_decision(gs)
	return delta


func _ctrl_label(idx: int) -> String:
	if idx == ai_index:
		return "me"
	if idx == 1 - ai_index:
		return "opponent"
	return "neutral"


func _trade_string(before: Dictionary, after: Dictionary, killed: Array) -> String:
	if killed.is_empty():
		return ""
	var mine: Array = []
	var theirs: Array = []
	for inst_id in killed:
		var u: Dictionary = before["units"][inst_id]
		var label := "%s (%d might)" % [inst_id, u["might"]]
		if u["owner"] == ai_index:
			mine.append(label)
		else:
			theirs.append(label)
	var parts: Array = []
	if mine.is_empty():
		parts.append("I lose nothing")
	else:
		parts.append("I lose " + ", ".join(mine))
	if theirs.is_empty():
		parts.append("they lose nothing")
	else:
		parts.append("they lose " + ", ".join(theirs))
	return "; ".join(parts)


func _next_decision(gs: GameState) -> String:
	if gs.game_over:
		return "game over"
	if gs.can_player_act(ai_index):
		if gs.turn_player_index == ai_index and gs.current_state == TurnStateMachine.State.NEUTRAL_OPEN:
			return "your main phase"
		return "your decision"
	return "opponent's turn"
