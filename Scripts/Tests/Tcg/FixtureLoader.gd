class_name FixtureLoader

const PHASE_MAP := {
	"AWAKEN": TurnStateMachine.Phase.AWAKEN,
	"BEGINNING": TurnStateMachine.Phase.BEGINNING,
	"CHANNEL": TurnStateMachine.Phase.CHANNEL,
	"DRAW": TurnStateMachine.Phase.DRAW,
	"MAIN": TurnStateMachine.Phase.MAIN,
	"ENDING": TurnStateMachine.Phase.ENDING,
}

const STATE_MAP := {
	"NEUTRAL_OPEN": TurnStateMachine.State.NEUTRAL_OPEN,
	"NEUTRAL_CLOSED": TurnStateMachine.State.NEUTRAL_CLOSED,
	"SHOWDOWN_OPEN": TurnStateMachine.State.SHOWDOWN_OPEN,
	"SHOWDOWN_CLOSED": TurnStateMachine.State.SHOWDOWN_CLOSED,
}


static func load_into_controller(controller: GameController, fixture_path: String) -> void:
	load_from_dict(controller, _read_json(fixture_path))


static func load_from_dict(controller: GameController, data: Dictionary) -> void:
	CardLoader.load_all()
	controller._first_player_cache = -1
	controller.log_lines.clear()
	controller.gs = GameState.new()
	var gs = controller.gs

	if data.has("seed"):
		seed(int(data["seed"]))

	var bf_ids: Array = data.get("battlefields", ["zaun-warrens", "targons-peak"])
	var bf1 = str(bf_ids[0])
	var bf2 = str(bf_ids[1] if bf_ids.size() > 1 else bf_ids[0])
	gs.board.setup(bf1, bf2)

	gs.turn_number = int(data.get("turn_number", 1))
	gs.turn_player_index = int(data.get("first_player", 0))
	gs.priority_player_index = gs.turn_player_index
	gs.second_player_index = int(data.get("second_player", 1 - gs.turn_player_index))
	gs.first_channel_done = [true, true]
	if data.get("first_channel_pending", false):
		gs.first_channel_done[gs.turn_player_index] = false

	gs.current_phase = PHASE_MAP.get(str(data.get("phase", "MAIN")), TurnStateMachine.Phase.MAIN)
	gs.current_state = STATE_MAP.get(str(data.get("state", "NEUTRAL_OPEN")), TurnStateMachine.State.NEUTRAL_OPEN)
	gs.auto_combat_damage = bool(data.get("auto_combat_damage", true))
	gs.mulligan_phase = false
	gs.mulligan_done = [true, true]
	gs.victory_score = int(data.get("victory_score", 8))

	var players_data: Array = data.get("players", [])
	for pi in range(2):
		var pdata: Dictionary = players_data[pi] if pi < players_data.size() else {}
		gs.players.append(_build_player(pi, pdata))

	_place_battlefield_units(gs, players_data)

	var control: Array = data.get("battlefield_control", [])
	for i in range(mini(control.size(), gs.board.battlefields.size())):
		var ctrl = control[i]
		if ctrl == null or str(ctrl) == "uncontrolled" or int(ctrl) < 0:
			gs.board.battlefields[i].controller_index = -1
		else:
			gs.board.battlefields[i].controller_index = int(ctrl)


static func _read_json(path: String) -> Dictionary:
	var file = FileAccess.open(path, FileAccess.READ)
	if file == null:
		push_error("FixtureLoader: cannot open %s" % path)
		return {}
	var parsed = JSON.parse_string(file.get_as_text())
	file.close()
	return parsed if parsed is Dictionary else {}


