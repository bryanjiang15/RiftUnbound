class_name AnalysisStateCodec
extends RefCounted

# Versioned authoritative GameState dump for offline counterfactual replay.
# Distinct from BriefState: this round-trips both players' ordered zones,
# rune pools, mutable card instance fields, battlefield control, chain/prompt
# metadata, and instance-allocation counters. Never send this to model prompts.

const SCHEMA_VERSION := "1"

const ScoreModelScript = preload("res://Scripts/Game/ScoreModel.gd")


static func replay_eligibility(gs: GameState) -> Dictionary:
	if gs == null:
		return {"supported": false, "reason": "null_state"}
	if gs.game_over:
		return {"supported": false, "reason": "game_over"}
	if gs.mulligan_phase:
		return {"supported": false, "reason": "mulligan_phase"}
	if gs.combat_assignment_active:
		return {"supported": false, "reason": "combat_assignment"}
	if not gs.pending_prompt.is_empty():
		return {"supported": false, "reason": "pending_prompt"}
	if not gs.chain.is_empty():
		return {"supported": false, "reason": "chain_active"}
	if gs.current_phase != TurnStateMachine.Phase.MAIN:
		return {"supported": false, "reason": "phase_%s" % gs.get_phase_name()}
	if gs.current_state != TurnStateMachine.State.NEUTRAL_OPEN:
		return {"supported": false, "reason": "state_%s" % gs.get_state_name()}
	return {"supported": true, "reason": ""}


static func root_hash(gs: GameState, seat: int) -> String:
	return ScoreModelScript.structural_hash(ScoreModelScript.snapshot(gs, seat))


static func export_state(gs: GameState) -> Dictionary:
	var cards: Dictionary = {}
	for ps in gs.players:
		_collect_player_cards(ps, cards)
	for u in gs.all_units_on_board():
		_serialize_card_into(u, cards)
	for bf in gs.board.battlefields:
		if bf.facedown_card != null:
			_serialize_card_into(bf.facedown_card, cards)
	for t in gs.assigned_targets:
		_serialize_card_into(t, cards)
	for ci in gs.chain:
		if ci.source_card != null:
			_serialize_card_into(ci.source_card, cards)
		for t in ci.targets:
			if t is CardInstance:
				_serialize_card_into(t, cards)
		for t in ci.valid_targets:
			if t is CardInstance:
				_serialize_card_into(t, cards)

	var players_out: Array = []
	for ps in gs.players:
		players_out.append(_export_player(ps))

	return {
		"schema_version": SCHEMA_VERSION,
		"replay": replay_eligibility(gs),
		"cards": cards,
		"players": players_out,
		"board": _export_board(gs.board),
		"chain": _export_chain(gs.chain),
		"turn_number": gs.turn_number,
		"turn_player_index": gs.turn_player_index,
		"current_phase": gs.current_phase,
		"current_phase_name": gs.get_phase_name(),
		"current_state": gs.current_state,
		"current_state_name": gs.get_state_name(),
		"priority_player_index": gs.priority_player_index,
		"focus_player_index": gs.focus_player_index,
		"passes_in_sequence": gs.passes_in_sequence,
		"game_over": gs.game_over,
		"winner_index": gs.winner_index,
		"victory_score": gs.victory_score,
		"game_session_id": gs.game_session_id,
		"rng_seed": gs.rng_seed,
		"pending_prompt": _export_variant(gs.pending_prompt),
		"death_replacement_recalls": _export_variant(gs.death_replacement_recalls),
		"prevent_spell_ability_damage": gs.prevent_spell_ability_damage,
		"mulligan_phase": gs.mulligan_phase,
		"mulligan_done": gs.mulligan_done.duplicate(),
		"combat_assignment_active": gs.combat_assignment_active,
		"combat_bf_index": gs.combat_bf_index,
		"attacker_player_index": gs.attacker_player_index,
		"remaining_attacker_might": gs.remaining_attacker_might,
		"damage_assignments": gs.damage_assignments.duplicate(true),
		"assigned_targets": _ids_of(gs.assigned_targets),
		"first_channel_done": gs.first_channel_done.duplicate(),
		"second_player_index": gs.second_player_index,
		"auto_combat_damage": gs.auto_combat_damage,
		"instance_id_counters": gs._instance_id_counters.duplicate(true),
	}


