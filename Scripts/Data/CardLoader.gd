class_name CardLoader

static var _all_cards: Dictionary = {}
static var _loaded: bool = false


static func load_all() -> Dictionary:
	if _loaded:
		return _all_cards
	_all_cards.clear()
	var files = [
		"res://Data/Cards/units.json",
		"res://Data/Cards/gear.json",
		"res://Data/Cards/spells.json",
		"res://Data/Cards/runes.json",
		"res://Data/Cards/battlefields.json",
		"res://Data/Cards/legends.json",
	]
	for path in files:
		_load_file(path)
	_load_tokens()
	_loaded = true
	return _all_cards


static func get_card(card_id: String) -> CardDefinition:
	if not _loaded:
		load_all()
	return _all_cards.get(card_id, null)


static func _load_file(path: String) -> void:
	if not FileAccess.file_exists(path):
		push_error("CardLoader: file not found: " + path)
		return
	var file = FileAccess.open(path, FileAccess.READ)
	if file == null:
		push_error("CardLoader: could not open: " + path)
		return
	var json_text = file.get_as_text()
	file.close()
	var data = JSON.parse_string(json_text)
	if data == null or not data is Array:
		push_error("CardLoader: invalid JSON in " + path)
		return
	for entry in data:
		var def = _parse_definition(entry)
		if def != null:
			_all_cards[def.id] = def


static func _load_tokens() -> void:
	var path = "res://Data/Cards/tokens.json"
	if not FileAccess.file_exists(path):
		return
	var file = FileAccess.open(path, FileAccess.READ)
	if file == null:
		return
	var json_text = file.get_as_text()
	file.close()
	var data = JSON.parse_string(json_text)
	if data == null or not data is Array:
		return
	for entry in data:
		var def = _parse_definition(entry)
		if def != null:
			var token_id = entry.get("token_id", def.id)
			def.id = token_id
			_all_cards[token_id] = def


static func _parse_definition(d: Dictionary) -> CardDefinition:
	if not d.has("id") and not d.has("token_id"):
		return null
	var def = CardDefinition.new()
	def.id = d.get("id", d.get("token_id", ""))
	def.name = d.get("name", def.id)
	def.card_type = d.get("card_type", "")
	def.supertypes = d.get("supertypes", [])
	def.tags = d.get("tags", [])
	def.domain = d.get("domain", [])
	def.energy_cost = d.get("energy_cost", 0)
	def.power_cost = d.get("power_cost", [])
	def.keywords = d.get("keywords", [])
	def.abilities = d.get("abilities", [])
	def.flavor_text = d.get("flavor_text", "")
	def.might = d.get("might", 0)
	def.might_bonus = d.get("might_bonus", null)
	def.attached_keywords = d.get("attached_keywords", [])
	def.is_action = d.get("is_action", false)
	def.is_reaction = d.get("is_reaction", false)
	def.is_basic = d.get("is_basic", false)
	def.facedown_capacity = d.get("facedown_capacity", 1)
	def.champion_tag = d.get("champion_tag", "")
	def.image = d.get("image", "")
	return def