static func _build_player(player_index: int, pdata: Dictionary) -> PlayerState:
	var ps = PlayerState.new()
	ps.player_index = player_index
	ps.player_name = "P%d" % (player_index + 1)
	ps.score = int(pdata.get("score", 0))

	var legend_id = str(pdata.get("legend", "jinx-loose-cannon"))
	var legend_def = CardLoader.get_card(legend_id)
	if legend_def:
		ps.legend = CardInstance.new(legend_def, "legend-p%d" % player_index, player_index)
		ps.legend.location = "legend_zone"

	var pool: Dictionary = pdata.get("pool", {})
	ps.rune_pool.energy = int(pool.get("energy", 0))
	for domain in pool.get("power", {}).keys():
		ps.rune_pool.power[str(domain)] = int(pool["power"][domain])

	for card_entry in pdata.get("hand", []):
		var inst = _make_card_from_entry(card_entry, player_index, ps)
		inst.location = "hand"
		ps.hand.append(inst)

	for entry in pdata.get("base", []):
		var inst = _make_card_from_entry(entry, player_index, ps)
		inst.location = "base"
		ps.base_permanents.append(inst)

	for entry in pdata.get("gear", []):
		var inst = _make_card_from_entry(entry, player_index, ps)
		inst.location = "base"
		ps.base_permanents.append(inst)

	for entry in pdata.get("trash", []):
		var inst = _make_card_from_entry(entry, player_index, ps)
		inst.location = "trash"
		ps.trash.append(inst)

	for i in range(int(pdata.get("deck_size", 0))):
		var filler_def = CardLoader.get_card("fury-rune")
		if filler_def:
			var filler = ps.create_instance(filler_def)
			filler.location = "deck"
			ps.deck.append(filler)

	for i in range(int(pdata.get("rune_deck_size", 12))):
		var rune_def = CardLoader.get_card("fury-rune")
		if rune_def:
			var rune = ps.create_instance(rune_def)
			rune.location = "rune_deck"
			ps.rune_deck.append(rune)

	for entry in pdata.get("runes", []):
		var rune_id = str(entry.get("id", "fury-rune") if entry is Dictionary else entry)
		var rune_def = CardLoader.get_card(rune_id)
		if rune_def:
			var rune = ps.create_instance(rune_def)
			rune.location = "rune_zone"
			if entry is Dictionary:
				rune.is_exhausted = bool(entry.get("exhausted", false))
			ps.channeled_runes.append(rune)

	return ps


static func _place_battlefield_units(gs: GameState, players_data: Array) -> void:
	for pi in range(players_data.size()):
		var pdata: Dictionary = players_data[pi]
		for bf_key in pdata.keys():
			if not str(bf_key).begins_with("battlefield-"):
				continue
			var bf_idx = _bf_key_to_index(str(bf_key))
			if bf_idx < 0:
				continue
			for entry in pdata[bf_key]:
				var owner = int(entry.get("owner", pi) if entry is Dictionary else pi)
				var ps: PlayerState = gs.players[owner]
				var inst = _make_card_from_entry(entry, owner, ps)
				gs.board.add_unit_to_battlefield(inst, bf_idx)


static func _bf_key_to_index(bf_key: String) -> int:
	if bf_key.ends_with("-a"):
		return 0
	if bf_key.ends_with("-b"):
		return 1
	return -1


static func _make_card(card_id: String, owner_index: int, ps: PlayerState) -> CardInstance:
	return _make_card_from_entry({"id": card_id}, owner_index, ps)


static func _make_card_from_entry(entry: Variant, owner_index: int, ps: PlayerState) -> CardInstance:
	var card_id: String
	var exhausted := false
	var damage := 0
	var extra_keywords: Array = []
	if entry is Dictionary:
		card_id = str(entry.get("id", ""))
		exhausted = bool(entry.get("exhausted", false))
		damage = int(entry.get("damage", 0))
		extra_keywords = entry.get("keywords", [])
	else:
		card_id = str(entry)
	var def = CardLoader.get_card(card_id)
	if def == null:
		push_error("FixtureLoader: unknown card '%s'" % card_id)
		def = CardDefinition.new()
		def.id = card_id
		def.name = card_id
		def.card_type = "unit"
	var inst = ps.create_instance(def)
	inst.owner_index = owner_index
	inst.is_exhausted = exhausted
	inst.damage = damage
	for kw in extra_keywords:
		if kw is Dictionary:
			inst.temp_keywords.append(kw)
	return inst
