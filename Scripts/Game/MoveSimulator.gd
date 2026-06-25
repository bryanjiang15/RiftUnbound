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
# See docs/Phase2_5_Engine_Truth_Simulation.md.

const GameControllerScript = preload("res://Scripts/Game/GameController.gd")
const TriggerDispatcherScript = preload("res://Scripts/Game/TriggerDispatcher.gd")

# Bound on engine steps (auto-passes / prompt resolutions) per drive so a sim can
# never hang on a pathological loop.
const PLY_BUDGET := 24

# Board-presence keywords surfaced to the scorer. These are the generic, unit
# state keywords whose presence on field/base units carries positional value
# (combat math, mobility, protection) independent of any specific card.
const SCORED_KEYWORDS := ["assault", "shield", "tank", "ganking", "deflect", "deathknell"]

var _ai_index: int = 1


# ── Public API ────────────────────────────────────────────────────────────────


# Simulate a single move to quiescence. Returns a SimResult dict.
func simulate_move(live_gs: GameState, ai_index: int, move_command: String) -> Dictionary:
	var line := simulate_line(live_gs, ai_index, [move_command])
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
func simulate_line(live_gs: GameState, ai_index: int, move_commands: Array) -> Dictionary:
	_ai_index = ai_index
	var sc: GameController = _build_sim_controller(live_gs)
	if sc == null:
		return {"legal": false, "error": "failed to clone game state"}

	var before := _snapshot(sc.gs)
	var applied: Array = []
	var windows: Array = []
	var stopped_reason := "quiescence"
	var first_illegal = null

	for cmd in move_commands:
		var cmd_str := str(cmd)
		sc.submit_command(_ai_index, cmd_str)
		if sc.last_command_error:
			first_illegal = cmd_str
			stopped_reason = "illegal"
			break
		applied.append(cmd_str)
		stopped_reason = _advance_to_quiescence(sc, cmd_str, windows)
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
	var after := _snapshot(sc.gs)
	result["resolved_if_unanswered"] = _build_delta(before, after, sc.gs)
	if not windows.is_empty():
		result["opponent_windows"] = windows
	return result


# ── Sim controller setup ──────────────────────────────────────────────────────


func _build_sim_controller(live_gs: GameState) -> GameController:
	var clone: GameState = live_gs.clone()
	if clone == null:
		return null
	var sc: GameController = GameControllerScript.new()
	sc.skip_auto_start = true
	sc._ai_player_index = -1
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
# choice; the AI's own pending prompts are likewise auto-resolved so the sim
# yields a concrete resolved board.
func _advance_to_quiescence(sc: GameController, after_move: String, windows: Array, ai_steps: Array = []) -> String:
	var steps := 0
	while steps < PLY_BUDGET:
		steps += 1

		if sc.gs.game_over:
			return "game_over"

		# Resolve any outstanding choice prompt first.
		if not sc.gs.pending_prompt.is_empty():
			var prompt_pi: int = sc.gs.pending_prompt.get("player_index", _ai_index)
			if prompt_pi == _ai_index:
				# The AI's OWN forced choice — capture it as an explicit line step
				# (command + human-readable context) so the executor can replay it
				# instead of treating it as an unexpected divergence.
				var pre_hash := MoveSimulator.structural_hash(_snapshot(sc.gs))
				var cc := _ai_prompt_step(sc)
				_resolve_prompt(sc)
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

		if seat == _ai_index:
			# The AI's own pass in a showdown/chain window — record it as an
			# intermediate step so the planned line carries the pass forward.
			var pre_hash := MoveSimulator.structural_hash(_snapshot(sc.gs))
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
	var opp: PlayerState = gs.players[1 - _ai_index]
	windows.append({
		"after_move": after_move,
		"opponent_may_respond": true,
		"legal_response_classes": classes,
		"opponent_unknown_cards": opp.hand.size(),
		"opponent_potential_energy": _ready_runes(opp),
		"note": "auto-passed; opponent could respond here (contested branch not resolved)",
	})


