class_name RuleScoreFeaturesTests
extends RefCounted

# Unit tests for the linear-eval feature space: ScoreModel.build_score_features
# (raw feature math) and ScoringProfile.score_with_breakdown (registry-driven
# weighted sum). Both operate on plain snapshot dicts, so these tests craft
# snapshots directly — no GameState needed.

const ScoringProfileScript = preload("res://Scripts/Game/ScoringProfile.gd")
const FeatureRegistryScript = preload("res://Scripts/Game/FeatureRegistry.gd")


static func run(assertions) -> void:
	_test_win_proximity_convex(assertions)
	_test_per_battlefield_might_margin(assertions)
	_test_hold_income(assertions)
	_test_control_fragility_sign(assertions)
	_test_asymmetric_card_advantage(assertions)
	_test_damage_fragility(assertions)
	_test_registry_drives_breakdown(assertions)


# Minimal snapshot with sensible defaults; override via `over`.
static func _snap(over: Dictionary) -> Dictionary:
	var base := {
		"ai_index": 0,
		"my_score": 0, "opp_score": 0, "victory_score": 8,
		"game_over": false, "winner_index": -1,
		"my_hand": 0, "opp_hand": 0,
		"my_energy": 0, "my_ready_runes": 0, "opp_ready_runes": 0,
		"my_channeled_runes": 0, "opp_channeled_runes": 0,
		"my_unit_might": 0, "opp_unit_might": 0,
		"my_cards_played": 0, "my_cards_discarded": 0,
		"my_hand_reactive": [], "my_ready_rune_domains": [],
		"bf": {}, "bf_scored": [], "units": {},
	}
	for k in over:
		base[k] = over[k]
	return base


static func _unit(owner: int, location: String, might: int, exhausted: bool = false, damage: int = 0) -> Dictionary:
	return {
		"owner": owner, "location": location, "might": might,
		"damage": damage, "exhausted": exhausted, "stunned": false, "keywords": [],
	}


static func _test_win_proximity_convex(assertions) -> void:
	var near := ScoreModel.build_score_features(_snap({}), _snap({"my_score": 7}), [])
	var far := ScoreModel.build_score_features(_snap({}), _snap({"my_score": 4}), [])
	# (7/8)^2 = 0.765625 ; (4/8)^2 = 0.25
	assertions.assert_true(absf(float(near["win_proximity"]) - 0.765625) < 1e-6,
		"win_proximity at 7/8 = (7/8)^2")
	# Convexity: gap 7→6 worth more than 4→3 near the win line.
	var six := ScoreModel.build_score_features(_snap({}), _snap({"my_score": 6}), [])
	var three := ScoreModel.build_score_features(_snap({}), _snap({"my_score": 3}), [])
	var high_gap := float(near["win_proximity"]) - float(six["win_proximity"])
	var low_gap := float(far["win_proximity"]) - float(three["win_proximity"])
	assertions.assert_true(high_gap > low_gap,
		"win_proximity is convex: a point near victory is worth more")


static func _test_per_battlefield_might_margin(assertions) -> void:
	# I dominate battlefield-a; opponent dominates battlefield-b.
	var units := {
		"u1": _unit(0, "battlefield-a", 5),
		"u2": _unit(1, "battlefield-b", 4),
	}
	var feats := ScoreModel.build_score_features(_snap({}), _snap({
		"bf": {"battlefield-a": 0, "battlefield-b": 1}, "units": units,
		"my_unit_might": 5, "opp_unit_might": 4,
	}), [])
	var margin: Dictionary = feats["bf_might_margin"]
	assertions.assert_eq(int(margin["battlefield-a"]), 5, "per-bf margin: +5 at a")
	assertions.assert_eq(int(margin["battlefield-b"]), -4, "per-bf margin: -4 at b")
	# With battlefield_weights a=1.5, b=1.0 the term is 5*1.5 - 4*1.0 = 3.5.
	var profile := ScoringProfileScript.new()
	var bd: Dictionary = profile.score_with_breakdown(feats)["breakdown"]
	var w := float(profile.profile["state_weights"]["battlefield_might_margin"])
	assertions.assert_true(absf(float(bd["battlefield_might_margin"]) - 3.5 * w) < 1e-4,
		"battlefield_might_margin term weights each bf locally")


static func _test_hold_income(assertions) -> void:
	# I control two battlefields but have already scored one this turn.
	var feats := ScoreModel.build_score_features(_snap({}), _snap({
		"bf": {"battlefield-a": 0, "battlefield-b": 0},
		"bf_scored": ["battlefield-a"],
	}), [])
	assertions.assert_eq(int(feats["hold_income"]), 1,
		"hold_income counts only controlled bf not yet scored this turn")


static func _test_control_fragility_sign(assertions) -> void:
	# I control battlefield-a with 2 Might; opponent has 5 ready Might at base that
	# could move in and flip it → fragile (negative).
	var units := {
		"mine": _unit(0, "battlefield-a", 2),
		"opp_reserve": _unit(1, "base", 5, false),
	}
	var feats := ScoreModel.build_score_features(_snap({}), _snap({
		"bf": {"battlefield-a": 0}, "units": units,
	}), [])
	assertions.assert_true(float(feats["control_fragility"]) < 0.0,
		"control_fragility is negative when my battlefield is flippable")


static func _test_asymmetric_card_advantage(assertions) -> void:
	var feats := ScoreModel.build_score_features(_snap({}), _snap({
		"my_hand": 5, "opp_hand": 5,
	}), [])
	# 5 - 0.8*5 = 1.0 (own cards worth more than denying theirs).
	assertions.assert_true(absf(float(feats["cards_in_hand_net"]) - 1.0) < 1e-6,
		"cards_in_hand is asymmetric (my - 0.8*opp)")


static func _test_damage_fragility(assertions) -> void:
	# A damaged enemy unit (good for me) vs an undamaged own unit.
	var units := {
		"enemy": _unit(1, "battlefield-a", 4, false, 3),
		"mine": _unit(0, "battlefield-a", 4, false, 0),
	}
	var feats := ScoreModel.build_score_features(_snap({}), _snap({
		"bf": {"battlefield-a": 1}, "units": units,
	}), [])
	# enemy progress 3/4 positive, mine 0 → positive.
	assertions.assert_true(float(feats["damage_fragility"]) > 0.0,
		"damage_fragility rewards enemy units near death")


static func _test_registry_drives_breakdown(assertions) -> void:
	var feats := ScoreModel.build_score_features(_snap({}), _snap({}), [])
	var profile := ScoringProfileScript.new()
	var bd: Dictionary = profile.score_with_breakdown(feats)["breakdown"]
	for spec in FeatureRegistryScript.specs():
		assertions.assert_true(bd.has(spec["id"]),
			"breakdown contains registry term '%s'" % spec["id"])
	# Legacy terms that were removed must not reappear.
	assertions.assert_false(bd.has("runes_available"),
		"removed term runes_available is gone")