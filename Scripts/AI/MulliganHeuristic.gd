class_name MulliganHeuristic

# Simple, configurable mulligan policy. Each card in hand gets a "keep prior"
# (higher = more desirable to keep) derived from its energy cost and type, then
# the lowest-prior cards that fall below `keep_threshold` are set aside, up to
# `max_set_aside`. Returns a console command string ("mulligan keep" or
# "mulligan <id> [id]") so it plugs into the same submit path as any move.
#
# Priors are read from Data/AI/scoring_profile.json["mulligan"] so they are
# tunable alongside the rest of the AI config; DEFAULT_CONFIG mirrors that block
# and is used when the section is missing.
#
# Intent of the default priors (per game design):
#   - 1-2 cost units  → highest prior (early board presence)
#   - 2 cost cards    → high prior
#   - 3 cost cards    → decent prior
#   - higher cost     → progressively lower prior (likely mulligan targets)

const DEFAULT_CONFIG := {
	"max_set_aside": 2,
	"keep_threshold": 3.0,
	"cost_prior": {"0": 3.0, "1": 4.0, "2": 7.0, "3": 5.0, "4": 2.0, "5": 1.0, "default": 0.5},
	"low_cost_unit_prior": 10.0,
	"low_cost_unit_max_cost": 2,
}


static func default_config() -> Dictionary:
	return DEFAULT_CONFIG.duplicate(true)


# Keep-desirability for a single card. Low-cost units get the dedicated unit
# prior; everything else uses the per-cost table (falling back to "default").
static func card_prior(card_type: String, energy_cost: int, config: Dictionary) -> float:
	var cfg := config if not config.is_empty() else DEFAULT_CONFIG
	var low_max := int(cfg.get("low_cost_unit_max_cost", 2))
	if card_type == "unit" and energy_cost <= low_max:
		return float(cfg.get("low_cost_unit_prior", 10.0))
	var cost_prior: Dictionary = cfg.get("cost_prior", {})
	var key := str(energy_cost)
	if cost_prior.has(key):
		return float(cost_prior[key])
	return float(cost_prior.get("default", 0.5))


# Decide the mulligan command for the given seat's current hand.
static func choose_command(gs: GameState, player_index: int, config: Dictionary = {}) -> String:
	var cfg := config if not config.is_empty() else DEFAULT_CONFIG
	if gs == null or player_index < 0 or player_index >= gs.players.size():
		return "mulligan keep"
	var ps: PlayerState = gs.players[player_index]
	var threshold := float(cfg.get("keep_threshold", 3.0))
	var max_aside := int(cfg.get("max_set_aside", 2))

	# Rank hand cards worst-first so the weakest keep-priors are mulligan targets.
	var ranked: Array = []
	for c in ps.hand:
		ranked.append({
			"id": c.instance_id,
			"prior": card_prior(c.definition.card_type, c.definition.energy_cost, cfg),
		})
	ranked.sort_custom(func(a, b): return float(a["prior"]) < float(b["prior"]))

	var set_aside: Array = []
	for entry in ranked:
		if set_aside.size() >= max_aside:
			break
		if float(entry["prior"]) < threshold:
			set_aside.append(str(entry["id"]))

	if set_aside.is_empty():
		return "mulligan keep"
	return "mulligan %s" % " ".join(PackedStringArray(set_aside))
