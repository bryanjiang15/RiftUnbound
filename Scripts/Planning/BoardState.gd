extends RefCounted
class_name BoardState

## Authoritative model of what is placed on the planning grid.
##
## Owns three arrays (player_champions, opponent_champions, deployed_allies) and an
## occupancy dictionary keyed by GridCoord.to_key(). All mutating methods keep the
## arrays and occupancy in lockstep — call rebuild_occupancy() only when repairing
## state that was modified externally.

var grid_spec: GridSpec
var player_champions: Array[ChampionInstance] = []
var opponent_champions: Array[ChampionInstance] = []
var deployed_allies: Array[CardInstance] = []
## instance_id (ally) -> GridCoord (when allies are enabled).
var ally_cells: Dictionary = {}

## Keys from GridCoord.to_key(); values: `{ "kind": "champion"|"ally", "instance_id": int }`.
var occupancy: Dictionary = {}

func _init(p_spec: GridSpec) -> void:
	grid_spec = p_spec

## Rebuilds the occupancy map from scratch using the current champion and ally arrays.
## Idempotent — safe to call after any batch mutation.
func rebuild_occupancy() -> void:
	occupancy.clear()
	for c in player_champions:
		_set_occ_champion(c)
	for c in opponent_champions:
		_set_occ_champion(c)
	for a in deployed_allies:
		var cell: Variant = ally_cells.get(a.instance_id, null)
		if cell is GridCoord:
			var k: String = (cell as GridCoord).to_key()
			occupancy[k] = {"kind": "ally", "instance_id": a.instance_id}

func _set_occ_champion(c: ChampionInstance) -> void:
	var k: String = c.cell.to_key()
	occupancy[k] = {"kind": "champion", "instance_id": c.instance_id}

## Searches both player and opponent arrays and returns the matching ChampionInstance,
## or null if no champion with that instance_id exists on the board.
func find_champion(instance_id: int) -> ChampionInstance:
	for c in player_champions:
		if c.instance_id == instance_id:
			return c
	for c in opponent_champions:
		if c.instance_id == instance_id:
			return c
	return null

## Places a new player champion on `cell`. Returns false (and warns) if the cell is
## out-of-bounds for the player half, already occupied, or the player champion cap
## from `params` is reached. On success appends to player_champions and refreshes occupancy.
func place_player_champion(
	def: ChampionData,
	cell: GridCoord,
	scope: InstanceIdScope,
	params: PlanningParams = null
) -> bool:
	if params != null and player_champions.size() >= params.max_player_champions_on_board:
		push_warning("BoardState: max player champions reached")
		return false
	if not grid_spec.is_player_deployable(cell):
		push_warning("BoardState: cell not player-deployable")
		return false
	if _cell_occupied(cell):
		push_warning("BoardState: cell occupied")
		return false
	var inst := ChampionInstance.from_definition(def, scope, cell)
	player_champions.append(inst)
	rebuild_occupancy()
	return true

## Places an opponent champion on `cell` (opponent half only). The opponent layout is
## set by OpponentPlanningStub and does not enforce a per-side cap. Returns false if
## the cell is not in the opponent zone or is already occupied.
func place_opponent_champion(def: ChampionData, cell: GridCoord, scope: InstanceIdScope) -> bool:
	if not grid_spec.is_opponent_deployable(cell):
		push_warning("BoardState: cell not opponent-deployable")
		return false
	if _cell_occupied(cell):
		push_warning("BoardState: cell occupied")
		return false
	var inst := ChampionInstance.from_definition(def, scope, cell)
	opponent_champions.append(inst)
	rebuild_occupancy()
	return true

## Moves the player champion with `instance_id` to `new_cell`. Returns false if the
## champion is not found on the player side, the destination is outside the player zone,
## or the destination is occupied by a different unit.
func move_player_champion(instance_id: int, new_cell: GridCoord, _scope: InstanceIdScope) -> bool:
	var c := find_champion(instance_id)
	if c == null:
		return false
	if player_champions.find(c) < 0:
		return false
	if not grid_spec.is_player_deployable(new_cell):
		return false
	if _cell_occupied_except(new_cell, instance_id):
		return false
	c.cell = new_cell
	rebuild_occupancy()
	return true

## Removes the player champion with `instance_id` from the board and clears its
## occupancy entry. Returns false if the champion is not found on the player side.
func remove_player_champion(instance_id: int) -> bool:
	var c := find_champion(instance_id)
	if c == null or player_champions.find(c) < 0:
		return false
	player_champions.erase(c)
	rebuild_occupancy()
	return true

## Removes all player champions and refreshes occupancy. Used before re-populating
## the player side (e.g. on round reset).
func clear_player_champions() -> void:
	player_champions.clear()
	rebuild_occupancy()

## Removes all opponent champions and refreshes occupancy. Called by OpponentPlanningStub
## before re-applying the stub layout each round.
func clear_opponent_champions() -> void:
	opponent_champions.clear()
	rebuild_occupancy()

## Alias for assign_equipment (matches Phase C plan wording).
func assign_item(champion_instance_id: int, card: CardInstance, params: PlanningParams) -> bool:
	return assign_equipment(champion_instance_id, card, params)

## Appends `card` to the champion's equipped list. Returns false if the champion is not
## found or its equipment slots are already full per `params.equipment_slots_per_champion`.
func assign_equipment(champion_instance_id: int, card: CardInstance, params: PlanningParams) -> bool:
	var c := find_champion(champion_instance_id)
	if c == null:
		return false
	if c.equipped.size() >= params.equipment_slots_per_champion:
		push_warning("BoardState: equipment slots full")
		return false
	c.equipped.append(card)
	return true

## Wipes both sides, allies, and occupancy in one call.
func clear() -> void:
	player_champions.clear()
	opponent_champions.clear()
	deployed_allies.clear()
	ally_cells.clear()
	occupancy.clear()

## Removes all equipped items from the champion with `instance_id`. No-op if not found.
func clear_equipment(champion_instance_id: int) -> void:
	var c := find_champion(champion_instance_id)
	if c != null:
		c.equipped.clear()

func _cell_occupied(cell: GridCoord) -> bool:
	return occupancy.has(cell.to_key())

func _cell_occupied_except(cell: GridCoord, champion_instance_id: int) -> bool:
	var k: String = cell.to_key()
	if not occupancy.has(k):
		return false
	var entry: Variant = occupancy[k]
	if entry is Dictionary:
		var id: int = int(entry.get("instance_id", -1))
		return id != champion_instance_id
	return true