# Resolve a pending choice prompt with the first valid option (mirrors the
# engine's deterministic default). Used for both seats so the board resolves.
func _resolve_prompt(sc: GameController) -> void:
	var prompt: Dictionary = sc.gs.pending_prompt
	var prompt_pi: int = prompt.get("player_index", _ai_index)
	var ptype: String = prompt.get("type", "")
	var choice := "none"
	var valid: Array = prompt.get("valid_choices", [])
	if ptype == "choose_optional":
		choice = "yes"
	elif not valid.is_empty():
		var v = valid[0]
		choice = v.instance_id if v is CardInstance else str(v)
	sc.submit_command(prompt_pi, "choose %s" % choice)


# Build the {command, context} the AI uses to resolve its own pending prompt,
# mirroring _resolve_prompt's deterministic first-valid-choice selection but also
# producing a human-readable label explaining what the choice is for.
func _ai_prompt_step(sc: GameController) -> Dictionary:
	var prompt: Dictionary = sc.gs.pending_prompt
	var ptype: String = prompt.get("type", "")
	var choice := "none"
	var valid: Array = prompt.get("valid_choices", [])
	if ptype == "choose_optional":
		choice = "yes"
	elif not valid.is_empty():
		var v = valid[0]
		choice = v.instance_id if v is CardInstance else str(v)
	return {"command": "choose %s" % choice, "context": _describe_prompt(prompt, choice)}


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


# ── State snapshot + delta ────────────────────────────────────────────────────


func _snapshot(gs: GameState) -> Dictionary:
	var me: PlayerState = gs.players[_ai_index]
	var opp: PlayerState = gs.players[1 - _ai_index]
	var bf: Dictionary = {}
	var bf_scored: Array = []
	for i in range(gs.board.battlefields.size()):
		var entry = gs.board.battlefields[i]
		bf[entry.battlefield_id] = entry.controller_index
		if i in me.battlefields_scored_this_turn:
			bf_scored.append(entry.battlefield_id)
	var units: Dictionary = {}
	var my_might := 0
	var opp_might := 0
	for u in gs.all_units_on_board():
		var might := u.get_current_might()
		units[u.instance_id] = {
			"owner": u.owner_index,
			"location": u.location,
			"might": might,
			"damage": u.damage,
			"exhausted": u.is_exhausted,
			"stunned": u.is_stunned,
			"keywords": _unit_keywords(u),
		}
		if u.owner_index == _ai_index:
			my_might += might
		else:
			opp_might += might
	for u in me.get_units_at_base():
		var might := u.get_current_might()
		units[u.instance_id] = {
			"owner": u.owner_index, "location": "base",
			"might": might, "damage": u.damage,
			"exhausted": u.is_exhausted, "stunned": u.is_stunned,
			"keywords": _unit_keywords(u),
		}
		my_might += might
	for u in opp.get_units_at_base():
		var might := u.get_current_might()
		units[u.instance_id] = {
			"owner": u.owner_index, "location": "base",
			"might": might, "damage": u.damage,
			"exhausted": u.is_exhausted, "stunned": u.is_stunned,
			"keywords": _unit_keywords(u),
		}
		opp_might += might
	return {
		"ai_index": _ai_index,
		"my_score": me.score,
		"opp_score": opp.score,
		"victory_score": gs.victory_score,
		"game_over": gs.game_over,
		"winner_index": gs.winner_index,
		"my_hand": me.hand.size(),
		"opp_hand": opp.hand.size(),
		"my_energy": me.rune_pool.energy,
		"my_ready_runes": _ready_runes(me),
		"opp_ready_runes": _ready_runes(opp),
		"my_unit_might": my_might,
		"opp_unit_might": opp_might,
		"my_cards_played": me.cards_played_this_turn,
		"my_cards_discarded": me.cards_discarded_count,
		"my_hand_reactive": _reactive_hand_costs(me),
		"my_ready_rune_domains": _ready_rune_domains(me),
		"bf": bf,
		"bf_scored": bf_scored,
		"units": units,
	}


