class_name FeatureRegistry
extends RefCounted

# ── Single source of truth for the linear-eval feature space ──────────────────
#
# Every scored feature is described ONCE here as a declarative spec. Both the
# GDScript scorer (ScoringProfile.score_with_breakdown) and the Python tuning /
# reporting tools (texel_tune.py, feature_report.py) consume this list so they
# can never drift:
#
#   ScoreModel.build_score_features()  → raw feature dict (one value per feature_key)
#   FeatureRegistry.specs()            → how each raw value becomes a weighted term
#   ScoringProfile.score_with_breakdown() → generic loop over specs
#   Data/AI/feature_registry.json      → exported manifest the Python side loads
#
# To ADD or CHANGE a scored feature you touch exactly two places:
#   1. compute its raw value in ScoreModel.build_score_features()
#   2. add/edit its spec here (and a default weight in scoring_profile.json)
# Then regenerate the manifest (see export_manifest below). Nothing else.
#
# Spec fields:
#   id          term name (key in score_breakdown; must be unique)
#   group       weights block in the profile: "state" | "action" | "situational"
#   kind        "scalar"        → term = features[feature_key] * weight
#               "dict_weighted" → term = (Σ features[feature_key][k] * subweights[k])
#                                 optionally × the group weight named by weight_key.
#                                 (k iterates the sub-dict; subweights comes from the
#                                  named sub-weight block. battlefield terms scale by a
#                                  group weight_key; keywords use sub-weights only.)
#   feature_key key into the raw feature dict produced by ScoreModel
#   weight_key  key under the group's weights block (scalar kind only)
#   subweights  name of the sub-weight block (dict_weighted kind only):
#               "battlefield_weights" | "keyword_weights"
#   sign_hint   expected sign of a healthy weight (+1 good, -1 bad, 0 unknown);
#               used by diagnostics to flag sign-flipped tuned weights
#   doc         one-line human description
#
# NOT listed here (handled specially by ScoringProfile, held fixed by the tuner):
#   win_game (terminal, dominating) and end_of_turn (composite shaping term).


