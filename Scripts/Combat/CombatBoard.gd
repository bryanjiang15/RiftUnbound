extends RefCounted
class_name CombatBoard

## Mutable grid state for a single combat.
##
## Owns all CombatUnit objects for the duration of combat. Keyed by
## GridCoord.to_key() so the same coordinate system used during planning
## works unchanged here.

## key → CombatUnit (only alive units are kept)
var occupancy: Dictionary = {}

## All units ever added (including dead ones, for event log attribution).
var _all_units: Array[CombatUnit] = []

## Counter used to assign unique combat instance_ids.
var _next_id: int = 1

## Builds a CombatBoard from a PlanningSnapshot, converting every
## ChampionInstance into a flat CombatUnit. deployed_allies are stubbed
## for future phases.
static func from_snapshot(snapshot: PlanningSnapshot) -> CombatBoard:
	var b := CombatBoard.new()
	for inst in snapshot.player_champions:
		var u := CombatUnit.from_champion(inst, true, b._next_id)
		b._next_id += 1
		b._all_units.append(u)
		b.occupancy[inst.cell.to_key()] = u
	for inst in snapshot.opponent_champions:
		var u := CombatUnit.from_champion(inst, false, b._next_id)
		b._next_id += 1
		b._all_units.append(u)
		b.occupancy[inst.cell.to_key()] = u
	return b

## Returns the unit at coord, or null if the cell is empty.
func unit_at(coord: GridCoord) -> CombatUnit:
	return occupancy.get(coord.to_key(), null)

## Places a unit on the board at coord (does not check for occupancy).
func place(unit: CombatUnit, coord: GridCoord) -> void:
	unit.cell = coord
	occupancy[coord.to_key()] = unit
	if unit not in _all_units:
		_all_units.append(unit)

## Removes a unit from the board (marks it as dead by leaving health ≤ 0).
func remove(unit: CombatUnit) -> void:
	var key := unit.cell.to_key()
	if occupancy.get(key, null) == unit:
		occupancy.erase(key)

## Moves a unit from its current cell to a new cell.
func move(unit: CombatUnit, to: GridCoord) -> void:
	var old_key := unit.cell.to_key()
	if occupancy.get(old_key, null) == unit:
		occupancy.erase(old_key)
	unit.cell = to
	occupancy[to.to_key()] = unit

## Returns all currently alive units (both sides).
func alive_units() -> Array[CombatUnit]:
	var out: Array[CombatUnit] = []
	for u: CombatUnit in occupancy.values():
		if u.is_alive():
			out.append(u)
	return out

## Returns alive player-side units.
func alive_players() -> Array[CombatUnit]:
	var out: Array[CombatUnit] = []
	for u: CombatUnit in occupancy.values():
		if u.is_alive() and u.is_player_side:
			out.append(u)
	return out

## Returns alive opponent-side units.
func alive_opponents() -> Array[CombatUnit]:
	var out: Array[CombatUnit] = []
	for u: CombatUnit in occupancy.values():
		if u.is_alive() and not u.is_player_side:
			out.append(u)
	return out

## Returns in-bounds, empty Chebyshev-adjacent cells (up to 8).
func empty_neighbours(coord: GridCoord, spec: GridSpec) -> Array[GridCoord]:
	var out: Array[GridCoord] = []
	for dx in range(-1, 2):
		for dy in range(-1, 2):
			if dx == 0 and dy == 0:
				continue
			var nc := GridCoord.from_square(Vector2i(coord.square.x + dx, coord.square.y + dy))
			if spec.is_in_bounds(nc) and not occupancy.has(nc.to_key()):
				out.append(nc)
	return out

## Chebyshev distance between two square GridCoords.
static func chebyshev(a: GridCoord, b: GridCoord) -> int:
	return maxi(absi(a.square.x - b.square.x), absi(a.square.y - b.square.y))
