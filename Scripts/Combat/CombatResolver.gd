extends RefCounted
class_name CombatResolver

## Pure stateless combat resolver.
##
## Given a PlanningSnapshot and a GridSpec, produces a fully deterministic
## CombatResult with a complete event log. No Node, no signals, no randomness.
## Fully headless-testable.
##
## Combat rules (Phase D):
##   - Turn order: speed DESC, instance_id ASC on ties.
##   - Action: ATTACK nearest enemy if Chebyshev ≤ 1; else MOVE one cell toward it.
##   - Damage: max(1, attacker.attack − defender.defense).
##   - Death: unit removed from board immediately; skipped for the rest of the tick.
##   - Timeout: 200 ticks; if reached, player loses.

const MAX_TICKS: int = 200

## Resolves a full combat from a planning snapshot.
static func resolve(snapshot: PlanningSnapshot, spec: GridSpec) -> CombatResult:
	var board := CombatBoard.from_snapshot(snapshot)
	var result := CombatResult.new()
	result.events.append(_make_boundary_event(CombatEvent.Kind.COMBAT_START, 0))

	var tick := 0
	while board.alive_players().size() > 0 and board.alive_opponents().size() > 0:
		if tick >= MAX_TICKS:
			result.timed_out = true
			break
		var turn_order := _build_turn_order(board)
		for unit: CombatUnit in turn_order:
			if not unit.is_alive():
				continue
			if board.alive_players().is_empty() or board.alive_opponents().is_empty():
				break
			_act(unit, board, spec, result.events, tick)
		tick += 1

	result.player_won = board.alive_opponents().size() == 0 and not result.timed_out
	result.player_survivors  = board.alive_players().size()
	result.opponent_survivors = board.alive_opponents().size()
	result.events.append(_make_boundary_event(CombatEvent.Kind.COMBAT_END, tick))
	return result

# ── Turn order ───────────────────────────────────────────────────────────────

## Returns all alive units sorted by speed DESC, instance_id ASC.
static func _build_turn_order(board: CombatBoard) -> Array[CombatUnit]:
	var units: Array[CombatUnit] = board.alive_units()
	units.sort_custom(func(a: CombatUnit, b: CombatUnit) -> bool:
		if a.speed != b.speed:
			return a.speed > b.speed
		return a.instance_id < b.instance_id
	)
	return units

# ── Per-unit action ──────────────────────────────────────────────────────────

## Decides and executes one action for `unit` this tick.
static func _act(
	unit: CombatUnit,
	board: CombatBoard,
	spec: GridSpec,
	events: Array[CombatEvent],
	tick: int
) -> void:
	var enemies: Array[CombatUnit] = board.alive_opponents() if unit.is_player_side else board.alive_players()
	if enemies.is_empty():
		return
	var nearest: CombatUnit = _nearest_enemy(unit, enemies)
	if CombatBoard.chebyshev(unit.cell, nearest.cell) <= 1:
		_do_attack(unit, nearest, board, events, tick)
	else:
		var dest: GridCoord = _best_move(unit, nearest, board, spec)
		_do_move(unit, dest, board, events, tick)

## Returns the enemy closest by Chebyshev distance; ties broken by instance_id ASC.
static func _nearest_enemy(unit: CombatUnit, enemies: Array[CombatUnit]) -> CombatUnit:
	var best: CombatUnit = enemies[0]
	var best_dist: int = CombatBoard.chebyshev(unit.cell, best.cell)
	for i in range(1, enemies.size()):
		var e: CombatUnit = enemies[i]
		var d: int = CombatBoard.chebyshev(unit.cell, e.cell)
		if d < best_dist or (d == best_dist and e.instance_id < best.instance_id):
			best = e
			best_dist = d
	return best

## Returns the best adjacent empty cell to move toward `target`.
## Minimises Chebyshev distance; ties broken by to_key() lexicographic order.
## Returns unit.cell if no better empty neighbour exists.
static func _best_move(
	unit: CombatUnit,
	target: CombatUnit,
	board: CombatBoard,
	spec: GridSpec
) -> GridCoord:
	var neighbours: Array[GridCoord] = board.empty_neighbours(unit.cell, spec)
	if neighbours.is_empty():
		return unit.cell
	var best: GridCoord = neighbours[0]
	var best_dist: int = CombatBoard.chebyshev(best, target.cell)
	for i in range(1, neighbours.size()):
		var nc: GridCoord = neighbours[i]
		var d: int = CombatBoard.chebyshev(nc, target.cell)
		if d < best_dist or (d == best_dist and nc.to_key() < best.to_key()):
			best = nc
			best_dist = d
	# Only move if it actually reduces distance.
	if best_dist >= CombatBoard.chebyshev(unit.cell, target.cell):
		return unit.cell
	return best

# ── Actions ──────────────────────────────────────────────────────────────────

static func _do_attack(
	attacker: CombatUnit,
	defender: CombatUnit,
	board: CombatBoard,
	events: Array[CombatEvent],
	tick: int
) -> void:
	var dmg: int = maxi(1, attacker.attack - defender.defense)
	defender.current_health -= dmg

	var ev := CombatEvent.new()
	ev.tick   = tick
	ev.kind   = CombatEvent.Kind.ATTACK
	ev.actor_id   = attacker.instance_id
	ev.actor_cell = attacker.cell
	ev.target_id  = defender.instance_id
	ev.target_cell = defender.cell
	ev.damage = dmg
	ev.target_health_after = defender.current_health
	ev.died   = not defender.is_alive()
	events.append(ev)

	if not defender.is_alive():
		board.remove(defender)
		var death_ev := CombatEvent.new()
		death_ev.tick     = tick
		death_ev.kind     = CombatEvent.Kind.DEATH
		death_ev.actor_id = defender.instance_id
		death_ev.actor_cell = defender.cell
		death_ev.target_id  = -1
		events.append(death_ev)

static func _do_move(
	unit: CombatUnit,
	dest: GridCoord,
	board: CombatBoard,
	events: Array[CombatEvent],
	tick: int
) -> void:
	var from_cell: GridCoord = unit.cell
	if dest.to_key() != from_cell.to_key():
		board.move(unit, dest)

	var ev := CombatEvent.new()
	ev.tick      = tick
	ev.kind      = CombatEvent.Kind.MOVE
	ev.actor_id  = unit.instance_id
	ev.actor_cell = unit.cell
	ev.target_cell = dest
	events.append(ev)

# ── Boundary events ──────────────────────────────────────────────────────────

static func _make_boundary_event(kind: CombatEvent.Kind, tick: int) -> CombatEvent:
	var ev := CombatEvent.new()
	ev.tick   = tick
	ev.kind   = kind
	ev.actor_id = -1
	ev.target_id = -1
	return ev