# Costs of the Action/Reaction cards in hand — the cards the AI could play during
# the opponent's turn (Action in showdowns, Reaction in closed states). Each entry
# is {energy, power:[{domain, amount}]}. Used to gauge reactive readiness.
func _reactive_hand_costs(ps: PlayerState) -> Array:
	var out: Array = []
	for card in ps.hand:
		var def: CardDefinition = card.definition
		if def == null:
			continue
		if not (def.is_action or def.is_reaction):
			continue
		out.append({"energy": def.energy_cost, "power": def.power_cost.duplicate(true)})
	return out


# Domains of the player's ready (un-exhausted) channeled runes. Each ready rune is
# a flexible resource: it can tap for 1 energy or recycle for 1 power of its domain.
func _ready_rune_domains(ps: PlayerState) -> Array:
	var out: Array = []
	for rune in ps.channeled_runes:
		if rune.is_exhausted:
			continue
		var def: CardDefinition = rune.definition
		var domain := "any"
		if def != null and def.domain is Array and not def.domain.is_empty():
			domain = str(def.domain[0])
		out.append(domain)
	return out


# Tracked board-presence keywords currently on a unit, used by the scorer to
# value generic unit qualities (combat keywords, mobility) on field/base.
func _unit_keywords(u: CardInstance) -> Array:
	var kws: Array = []
	for kw_id in SCORED_KEYWORDS:
		if u.has_keyword(kw_id):
			kws.append(kw_id)
	return kws


# Flatten a search line into the flat feature dict the scorer consumes. Merges
# leaf-state features (positional) with action/outcome deltas measured against
# the root snapshot and the line's executed steps. Keeping this here (rather than
# in ScoringProfile) keeps the scorer decoupled from snapshot internals.
func _build_score_features(root_snap: Dictionary, leaf_snap: Dictionary, steps: Array) -> Dictionary:
	var ai_index := int(leaf_snap.get("ai_index", _ai_index))
	var features: Dictionary = {}

	# ── passthrough (terminal + battlefield weighting + end-of-turn) ──
	features["ai_index"] = ai_index
	features["game_over"] = bool(leaf_snap.get("game_over", false))
	features["winner_index"] = int(leaf_snap.get("winner_index", -1))
	features["my_score"] = int(leaf_snap.get("my_score", 0))
	features["opp_score"] = int(leaf_snap.get("opp_score", 0))
	features["victory_score"] = int(leaf_snap.get("victory_score", 8))
	features["bf"] = leaf_snap.get("bf", {})
	features["bf_scored"] = leaf_snap.get("bf_scored", [])
	features["my_hand"] = int(leaf_snap.get("my_hand", 0))
	features["my_ready_runes"] = int(leaf_snap.get("my_ready_runes", 0))

	# ── state diffs (me vs opponent at the leaf) ──
	features["score_diff"] = int(leaf_snap.get("my_score", 0)) - int(leaf_snap.get("opp_score", 0))
	features["unit_might_diff"] = int(leaf_snap.get("my_unit_might", 0)) - int(leaf_snap.get("opp_unit_might", 0))
	features["cards_in_hand_diff"] = int(leaf_snap.get("my_hand", 0)) - int(leaf_snap.get("opp_hand", 0))
	features["runes_available_diff"] = int(leaf_snap.get("my_ready_runes", 0)) - int(leaf_snap.get("opp_ready_runes", 0))
	features["keyword_net"] = _keyword_net(leaf_snap, ai_index)
	# How many Action/Reaction cards in hand the AI can actually afford to play on
	# the opponent's turn with its leftover ready runes (a combination check when
	# more than one is individually affordable). Rewards ending the turn with live
	# reactive threats rather than a tapped-out board. unusable_runes counts ready
	# runes that no reactive card could ever consume — dead weight, slightly bad.
	var reactive := _reactive_eval(leaf_snap)
	features["reactive_potential"] = reactive["potential"]
	features["unusable_runes"] = maxi(0, int(leaf_snap.get("my_ready_runes", 0)) - int(reactive["usable_runes"]))

	# ── action / outcome deltas (root → leaf) ──
	features["cards_played"] = int(leaf_snap.get("my_cards_played", 0)) - int(root_snap.get("my_cards_played", 0))
	features["cards_discarded"] = int(leaf_snap.get("my_cards_discarded", 0)) - int(root_snap.get("my_cards_discarded", 0))
	features["units_moved"] = _count_move_steps(steps)
	features["points_scored"] = int(leaf_snap.get("my_score", 0)) - int(root_snap.get("my_score", 0))
	features["cards_drawn"] = maxi(0, int(leaf_snap.get("my_hand", 0)) - int(root_snap.get("my_hand", 0)))
	# Spending runes is not penalised (the pool empties each turn anyway, and
	# reactive_potential already values leftover ready runes); spending domain
	# power is slightly penalised below as a tempo cost.
	features["power_used"] = maxi(0, int(root_snap.get("my_energy", 0)) - int(leaf_snap.get("my_energy", 0)))

	var kills := _unit_losses(root_snap, leaf_snap, ai_index)
	features["enemy_units_killed"] = kills["enemy"]
	features["own_units_lost"] = kills["own"]

	# Holding fix: a conquer only earns a point — and so only counts as an
	# aggression signal — if that battlefield was actually scored this turn
	# (each battlefield scores at most once per turn). Re-taking an already
	# scored battlefield no longer inflates the score.
	features["battlefields_conquered"] = _scoring_conquers(root_snap, leaf_snap, ai_index)
	return features


