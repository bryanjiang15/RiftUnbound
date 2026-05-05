extends Node
## C1 unit tests for BoardState. Run via: run_project(scene="res://Scenes/Tests/c1_tests.tscn")
## then get_debug_output() and look for "TEST C1:" and "TEST SUMMARY:" lines.

var _pass: int = 0
var _fail: int = 0

func _ready() -> void:
	var spec := GridSpec.default_square_5x3_two_sided()
	var params := PlanningParams.new()
	params.equipment_slots_per_champion = 3
	params.max_player_champions_on_board = 3
	params.require_at_least_one_player_champion = true

	var scope := InstanceIdScope.new()

	var def := _make_champion_def("test_hero", "Test Hero")
	var def2 := _make_champion_def("test_hero_2", "Test Hero 2")

	# ── Case 1: out-of-bounds ─────────────────────────────────────────────────
	var board := BoardState.new(spec)
	var oob_cell := GridCoord.from_square(Vector2i(99, 99))
	_check("out-of-bounds returns false",
		board.place_player_champion(def, oob_cell, scope, params) == false)

	# ── Case 2: collision ────────────────────────────────────────────────────
	board = BoardState.new(spec)
	var valid_player_cell := GridCoord.from_square(Vector2i(1, 7))
	var first_ok := board.place_player_champion(def, valid_player_cell, scope, params)
	var second_ok := board.place_player_champion(def2, valid_player_cell, scope, params)
	_check("first placement on valid cell succeeds", first_ok == true)
	_check("collision returns false", second_ok == false)

	# ── Case 3: slot overflow ────────────────────────────────────────────────
	board = BoardState.new(spec)
	scope.reset(1)
	var champ_cell := GridCoord.from_square(Vector2i(0, 6))
	board.place_player_champion(def, champ_cell, scope, params)
	var champ_id := board.player_champions[0].instance_id
	var card1 := _make_card_instance(scope)
	var card2 := _make_card_instance(scope)
	var card3 := _make_card_instance(scope)
	var card4 := _make_card_instance(scope)
	var r1 := board.assign_item(champ_id, card1, params)
	var r2 := board.assign_item(champ_id, card2, params)
	var r3 := board.assign_item(champ_id, card3, params)
	var r4 := board.assign_item(champ_id, card4, params)
	_check("first 3 assign_item succeed", r1 and r2 and r3)
	_check("4th assign_item returns false (slot overflow)", r4 == false)

	# ── Case 4: wrong half ───────────────────────────────────────────────────
	board = BoardState.new(spec)
	scope.reset(1)
	# spec: rows_per_side=5, so player rows=5..9, opponent rows=0..4
	var opp_half_cell := GridCoord.from_square(Vector2i(1, 2))   # y=2 → opponent half
	var player_half_cell := GridCoord.from_square(Vector2i(1, 7)) # y=7 → player half
	_check("player cannot place on opponent half (row 2)",
		board.place_player_champion(def, opp_half_cell, scope, params) == false)
	_check("opponent cannot place on player half (row 7)",
		board.place_opponent_champion(def, player_half_cell, scope) == false)

	# ── Bonus: clear() ───────────────────────────────────────────────────────
	board = BoardState.new(spec)
	scope.reset(1)
	board.place_player_champion(def, GridCoord.from_square(Vector2i(0, 5)), scope, params)
	board.place_opponent_champion(def2, GridCoord.from_square(Vector2i(0, 0)), scope)
	board.clear()
	_check("clear() empties player_champions", board.player_champions.is_empty())
	_check("clear() empties opponent_champions", board.opponent_champions.is_empty())
	_check("clear() empties occupancy", board.occupancy.is_empty())

	# ── Bonus: occupancy consistent after place ───────────────────────────────
	board = BoardState.new(spec)
	scope.reset(1)
	var pcell := GridCoord.from_square(Vector2i(2, 9))
	board.place_player_champion(def, pcell, scope, params)
	var occ_entry: Variant = board.occupancy.get(pcell.to_key(), null)
	_check("occupancy consistent after place",
		occ_entry != null
		and occ_entry is Dictionary
		and str(occ_entry.get("kind", "")) == "champion")

	# ── Bonus: move_player_champion ───────────────────────────────────────────
	board = BoardState.new(spec)
	scope.reset(1)
	var from_cell := GridCoord.from_square(Vector2i(0, 5))
	var to_cell   := GridCoord.from_square(Vector2i(2, 8))
	board.place_player_champion(def, from_cell, scope, params)
	var iid := board.player_champions[0].instance_id
	var moved := board.move_player_champion(iid, to_cell, scope)
	_check("move_player_champion succeeds to empty player cell", moved == true)
	_check("old cell vacated after move", not board.occupancy.has(from_cell.to_key()))
	_check("new cell occupied after move", board.occupancy.has(to_cell.to_key()))

	# ── Bonus: remove_player_champion ────────────────────────────────────────
	board = BoardState.new(spec)
	scope.reset(1)
	var rm_cell := GridCoord.from_square(Vector2i(1, 6))
	board.place_player_champion(def, rm_cell, scope, params)
	var rm_id := board.player_champions[0].instance_id
	var removed := board.remove_player_champion(rm_id)
	_check("remove_player_champion succeeds", removed == true)
	_check("champion gone after remove", board.player_champions.is_empty())
	_check("occupancy cleared after remove", not board.occupancy.has(rm_cell.to_key()))

	print("TEST SUMMARY: %d/%d passed" % [_pass, _pass + _fail])
	get_tree().quit(0 if _fail == 0 else 1)

func _check(name: String, condition: bool) -> void:
	if condition:
		_pass += 1
		print("TEST C1: %s PASS" % name)
	else:
		_fail += 1
		print("TEST C1: %s FAIL" % name)

func _make_champion_def(id: StringName, dname: String) -> ChampionData:
	var d := ChampionData.new()
	d.definition_id = id
	d.display_name = dname
	var stats := CombatStats.new()
	stats.max_health = 10
	stats.current_health = 10
	stats.attack = 1
	d.base_stats = stats
	return d

func _make_card_instance(scope: InstanceIdScope) -> CardInstance:
	var cd := CardData.new()
	cd.definition_id = &"stub_item"
	cd.card_kind = CardData.CardType.EQUIPMENT
	return CardInstance.from_definition(cd, scope)