static func restore_state(payload: Dictionary) -> Dictionary:
	if payload == null or payload.is_empty():
		return {"ok": false, "error": "empty_payload"}
	var version := str(payload.get("schema_version", ""))
	if version != SCHEMA_VERSION:
		return {"ok": false, "error": "unsupported_schema_version:%s" % version}

	CardLoader.load_all()
	var gs := GameState.new()
	var card_map: Dictionary = {}
	var cards_in: Dictionary = payload.get("cards", {})
	if cards_in is Dictionary:
		for inst_id in cards_in:
			var card_data: Dictionary = cards_in[inst_id]
			var inst := _make_card(card_data)
			if inst == null:
				return {"ok": false, "error": "unknown_definition:%s" % str(card_data.get("definition_id", inst_id))}
			card_map[str(inst_id)] = inst

	var players_in: Array = payload.get("players", [])
	gs.players = []
	for i in range(players_in.size()):
		var pdata: Dictionary = players_in[i]
		var ps := _restore_player(pdata, card_map, gs)
		if ps == null:
			return {"ok": false, "error": "player_restore_failed:%d" % i}
		gs.players.append(ps)
	while gs.players.size() < 2:
		var filler := PlayerState.new()
		filler.player_index = gs.players.size()
		filler.player_name = "P%d" % (filler.player_index + 1)
		filler.id_registry = gs
		gs.players.append(filler)
	for ps in gs.players:
		ps.id_registry = gs

	_wire_attachments(cards_in, card_map)

	gs.board = _restore_board(payload.get("board", {}), card_map)
	gs.chain = _restore_chain(payload.get("chain", []), card_map)

	gs.turn_number = int(payload.get("turn_number", 1))
	gs.turn_player_index = int(payload.get("turn_player_index", 0))
	gs.current_phase = int(payload.get("current_phase", TurnStateMachine.Phase.MAIN))
	gs.current_state = int(payload.get("current_state", TurnStateMachine.State.NEUTRAL_OPEN))
	gs.priority_player_index = int(payload.get("priority_player_index", gs.turn_player_index))
	gs.focus_player_index = int(payload.get("focus_player_index", -1))
	gs.passes_in_sequence = int(payload.get("passes_in_sequence", 0))
	gs.game_over = bool(payload.get("game_over", false))
	gs.winner_index = int(payload.get("winner_index", -1))
	gs.victory_score = int(payload.get("victory_score", 8))
	gs.game_session_id = str(payload.get("game_session_id", ""))
	gs.rng_seed = str(payload.get("rng_seed", ""))
	gs.pending_prompt = _restore_variant(payload.get("pending_prompt", {}), card_map)
	gs.death_replacement_recalls = _restore_variant(payload.get("death_replacement_recalls", {}), card_map)
	gs.prevent_spell_ability_damage = bool(payload.get("prevent_spell_ability_damage", false))
	gs.mulligan_phase = bool(payload.get("mulligan_phase", false))
	gs.mulligan_done = _to_bool_array(payload.get("mulligan_done", [false, false]))
	gs.combat_assignment_active = bool(payload.get("combat_assignment_active", false))
	gs.combat_bf_index = int(payload.get("combat_bf_index", -1))
	gs.attacker_player_index = int(payload.get("attacker_player_index", -1))
	gs.remaining_attacker_might = int(payload.get("remaining_attacker_might", 0))
	gs.damage_assignments = (payload.get("damage_assignments", {}) as Dictionary).duplicate(true)
	gs.assigned_targets = _lookup_cards(payload.get("assigned_targets", []), card_map)
	gs.first_channel_done = _to_bool_array(payload.get("first_channel_done", [false, false]))
	gs.second_player_index = int(payload.get("second_player_index", 1))
	gs.auto_combat_damage = bool(payload.get("auto_combat_damage", true))
	var counters: Dictionary = payload.get("instance_id_counters", {})
	gs._instance_id_counters = counters.duplicate(true) if counters is Dictionary else {}

	var replay: Dictionary = payload.get("replay", replay_eligibility(gs))
	if not (replay is Dictionary):
		replay = replay_eligibility(gs)
	return {
		"ok": true,
		"gs": gs,
		"replay": replay,
		"schema_version": SCHEMA_VERSION,
	}


