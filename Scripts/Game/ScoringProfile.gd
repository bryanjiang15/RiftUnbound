class_name ScoringProfile
extends RefCounted

# Schema v2 — generic, AI-tunable state/action scoring.
#
# The AI does NOT invent terms in this phase; it only edits the weights in
# Data/AI/scoring_profile.json. Scoring consumes the flat feature dict produced
# by ScoreModel.build_score_features() (state diffs + action/outcome deltas +
# board keyword presence), and returns a weighted sum plus a per-term breakdown.

const DEFAULT_PROFILE_PATH := "res://Data/AI/scoring_profile.json"
const FeatureRegistryScript = preload("res://Scripts/Game/FeatureRegistry.gd")

var profile: Dictionary = {}


func _init(path: String = DEFAULT_PROFILE_PATH) -> void:
	profile = load_profile(path)


# Apply a transient goal overlay to this profile's weights (goal-oriented
# strategist). The overlay is the deterministic compile of an LLM GoalSet; here we
# consume only its weight-modulation part — `weight_multipliers` keyed
# "block.weight_key" (e.g. "state_weights.battlefield_control") — so generic goals
# bias the ACTUAL search, not just post-hoc selection. Specific situational /
# card-target goals are applied server-side as a selection re-rank (they need a
# leaf-predicate evaluator the engine does not yet have). Unknown keys are ignored
# so a malformed overlay degrades to the base profile rather than corrupting it.
func apply_overlay(overlay: Dictionary) -> void:
	if overlay.is_empty():
		return
	var mults: Dictionary = overlay.get("weight_multipliers", {})
	for key in mults:
		var parts := str(key).split(".", true, 1)
		if parts.size() != 2:
			continue
		var block: String = parts[0]
		var wkey: String = parts[1]
		if not profile.has(block):
			continue
		var blockdict = profile[block]
		if typeof(blockdict) != TYPE_DICTIONARY or not blockdict.has(wkey):
			continue
		blockdict[wkey] = float(blockdict[wkey]) * float(mults[key])


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
	var eot: Dictionary = p.get("end_of_turn", {})
	var ai_index := int(features.get("ai_index", 0))
	var my_score := int(features.get("my_score", 0))
	var breakdown: Dictionary = {}

	# ── terminal (special: dominating, not registry-driven) ──
	breakdown["win_game"] = 0.0
	if bool(features.get("game_over", false)):
		var win_w := float(p.get("win_game", 0.0))
		breakdown["win_game"] = win_w if int(features.get("winner_index", -1)) == ai_index else -win_w

	# ── registry-driven terms (generic: one loop over every spec) ──
	for spec in FeatureRegistryScript.specs():
		breakdown[spec["id"]] = _term(features, p, spec)

	# ── end-of-turn (special: composite shaping term) ──
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


# Evaluate one feature spec into its weighted term value. Scalar specs multiply the
# raw feature by its group weight; dict_weighted specs dot a sub-dict feature with a
# named sub-weight block (battlefield_weights / keyword_weights).
static func _term(features: Dictionary, p: Dictionary, spec: Dictionary) -> float:
	var kind := str(spec.get("kind", "scalar"))
	if kind == "dict_weighted":
		var sub: Dictionary = p.get(str(spec.get("subweights", "")), {})
		var sub_default := 1.0 if str(spec.get("subweights", "")) == "battlefield_weights" else 0.0
		var values: Dictionary = features.get(str(spec.get("feature_key", "")), {})
		var total := 0.0
		for k in values:
			total += float(values[k]) * float(sub.get(str(k), sub_default))
		# Optional group-weight multiplier (battlefield terms have one; keywords don't).
		if spec.has("weight_key"):
			var gw: Dictionary = p.get(FeatureRegistryScript.group_weights_key(str(spec.get("group", "state"))), {})
			total *= float(gw.get(str(spec["weight_key"]), 0.0))
		return total
	# scalar
	var wblock: Dictionary = p.get(FeatureRegistryScript.group_weights_key(str(spec.get("group", "state"))), {})
	var w := float(wblock.get(str(spec.get("weight_key", "")), 0.0))
	return float(features.get(str(spec.get("feature_key", "")), 0)) * w


static func _end_of_turn(features: Dictionary, eot: Dictionary) -> float:
	var hand_target := int(eot.get("hand_size_target", 4))
	var hand_weight := float(eot.get("hand_size_weight", 0.5))
	var rune_weight := float(eot.get("rune_weight", 0.3))
	return -absf(float(features.get("my_hand", 0) - hand_target)) * hand_weight + float(features.get("my_ready_runes", 0)) * rune_weight


static func _default_profile() -> Dictionary:
	return {
		"schema_version": "3.0",
		"win_game": 1000.0,
		"state_weights": {
			"score_diff": 10.0,
			"win_proximity": 12.0,
			"hold_income": 3.0,
			"battlefield_control": 5.0,
			"battlefield_might_margin": 0.4,
			"control_fragility": 1.5,
			"unit_might_on_board": 0.15,
			"ready_unit_might": 0.3,
			"idle_base_might": -0.1,
			"damage_fragility": 1.0,
			"cards_in_hand": 0.3,
			"rune_development": 0.3,
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
			"rune_recycled": -1.0,
		},
		"keyword_weights": {
			"assault": 0.4,
			"shield": 0.4,
			"tank": 0.6,
			"ganking": 0.3,
			"deflect": 0.3,
			"deathknell": 0.2,
		},
		"situational_weights": {},
		"battlefield_weights": {"battlefield-a": 1.5, "battlefield-b": 1.0},
		"end_of_turn": {"hand_size_target": 3, "hand_size_weight": 0.3, "rune_weight": 0.5},
	}
