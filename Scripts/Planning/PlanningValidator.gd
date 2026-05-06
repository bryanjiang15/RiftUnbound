extends RefCounted
class_name PlanningValidator

## Pure validation utilities for BoardState.
##
## All methods are static — no instance state. Errors are returned as human-readable
## strings so they can be shown directly in the HUD or logged without extra formatting.

## Validates the entire board against `params` rules. Returns an empty array when the
## board is legal; otherwise returns one string per violation (bounds, zone, duplicates,
## slot limits, and occupancy consistency).
static func validate(board: BoardState, params: PlanningParams) -> PackedStringArray:
	var errs: PackedStringArray = []
	if board == null or board.grid_spec == null:
		errs.append("Board or grid spec missing.")
		return errs
	if params == null:
		params = PlanningParams.new()

	board.rebuild_occupancy()

	var seen_ids: Dictionary = {}
	var player_cells: Dictionary = {}
	var opponent_cells: Dictionary = {}

	for c in board.player_champions:
		var ck: String = c.cell.to_key()
		if player_cells.has(ck):
			errs.append("Two player champions share cell %s." % ck)
		player_cells[ck] = true
		_validate_champion_placement(board, c, true, params, errs, seen_ids)

	for c in board.opponent_champions:
		var ck2: String = c.cell.to_key()
		if opponent_cells.has(ck2):
			errs.append("Two opponent champions share cell %s." % ck2)
		opponent_cells[ck2] = true
		_validate_champion_placement(board, c, false, params, errs, seen_ids)

	for a in board.deployed_allies:
		if seen_ids.has(a.instance_id):
			errs.append("Duplicate instance_id %d." % a.instance_id)
		else:
			seen_ids[a.instance_id] = true

	if params.require_at_least_one_player_champion and board.player_champions.is_empty():
		errs.append("At least one player champion is required.")

	if board.player_champions.size() > params.max_player_champions_on_board:
		errs.append(
			"Too many player champions (%d > %d)."
			% [board.player_champions.size(), params.max_player_champions_on_board]
		)

	_validate_occupancy_matches_champions(board, errs)

	return errs

static func _validate_champion_placement(
	board: BoardState,
	c: ChampionInstance,
	is_player: bool,
	params: PlanningParams,
	errs: PackedStringArray,
	seen_ids: Dictionary
) -> void:
	if c.definition == null:
		errs.append("Champion instance %d has no definition." % c.instance_id)
	if seen_ids.has(c.instance_id):
		errs.append("Duplicate champion instance_id %d." % c.instance_id)
	else:
		seen_ids[c.instance_id] = true

	if not board.grid_spec.is_in_bounds(c.cell):
		errs.append("Champion %d out of bounds." % c.instance_id)
	elif is_player:
		if not board.grid_spec.is_player_deployable(c.cell):
			errs.append("Player champion %d not on player deploy rows." % c.instance_id)
	else:
		if not board.grid_spec.is_opponent_deployable(c.cell):
			errs.append("Opponent champion %d not on opponent deploy rows." % c.instance_id)

	if c.equipped.size() > params.equipment_slots_per_champion:
		errs.append(
			"Champion %d has too many items (%d > %d)."
			% [c.instance_id, c.equipped.size(), params.equipment_slots_per_champion]
		)

	for card in c.equipped:
		if card != null and seen_ids.has(card.instance_id):
			errs.append("Duplicate card instance_id %d in loadouts." % card.instance_id)
		elif card != null:
			seen_ids[card.instance_id] = true

static func _validate_occupancy_matches_champions(board: BoardState, errs: PackedStringArray) -> void:
	for c in board.player_champions:
		var k: String = c.cell.to_key()
		if not board.occupancy.has(k):
			errs.append("Occupancy missing key for player champion %d." % c.instance_id)
			continue
		var entry: Variant = board.occupancy[k]
		if entry is Dictionary:
			if entry.get("instance_id", -1) != c.instance_id:
				errs.append("Occupancy mismatch at %s for player champion." % k)
			if str(entry.get("kind", "")) != "champion":
				errs.append("Occupancy kind wrong at %s." % k)

	for c in board.opponent_champions:
		var k2: String = c.cell.to_key()
		if not board.occupancy.has(k2):
			errs.append("Occupancy missing key for opponent champion %d." % c.instance_id)