# ── Cards ─────────────────────────────────────────────────────────────────────


static func _collect_player_cards(ps: PlayerState, cards: Dictionary) -> void:
	for zone in [ps.deck, ps.rune_deck, ps.hand, ps.trash, ps.banishment, ps.base_permanents, ps.channeled_runes, ps.discarded_this_turn]:
		for c in zone:
			_serialize_card_into(c, cards)
	if ps.champion_zone != null:
		_serialize_card_into(ps.champion_zone, cards)
	if ps.legend != null:
		_serialize_card_into(ps.legend, cards)


static func _serialize_card_into(card: CardInstance, cards: Dictionary) -> void:
	if card == null:
		return
	var key := str(card.instance_id)
	if cards.has(key):
		return
	var def_id := ""
	if card.definition != null:
		def_id = str(card.definition.id)
	var gear_ids: Array = []
	for g in card.attached_gear:
		if g != null:
			gear_ids.append(str(g.instance_id))
			_serialize_card_into(g, cards)
	if card.attached_to != null:
		_serialize_card_into(card.attached_to, cards)
	cards[key] = {
		"definition_id": def_id,
		"instance_id": key,
		"owner_index": card.owner_index,
		"location": card.location,
		"battlefield_index": card.battlefield_index,
		"is_exhausted": card.is_exhausted,
		"is_stunned": card.is_stunned,
		"damage": card.damage,
		"buff_counters": card.buff_counters,
		"is_attacker": card.is_attacker,
		"is_defender": card.is_defender,
		"temp_might_bonus": card.temp_might_bonus,
		"temp_keywords": card.temp_keywords.duplicate(true),
		"passive_keywords": card.passive_keywords.duplicate(true),
		"passive_might_bonus": card.passive_might_bonus,
		"played_this_turn": card.played_this_turn,
		"is_face_down": card.is_face_down,
		"hidden_turn_number": card.hidden_turn_number,
		"hidden_battlefield_id": card.hidden_battlefield_id,
		"attached_gear_ids": gear_ids,
		"attached_to_id": str(card.attached_to.instance_id) if card.attached_to != null else "",
	}


static func _make_card(data: Dictionary) -> CardInstance:
	var def_id := str(data.get("definition_id", ""))
	var def = CardLoader.get_card(def_id)
	if def == null:
		return null
	var inst := CardInstance.new(def, str(data.get("instance_id", def_id)), int(data.get("owner_index", 0)))
	inst.location = str(data.get("location", ""))
	inst.battlefield_index = int(data.get("battlefield_index", -1))
	inst.is_exhausted = bool(data.get("is_exhausted", false))
	inst.is_stunned = bool(data.get("is_stunned", false))
	inst.damage = int(data.get("damage", 0))
	inst.buff_counters = int(data.get("buff_counters", 0))
	inst.is_attacker = bool(data.get("is_attacker", false))
	inst.is_defender = bool(data.get("is_defender", false))
	inst.temp_might_bonus = int(data.get("temp_might_bonus", 0))
	inst.temp_keywords = (data.get("temp_keywords", []) as Array).duplicate(true)
	inst.passive_keywords = (data.get("passive_keywords", []) as Array).duplicate(true)
	inst.passive_might_bonus = int(data.get("passive_might_bonus", 0))
	inst.played_this_turn = bool(data.get("played_this_turn", false))
	inst.is_face_down = bool(data.get("is_face_down", false))
	inst.hidden_turn_number = int(data.get("hidden_turn_number", -1))
	inst.hidden_battlefield_id = str(data.get("hidden_battlefield_id", ""))
	return inst