func _keyword_net(snap: Dictionary, ai_index: int) -> Dictionary:
	var net: Dictionary = {}
	for kw_id in SCORED_KEYWORDS:
		net[kw_id] = 0
	var units: Dictionary = snap.get("units", {})
	for inst_id in units:
		var u: Dictionary = units[inst_id]
		var sign := 1 if int(u.get("owner", -1)) == ai_index else -1
		for kw_id in u.get("keywords", []):
			net[kw_id] = int(net.get(kw_id, 0)) + sign
	return net


func _count_move_steps(steps: Array) -> int:
	var count := 0
	for step in steps:
		if str(step.get("kind", "scripted")) != "scripted":
			continue
		if str(step.get("command", "")).begins_with("move "):
			count += 1
	return count


func _unit_losses(root_snap: Dictionary, leaf_snap: Dictionary, ai_index: int) -> Dictionary:
	var enemy := 0
	var own := 0
	var root_units: Dictionary = root_snap.get("units", {})
	var leaf_units: Dictionary = leaf_snap.get("units", {})
	for inst_id in root_units:
		if leaf_units.has(inst_id):
			continue
		if int(root_units[inst_id].get("owner", -1)) == ai_index:
			own += 1
		else:
			enemy += 1
	return {"enemy": enemy, "own": own}


func _scoring_conquers(root_snap: Dictionary, leaf_snap: Dictionary, ai_index: int) -> int:
	var count := 0
	var root_bf: Dictionary = root_snap.get("bf", {})
	var leaf_bf: Dictionary = leaf_snap.get("bf", {})
	var scored: Array = leaf_snap.get("bf_scored", [])
	for bf_id in leaf_bf:
		if int(leaf_bf[bf_id]) != ai_index:
			continue
		if int(root_bf.get(bf_id, -1)) == ai_index:
			continue
		if bf_id in scored:
			count += 1
	return count


