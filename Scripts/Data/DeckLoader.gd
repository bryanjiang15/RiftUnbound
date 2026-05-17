class_name DeckLoader


static func load_deck(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		push_error("DeckLoader: file not found: " + path)
		return {}
	var file = FileAccess.open(path, FileAccess.READ)
	if file == null:
		push_error("DeckLoader: could not open: " + path)
		return {}
	var json_text = file.get_as_text()
	file.close()
	var data = JSON.parse_string(json_text)
	if data == null or not data is Dictionary:
		push_error("DeckLoader: invalid JSON in " + path)
		return {}
	return data


static func build_player_state(deck_path: String, player_index: int) -> PlayerState:
	var data = load_deck(deck_path)
	if data.is_empty():
		return null
	CardLoader.load_all()
	var ps = PlayerState.new()
	ps.player_index = player_index
	ps.player_name = data.get("player_label", "P%d" % (player_index + 1))

	# Legend
	var legend_id = data.get("legend", "")
	var legend_def = CardLoader.get_card(legend_id)
	if legend_def:
		ps.legend = CardInstance.new(legend_def, "legend-p%d" % player_index, player_index)
		ps.legend.location = "legend_zone"

	# Chosen Champion Zone (face-up, placed at start)
	var champ_id = data.get("chosen_champion", "")
	var champ_def = CardLoader.get_card(champ_id)
	if champ_def:
		var champ_inst = ps.create_instance(champ_def)
		champ_inst.location = "champion_zone"
		ps.champion_zone = champ_inst

	# Main Deck
	var main_deck_raw: Array[CardInstance] = []
	for entry in data.get("main_deck", []):
		var card_id = entry.get("card_id", "")
		var count = entry.get("count", 1)
		var card_def = CardLoader.get_card(card_id)
		if card_def == null:
			push_warning("DeckLoader: unknown card id '%s'" % card_id)
			continue
		for _i in range(count):
			var inst = ps.create_instance(card_def)
			inst.location = "deck"
			main_deck_raw.append(inst)
	main_deck_raw.shuffle()
	ps.deck = main_deck_raw

	# Rune Deck
	var rune_deck_raw: Array[CardInstance] = []
	for entry in data.get("rune_deck", []):
		var card_id = entry.get("card_id", "")
		var count = entry.get("count", 1)
		var card_def = CardLoader.get_card(card_id)
		if card_def == null:
			continue
		for _i in range(count):
			var inst = ps.create_instance(card_def)
			inst.location = "rune_deck"
			rune_deck_raw.append(inst)
	rune_deck_raw.shuffle()
	ps.rune_deck = rune_deck_raw

	# Battlefields list (stored in deck data; selection happens in game setup)
	ps.deck_battlefields = data.get("battlefields", [])

	return ps