static func _wire_attachments(cards_in: Dictionary, card_map: Dictionary) -> void:
	for inst_id in cards_in:
		var data: Dictionary = cards_in[inst_id]
		var inst: CardInstance = card_map.get(str(inst_id))
		if inst == null:
			continue
		var attached_to_id := str(data.get("attached_to_id", ""))
		if attached_to_id != "" and card_map.has(attached_to_id):
			inst.attached_to = card_map[attached_to_id]
		var gear: Array = []
		for gid in data.get("attached_gear_ids", []):
			var g: CardInstance = card_map.get(str(gid))
			if g != null:
				gear.append(g)
		inst.attached_gear = gear


# ── Players / board / chain ───────────────────────────────────────────────────


static func _export_player(ps: PlayerState) -> Dictionary:
	return {
		"player_index": ps.player_index,
		"player_name": ps.player_name,
		"score": ps.score,
		"deck": _ids_of(ps.deck),
		"rune_deck": _ids_of(ps.rune_deck),
		"hand": _ids_of(ps.hand),
		"trash": _ids_of(ps.trash),
		"banishment": _ids_of(ps.banishment),
		"base_permanents": _ids_of(ps.base_permanents),
		"channeled_runes": _ids_of(ps.channeled_runes),
		"champion_zone": str(ps.champion_zone.instance_id) if ps.champion_zone != null else "",
		"legend": str(ps.legend.instance_id) if ps.legend != null else "",
		"rune_pool": {
			"energy": ps.rune_pool.energy,
			"power": ps.rune_pool.power.duplicate(true),
		},
		"cards_played_this_turn": ps.cards_played_this_turn,
		"cards_discarded_count": ps.cards_discarded_count,
		"discarded_this_turn": _ids_of(ps.discarded_this_turn),
		"battlefields_scored_this_turn": ps.battlefields_scored_this_turn.duplicate(),
		"units_enter_ready_this_turn": ps.units_enter_ready_this_turn,
		"deck_battlefields": ps.deck_battlefields.duplicate(),
		"id_counters": ps._id_counters.duplicate(true),
	}


static func _restore_player(pdata: Dictionary, card_map: Dictionary, gs: GameState) -> PlayerState:
	var ps := PlayerState.new()
	ps.player_index = int(pdata.get("player_index", 0))
	ps.player_name = str(pdata.get("player_name", "P%d" % (ps.player_index + 1)))
	ps.id_registry = gs
	ps.score = int(pdata.get("score", 0))
	ps.deck = _lookup_cards(pdata.get("deck", []), card_map)
	ps.rune_deck = _lookup_cards(pdata.get("rune_deck", []), card_map)
	ps.hand = _lookup_cards(pdata.get("hand", []), card_map)
	ps.trash = _lookup_cards(pdata.get("trash", []), card_map)
	ps.banishment = _lookup_cards(pdata.get("banishment", []), card_map)
	ps.base_permanents = _lookup_cards(pdata.get("base_permanents", []), card_map)
	ps.channeled_runes = _lookup_cards(pdata.get("channeled_runes", []), card_map)
	var champ_id := str(pdata.get("champion_zone", ""))
	ps.champion_zone = card_map.get(champ_id) if champ_id != "" else null
	var legend_id := str(pdata.get("legend", ""))
	ps.legend = card_map.get(legend_id) if legend_id != "" else null
	var pool: Dictionary = pdata.get("rune_pool", {})
	ps.rune_pool.energy = int(pool.get("energy", 0))
	var power: Dictionary = pool.get("power", {})
	ps.rune_pool.power = power.duplicate(true) if power is Dictionary else {}
	ps.cards_played_this_turn = int(pdata.get("cards_played_this_turn", 0))
	ps.cards_discarded_count = int(pdata.get("cards_discarded_count", 0))
	ps.discarded_this_turn = _lookup_cards(pdata.get("discarded_this_turn", []), card_map)
	var scored: Array = pdata.get("battlefields_scored_this_turn", [])
	ps.battlefields_scored_this_turn = []
	for v in scored:
		ps.battlefields_scored_this_turn.append(int(v))
	ps.units_enter_ready_this_turn = bool(pdata.get("units_enter_ready_this_turn", false))
	var bfs: Array = pdata.get("deck_battlefields", [])
	ps.deck_battlefields = []
	for v in bfs:
		ps.deck_battlefields.append(str(v))
	var counters: Dictionary = pdata.get("id_counters", {})
	ps._id_counters = counters.duplicate(true) if counters is Dictionary else {}
	return ps