# Returns the ordered list of feature specs. Pure data (no Callables) so it can be
# JSON-serialised verbatim into the manifest.
static func specs() -> Array:
	return [
		# ── State: win condition & race ──────────────────────────────────────
		{
			"id": "score_diff", "group": "state", "kind": "scalar",
			"feature_key": "score_diff", "weight_key": "score_diff",
			"sign_hint": 1, "doc": "my points − opp points",
		},
		{
			"id": "win_proximity", "group": "state", "kind": "scalar",
			"feature_key": "win_proximity", "weight_key": "win_proximity",
			"sign_hint": 1,
			"doc": "convex closeness to victory: (my/victory)^2 − (opp/victory)^2",
		},
		{
			"id": "hold_income", "group": "state", "kind": "scalar",
			"feature_key": "hold_income", "weight_key": "hold_income",
			"sign_hint": 1,
			"doc": "battlefields I control not yet scored this turn (future Hold points)",
		},
		# ── State: battlefield control & contestation ────────────────────────
		{
			"id": "battlefield_control", "group": "state", "kind": "dict_weighted",
			"feature_key": "bf_control_net", "subweights": "battlefield_weights",
			"weight_key": "battlefield_control",
			"sign_hint": 1, "doc": "net battlefield control, weighted per battlefield",
		},
		{
			"id": "battlefield_might_margin", "group": "state", "kind": "dict_weighted",
			"feature_key": "bf_might_margin", "subweights": "battlefield_weights",
			"weight_key": "battlefield_might_margin",
			"sign_hint": 1,
			"doc": "per-battlefield (my − opp) Might, weighted per battlefield (local, not global)",
		},
		{
			"id": "control_fragility", "group": "state", "kind": "scalar",
			"feature_key": "control_fragility", "weight_key": "control_fragility",
			"sign_hint": 1,
			"doc": "my threats on opp battlefields − opp threats on mine (flippability)",
		},
		# ── State: development & tempo ───────────────────────────────────────
		{
			"id": "unit_might_on_board", "group": "state", "kind": "scalar",
			"feature_key": "unit_might_diff", "weight_key": "unit_might_on_board",
			"sign_hint": 1, "doc": "global (my − opp) Might; weak fallback",
		},
		{
			"id": "ready_unit_might", "group": "state", "kind": "scalar",
			"feature_key": "ready_unit_might_diff", "weight_key": "ready_unit_might",
			"sign_hint": 1,
			"doc": "(my − opp) Might of un-exhausted units deployed to battlefields (tempo)",
		},
		{
			"id": "idle_base_might", "group": "state", "kind": "scalar",
			"feature_key": "idle_base_might_diff", "weight_key": "idle_base_might",
			"sign_hint": -1,
			"doc": "(my − opp) Might sitting at Base, off-objective",
		},
		{
			"id": "damage_fragility", "group": "state", "kind": "scalar",
			"feature_key": "damage_fragility", "weight_key": "damage_fragility",
			"sign_hint": 1,
			"doc": "enemy damage-progress toward death − my damage-progress (closer enemy deaths good)",
		},
		{
			"id": "keywords", "group": "state", "kind": "dict_weighted",
			"feature_key": "keyword_net", "subweights": "keyword_weights",
			"sign_hint": 1, "doc": "per-keyword net presence (mine − opp), weighted per keyword",
		},
		# ── State: card & resource advantage ─────────────────────────────────
		{
			"id": "cards_in_hand", "group": "state", "kind": "scalar",
			"feature_key": "cards_in_hand_net", "weight_key": "cards_in_hand",
			"sign_hint": 1,
			"doc": "my hand − k·opp hand (asymmetric card advantage; k baked into feature)",
		},
		{
			"id": "rune_development", "group": "state", "kind": "scalar",
			"feature_key": "rune_development_diff", "weight_key": "rune_development",
			"sign_hint": 1, "doc": "(my − opp) channeled runes (persistent ramp)",
		},
		{
			"id": "reactive_potential", "group": "state", "kind": "scalar",
			"feature_key": "reactive_potential", "weight_key": "reactive_potential",
			"sign_hint": 1, "doc": "A/R cards in hand payable with leftover ready runes",
		},
		{
			"id": "unusable_runes", "group": "state", "kind": "scalar",
			"feature_key": "unusable_runes", "weight_key": "unusable_runes",
			"sign_hint": -1, "doc": "ready runes no reactive card could consume (dead weight)",
		},
		# ── Action / outcome deltas (root → leaf) ────────────────────────────
		{
			"id": "card_played", "group": "action", "kind": "scalar",
			"feature_key": "cards_played", "weight_key": "card_played",
			"sign_hint": 1, "doc": "cards I played this line",
		},
		{
			"id": "unit_moved", "group": "action", "kind": "scalar",
			"feature_key": "units_moved", "weight_key": "unit_moved",
			"sign_hint": 1, "doc": "scripted move steps in the line",
		},
		{
			"id": "card_discarded", "group": "action", "kind": "scalar",
			"feature_key": "cards_discarded", "weight_key": "card_discarded",
			"sign_hint": -1, "doc": "cards I discarded this line",
		},
		{
			"id": "enemy_unit_killed", "group": "action", "kind": "scalar",
			"feature_key": "enemy_units_killed", "weight_key": "enemy_unit_killed",
			"sign_hint": 1, "doc": "enemy units removed root→leaf",
		},
		{
			"id": "own_unit_lost", "group": "action", "kind": "scalar",
			"feature_key": "own_units_lost", "weight_key": "own_unit_lost",
			"sign_hint": -1, "doc": "own units lost root→leaf",
		},
		{
			"id": "battlefield_conquered", "group": "action", "kind": "scalar",
			"feature_key": "battlefields_conquered", "weight_key": "battlefield_conquered",
			"sign_hint": 1, "doc": "battlefields newly controlled and scored this turn",
		},
		{
			"id": "point_scored", "group": "action", "kind": "scalar",
			"feature_key": "points_scored", "weight_key": "point_scored",
			"sign_hint": 1, "doc": "points gained root→leaf",
		},
		{
			"id": "card_drawn", "group": "action", "kind": "scalar",
			"feature_key": "cards_drawn", "weight_key": "card_drawn",
			"sign_hint": 1, "doc": "non-negative hand increase root→leaf",
		},
		{
			"id": "power_used", "group": "action", "kind": "scalar",
			"feature_key": "power_used", "weight_key": "power_used",
			"sign_hint": -1, "doc": "domain power spent root→leaf (small tempo cost)",
		},
		{
			"id": "rune_recycled", "group": "action", "kind": "scalar",
			"feature_key": "runes_recycled", "weight_key": "rune_recycled",
			"sign_hint": -1, "doc": "own channeled runes permanently recycled/removed root→leaf",
		},
	]


# Map a group name to its weights block key in the profile JSON.
static func group_weights_key(group: String) -> String:
	match group:
		"state":
			return "state_weights"
		"action":
			return "action_weights"
		"situational":
			return "situational_weights"
		_:
			return "%s_weights" % group


# Serialise the registry (plus situational specs from config) to the JSON manifest
# the Python tooling consumes. Run via the headless export entry point so the
# manifest is always regenerated from this file — never hand-edited.
static func export_manifest(situational: Array = []) -> Dictionary:
	return {
		"schema_version": "3.0",
		"specs": specs(),
		"situational": situational,
	}
