class_name ScoringProfile
extends RefCounted

# Schema v2 — generic, AI-tunable state/action scoring.
#
# The AI does NOT invent terms in this phase; it only edits the weights in
# Data/AI/scoring_profile.json. Scoring consumes the flat feature dict produced
# by ScoreModel.build_score_features() (state diffs + action/outcome deltas +
# board keyword presence), and returns a weighted sum plus a per-term breakdown.

const DEFAULT_PROFILE_PATH := "res://Data/AI/scoring_profile.json"

var profile: Dictionary = {}


func _init(path: String = DEFAULT_PROFILE_PATH) -> void:
	profile = load_profile(path)


static func load_profile(path: String = DEFAULT_PROFILE_PATH) -> Dictionary:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		push_warning("ScoringProfile: could not open %s" % path)
		return _default_profile()
	var parsed = JSON.parse_string(file.get_as_text())
	if parsed == null or not parsed is Dictionary:
		push_warning("ScoringProfile: invalid JSON in %s" % path)
		return _default_profile()
	return parsed


func score_with_breakdown(features: Dictionary) -> Dictionary:
	var p := profile if not profile.is_empty() else _default_profile()
	var state_w: Dictionary = p.get("state_weights", {})
	var action_w: Dictionary = p.get("action_weights", {})
	var keyword_w: Dictionary = p.get("keyword_weights", {})
	var bf_w: Dictionary = p.get("battlefield_weights", {})
	var eot: Dictionary = p.get("end_of_turn", {})
	var ai_index := int(features.get("ai_index", 0))
	var my_score := int(features.get("my_score", 0))
	var breakdown: Dictionary = {}

	# ── terminal ──
	breakdown["win_game"] = 0.0
	if bool(features.get("game_over", false)):
		var win_w := float(p.get("win_game", 0.0))
		breakdown["win_game"] = win_w if int(features.get("winner_index", -1)) == ai_index else -win_w

	# ── state terms (positional, me vs opponent) ──
	breakdown["score_diff"] = float(features.get("score_diff", 0)) * _w(state_w, "score_diff")
	breakdown["battlefield_control"] = _battlefield_control(features, ai_index, bf_w) * _w(state_w, "battlefield_control")
	breakdown["unit_might_on_board"] = float(features.get("unit_might_diff", 0)) * _w(state_w, "unit_might_on_board")
	breakdown["cards_in_hand"] = float(features.get("cards_in_hand_self", 0)) * _w(state_w, "cards_in_hand")
	breakdown["runes_available"] = float(features.get("runes_available_diff", 0)) * _w(state_w, "runes_available")
	breakdown["reactive_potential"] = float(features.get("reactive_potential", 0)) * _w(state_w, "reactive_potential")
	breakdown["unusable_runes"] = float(features.get("unusable_runes", 0)) * _w(state_w, "unusable_runes")
	breakdown["keywords"] = _keyword_score(features.get("keyword_net", {}), keyword_w)

	# ── action / outcome terms (what the line did) ──
	breakdown["card_played"] = float(features.get("cards_played", 0)) * _w(action_w, "card_played")
	breakdown["unit_moved"] = float(features.get("units_moved", 0)) * _w(action_w, "unit_moved")
	breakdown["card_discarded"] = float(features.get("cards_discarded", 0)) * _w(action_w, "card_discarded")
	breakdown["enemy_unit_killed"] = float(features.get("enemy_units_killed", 0)) * _w(action_w, "enemy_unit_killed")
	breakdown["own_unit_lost"] = float(features.get("own_units_lost", 0)) * _w(action_w, "own_unit_lost")
	breakdown["battlefield_conquered"] = float(features.get("battlefields_conquered", 0)) * _w(action_w, "battlefield_conquered")
	breakdown["point_scored"] = float(features.get("points_scored", 0)) * _w(action_w, "point_scored")
	breakdown["card_drawn"] = float(features.get("cards_drawn", 0)) * _w(action_w, "card_drawn")
	breakdown["power_used"] = float(features.get("power_used", 0)) * _w(action_w, "power_used")
	breakdown["end_of_turn"] = _end_of_turn(features, eot)

	var shaping := 0.0
	for key in breakdown:
		if key != "win_game":
			shaping += float(breakdown[key])
	var win_weight := absf(float(p.get("win_game", 0.0)))
	var clamp_limit := maxf(0.0, win_weight - 1.0)
	if absf(shaping) > clamp_limit:
		shaping = signf(shaping) * clamp_limit
		breakdown["shaping_clamped"] = true
	else:
		breakdown["shaping_clamped"] = false
	var score := float(breakdown["win_game"]) + shaping
	breakdown["total"] = score
	breakdown["points_to_win"] = int(features.get("victory_score", 8)) - my_score
	return {"score": score, "breakdown": breakdown}


static func _battlefield_control(features: Dictionary, ai_index: int, bf_weights: Dictionary) -> float:
	var total := 0.0
	var controls: Dictionary = features.get("bf", {})
	for bf_id in controls:
		var weight := float(bf_weights.get(str(bf_id), 1.0))
		var ctrl := int(controls[bf_id])
		if ctrl == ai_index:
			total += weight
		elif ctrl >= 0:
			total -= weight
	return total


static func _keyword_score(keyword_net: Dictionary, keyword_weights: Dictionary) -> float:
	var total := 0.0
	for kw_id in keyword_net:
		total += float(keyword_net[kw_id]) * float(keyword_weights.get(str(kw_id), 0.0))
	return total


static func _end_of_turn(features: Dictionary, eot: Dictionary) -> float:
	var hand_target := int(eot.get("hand_size_target", 4))
	var hand_weight := float(eot.get("hand_size_weight", 0.5))
	var rune_weight := float(eot.get("rune_weight", 0.3))
	return -absf(float(features.get("my_hand", 0) - hand_target)) * hand_weight + float(features.get("my_ready_runes", 0)) * rune_weight


static func _w(weights: Dictionary, key: String) -> float:
	return float(weights.get(key, 0.0))


static func _default_profile() -> Dictionary:
	return {
		"schema_version": "2.0",
		"win_game": 1000.0,
		"state_weights": {
			"score_diff": 10.0,
			"battlefield_control": 5.0,
			"unit_might_on_board": 0.5,
			"cards_in_hand": 0.3,
			"runes_available": -0.1,
			"reactive_potential": 1.0,
			"unusable_runes": -0.15,
		},
		"action_weights": {
			"card_played": 0.75,
			"unit_moved": 0.2,
			"card_discarded": -0.5,
			"enemy_unit_killed": 1.5,
			"own_unit_lost": -1.5,
			"battlefield_conquered": 4.0,
			"point_scored": 8.0,
			"card_drawn": 0.4,
			"power_used": -0.05,
		},
		"keyword_weights": {
			"assault": 0.4,
			"shield": 0.4,
			"tank": 0.6,
			"ganking": 0.3,
			"deflect": 0.3,
			"deathknell": 0.2,
		},
		"battlefield_weights": {"battlefield-a": 1.5, "battlefield-b": 1.0},
		"end_of_turn": {"hand_size_target": 3, "hand_size_weight": 0.3, "rune_weight": 0.5},
	}