static func _export_board(board: BoardState) -> Dictionary:
	var bfs: Array = []
	for bf in board.battlefields:
		var units_out: Array = []
		for pi in range(bf.units.size()):
			units_out.append(_ids_of(bf.units[pi]))
		var def_id := ""
		if bf.card_def != null:
			def_id = str(bf.card_def.id)
		bfs.append({
			"definition_id": def_id,
			"battlefield_id": bf.battlefield_id,
			"display_name": bf.display_name,
			"controller_index": bf.controller_index,
			"units": units_out,
			"is_contested": bf.is_contested,
			"facedown_card": str(bf.facedown_card.instance_id) if bf.facedown_card != null else "",
			"scored_by": bf.scored_by.duplicate(),
		})
	return {
		"battlefields": bfs,
		"active_showdown_bf": board.active_showdown_bf,
		"active_combat_bf": board.active_combat_bf,
		"staged_showdowns": board.staged_showdowns.duplicate(),
		"staged_combats": board.staged_combats.duplicate(),
	}


static func _restore_board(data: Dictionary, card_map: Dictionary) -> BoardState:
	var board := BoardState.new()
	board.battlefields = []
	for bf_data in data.get("battlefields", []):
		if not bf_data is Dictionary:
			continue
		var entry := BoardState.BattlefieldEntry.new()
		var def_id := str(bf_data.get("definition_id", ""))
		entry.card_def = CardLoader.get_card(def_id)
		entry.battlefield_id = str(bf_data.get("battlefield_id", ""))
		entry.display_name = str(bf_data.get("display_name", ""))
		entry.controller_index = int(bf_data.get("controller_index", -1))
		entry.is_contested = bool(bf_data.get("is_contested", false))
		entry.scored_by = (bf_data.get("scored_by", []) as Array).duplicate()
		var facedown_id := str(bf_data.get("facedown_card", ""))
		entry.facedown_card = card_map.get(facedown_id) if facedown_id != "" else null
		entry.units = [[], []]
		var units_in: Array = bf_data.get("units", [])
		for pi in range(mini(units_in.size(), 2)):
			entry.units[pi] = _lookup_cards_untyped(units_in[pi], card_map)
		board.battlefields.append(entry)
	board.active_showdown_bf = int(data.get("active_showdown_bf", -1))
	board.active_combat_bf = int(data.get("active_combat_bf", -1))
	board.staged_showdowns = (data.get("staged_showdowns", []) as Array).duplicate()
	board.staged_combats = (data.get("staged_combats", []) as Array).duplicate()
	return board


static func _export_chain(chain: Array) -> Array:
	var out: Array = []
	for ci in chain:
		out.append({
			"item_type": ci.item_type,
			"source_card": str(ci.source_card.instance_id) if ci.source_card != null else "",
			"ability_def": ci.ability_def.duplicate(true),
			"ability_index": ci.ability_index,
			"targets": _ids_mixed(ci.targets),
			"mode": ci.mode,
			"owner_index": ci.owner_index,
			"is_resolved": ci.is_resolved,
			"needs_target": ci.needs_target,
			"target_prompt": ci.target_prompt,
			"target_filter": ci.target_filter,
			"target_params": ci.target_params.duplicate(true),
			"damage_assignments": ci.damage_assignments.duplicate(true),
			"remaining_might": ci.remaining_might,
			"valid_targets": _ids_mixed(ci.valid_targets),
		})
	return out