# Evaluate the AI's reactive resource situation from its leftover ready runes and
# the Action/Reaction cards in hand. Each ready rune is one flexible resource (1
# energy via tap, or 1 power of its domain via recycle). Returns:
#   "potential":     largest set of A/R cards payable SIMULTANEOUSLY (the reactive
#                    threat) — brute-forced over subsets since hands are tiny.
#   "usable_runes":  the most runes any payable subset could actually consume, so
#                    callers can derive how many ready runes are dead weight.
func _reactive_eval(snap: Dictionary) -> Dictionary:
	var cards: Array = snap.get("my_hand_reactive", [])
	var runes: Array = snap.get("my_ready_rune_domains", [])
	if cards.is_empty() or runes.is_empty():
		return {"potential": 0, "usable_runes": 0}
	# Cap to keep the subset enumeration bounded on pathological hands.
	if cards.size() > 12:
		cards = cards.slice(0, 12)
	var n := cards.size()
	var best_count := 0
	var best_runes := 0
	for mask in range(1, 1 << n):
		var energy := 0
		var power: Array = []
		var size := 0
		for i in range(n):
			if mask & (1 << i):
				size += 1
				energy += int(cards[i].get("energy", 0))
				for pc in cards[i].get("power", []):
					power.append(pc)
		if not _runes_can_pay(runes, energy, power):
			continue
		# Runes a payable subset consumes equals its total cost (one rune per
		# energy or power pip), so it bounds how many runes can be put to use.
		var rune_cost := energy
		for pc in power:
			rune_cost += int(pc.get("amount", 0))
		best_count = maxi(best_count, size)
		best_runes = maxi(best_runes, rune_cost)
	return {"potential": best_count, "usable_runes": best_runes}


# Can a pool of ready runes (domains) cover energy + power costs? Each rune covers
# either 1 energy or 1 power of its own domain (or any domain, for an "any" rune).
func _runes_can_pay(rune_domains: Array, energy_cost: int, power_cost: Array) -> bool:
	var avail: Dictionary = {}
	var any_runes := 0
	for d in rune_domains:
		if str(d) == "any":
			any_runes += 1
		else:
			avail[d] = int(avail.get(d, 0)) + 1
	var any_power := 0
	# Satisfy specific-domain power needs from matching-domain runes first,
	# falling back to "any" runes when a domain is short.
	for pc in power_cost:
		var d := str(pc.get("domain", ""))
		var amt := int(pc.get("amount", 0))
		if d == "any" or d == "":
			any_power += amt
			continue
		var have := int(avail.get(d, 0))
		var use := mini(have, amt)
		avail[d] = have - use
		amt -= use
		if amt > 0:
			if any_runes < amt:
				return false
			any_runes -= amt
	# Remaining runes (domain leftovers + any) cover "any" power and energy.
	var leftover := any_runes
	for d in avail:
		leftover += int(avail[d])
	return leftover >= energy_cost + any_power


static func structural_hash(snapshot: Dictionary) -> String:
	return JSON.stringify(_canonicalize(snapshot))


static func _canonicalize(value: Variant) -> Variant:
	if value is Dictionary:
		var out: Dictionary = {}
		var keys: Array = value.keys()
		keys.sort()
		for key in keys:
			out[str(key)] = _canonicalize(value[key])
		return out
	if value is Array:
		var arr: Array = []
		for item in value:
			arr.append(_canonicalize(item))
		return arr
	return value


func _ready_runes(ps: PlayerState) -> int:
	var count := 0
	for rune in ps.channeled_runes:
		if not rune.is_exhausted:
			count += 1
	return count


func _build_delta(before: Dictionary, after: Dictionary, gs: GameState) -> Dictionary:
	var delta: Dictionary = {}

	# ── headline: win condition ──
	delta["wins_game"] = gs.game_over and gs.winner_index == _ai_index
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
			if after_ctrl == _ai_index:
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
		if au["owner"] == _ai_index and au["location"] != "base":
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
	if idx == _ai_index:
		return "me"
	if idx == 1 - _ai_index:
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
		if u["owner"] == _ai_index:
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
	if gs.can_player_act(_ai_index):
		if gs.turn_player_index == _ai_index and gs.current_state == TurnStateMachine.State.NEUTRAL_OPEN:
			return "your main phase"
		return "your decision"
	return "opponent's turn"