static func _restore_chain(items: Array, card_map: Dictionary) -> Array[ChainItem]:
	var out: Array[ChainItem] = []
	for data in items:
		if not data is Dictionary:
			continue
		var item := ChainItem.new()
		item.item_type = int(data.get("item_type", ChainItem.ItemType.CARD))
		var src_id := str(data.get("source_card", ""))
		item.source_card = card_map.get(src_id) if src_id != "" else null
		item.ability_def = (data.get("ability_def", {}) as Dictionary).duplicate(true)
		item.ability_index = int(data.get("ability_index", -1))
		item.targets = _restore_mixed_targets(data.get("targets", []), card_map)
		item.mode = str(data.get("mode", ""))
		item.owner_index = int(data.get("owner_index", -1))
		item.is_resolved = bool(data.get("is_resolved", false))
		item.needs_target = bool(data.get("needs_target", false))
		item.target_prompt = str(data.get("target_prompt", ""))
		item.target_filter = str(data.get("target_filter", ""))
		item.target_params = (data.get("target_params", {}) as Dictionary).duplicate(true)
		item.damage_assignments = (data.get("damage_assignments", {}) as Dictionary).duplicate(true)
		item.remaining_might = int(data.get("remaining_might", 0))
		item.valid_targets = _restore_mixed_targets(data.get("valid_targets", []), card_map)
		out.append(item)
	return out


# ── Variant / id helpers ──────────────────────────────────────────────────────


static func _ids_of(arr: Array) -> Array:
	var out: Array = []
	for c in arr:
		if c != null:
			out.append(str(c.instance_id))
	return out


static func _ids_mixed(arr: Array) -> Array:
	var out: Array = []
	for t in arr:
		if t is CardInstance:
			out.append({"kind": "card", "id": str(t.instance_id)})
		else:
			out.append({"kind": "value", "value": t})
	return out


static func _lookup_cards(ids: Array, card_map: Dictionary) -> Array[CardInstance]:
	var out: Array[CardInstance] = []
	for inst_id in ids:
		var c: CardInstance = card_map.get(str(inst_id))
		if c != null:
			out.append(c)
	return out


static func _lookup_cards_untyped(ids, card_map: Dictionary) -> Array:
	var out: Array = []
	if not (ids is Array):
		return out
	for inst_id in ids:
		var c: CardInstance = card_map.get(str(inst_id))
		if c != null:
			out.append(c)
	return out


static func _restore_mixed_targets(items: Array, card_map: Dictionary) -> Array:
	var out: Array = []
	for item in items:
		if item is Dictionary and str(item.get("kind", "")) == "card":
			var c: CardInstance = card_map.get(str(item.get("id", "")))
			if c != null:
				out.append(c)
		elif item is Dictionary and item.has("value"):
			out.append(item.get("value"))
		elif item is String and card_map.has(str(item)):
			out.append(card_map[str(item)])
		else:
			out.append(item)
	return out


static func _export_variant(v: Variant) -> Variant:
	if v is CardInstance:
		return {"__card__": str(v.instance_id)}
	if v is Dictionary:
		var d: Dictionary = {}
		for k in v:
			d[str(k)] = _export_variant(v[k])
		return d
	if v is Array:
		var a: Array = []
		for item in v:
			a.append(_export_variant(item))
		return a
	return v


static func _restore_variant(v: Variant, card_map: Dictionary) -> Variant:
	if v is Dictionary and v.has("__card__"):
		return card_map.get(str(v.get("__card__", "")))
	if v is Dictionary:
		var d: Dictionary = {}
		for k in v:
			d[k] = _restore_variant(v[k], card_map)
		return d
	if v is Array:
		var a: Array = []
		for item in v:
			a.append(_restore_variant(item, card_map))
		return a
	return v


static func _to_bool_array(values: Variant) -> Array[bool]:
	var out: Array[bool] = [false, false]
	if values is Array:
		for i in range(mini(values.size(), 2)):
			out[i] = bool(values[i])
	return out
