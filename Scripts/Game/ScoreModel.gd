class_name ScoreModel
extends RefCounted

# Pure snapshot + scoring-feature math for the AI search. No GameController / Node
# coupling: every entry point takes a GameState (or plain snapshot dicts) and the
# acting AI seat, and returns plain dictionaries. MoveSimulator (simulation
# control) and TurnSearch (the beam search) both compose this; keeping it separate
# keeps each file focused and gives the search a stable public surface instead of
# reaching into simulator privates.

# Board-presence keywords surfaced to the scorer. These are the generic, unit
# state keywords whose presence on field/base units carries positional value
# (combat math, mobility, protection) independent of any specific card.
const SCORED_KEYWORDS := ["assault", "shield", "tank", "ganking", "deflect", "deathknell"]


# ── Snapshot ──────────────────────────────────────────────────────────────────


static func snapshot(gs: GameState, ai_index: int) -> Dictionary:
	var me: PlayerState = gs.players[ai_index]
	var opp: PlayerState = gs.players[1 - ai_index]
	var bf: Dictionary = {}
	var bf_scored: Array = []
	for i in range(gs.board.battlefields.size()):
		var entry = gs.board.battlefields[i]
		bf[entry.battlefield_id] = entry.controller_index
		if i in me.battlefields_scored_this_turn:
			bf_scored.append(entry.battlefield_id)
	var units: Dictionary = {}
	var my_might := 0
	var opp_might := 0
	for u in gs.all_units_on_board():
		var might := u.get_current_might()
		units[u.instance_id] = {
			"owner": u.owner_index,
			"location": u.location,
			"might": might,
			"damage": u.damage,
			"exhausted": u.is_exhausted,
			"stunned": u.is_stunned,
			"keywords": _unit_keywords(u),
		}
		if u.owner_index == ai_index:
			my_might += might
		else:
			opp_might += might
	for u in me.get_units_at_base():
		var might := u.get_current_might()
		units[u.instance_id] = {
			"owner": u.owner_index, "location": "base",
			"might": might, "damage": u.damage,
			"exhausted": u.is_exhausted, "stunned": u.is_stunned,
			"keywords": _unit_keywords(u),
		}
		my_might += might
	for u in opp.get_units_at_base():
		var might := u.get_current_might()
		units[u.instance_id] = {
			"owner": u.owner_index, "location": "base",
			"might": might, "damage": u.damage,
			"exhausted": u.is_exhausted, "stunned": u.is_stunned,
			"keywords": _unit_keywords(u),
		}
		opp_might += might
	return {
		"ai_index": ai_index,
		"my_score": me.score,
		"opp_score": opp.score,
		"victory_score": gs.victory_score,
		"game_over": gs.game_over,
		"winner_index": gs.winner_index,
		"my_hand": me.hand.size(),
		"opp_hand": opp.hand.size(),
		"my_energy": me.rune_pool.energy,
		"my_ready_runes": ready_runes(me),
		"opp_ready_runes": ready_runes(opp),
		"my_unit_might": my_might,
		"opp_unit_might": opp_might,
		"my_cards_played": me.cards_played_this_turn,
		"my_cards_discarded": me.cards_discarded_count,
		"my_hand_reactive": _reactive_hand_costs(me),
		"my_ready_rune_domains": _ready_rune_domains(me),
		"bf": bf,
		"bf_scored": bf_scored,
		"units": units,
	}


static func ready_runes(ps: PlayerState) -> int:
	var count := 0
	for rune in ps.channeled_runes:
		if not rune.is_exhausted:
			count += 1
	return count


# Costs of the Action/Reaction cards in hand — the cards the AI could play during
# the opponent's turn (Action in showdowns, Reaction in closed states). Each entry
# is {energy, power:[{domain, amount}]}. Used to gauge reactive readiness.
static func _reactive_hand_costs(ps: PlayerState) -> Array:
	var out: Array = []
	for card in ps.hand:
		var def: CardDefinition = card.definition
		if def == null:
			continue
		if not (def.is_action or def.is_reaction):
			continue
		out.append({"energy": def.energy_cost, "power": def.power_cost.duplicate(true)})
	return out


# Domains of the player's ready (un-exhausted) channeled runes. Each ready rune is
# a flexible resource: it can tap for 1 energy or recycle for 1 power of its domain.
static func _ready_rune_domains(ps: PlayerState) -> Array:
	var out: Array = []
	for rune in ps.channeled_runes:
		if rune.is_exhausted:
			continue
		var def: CardDefinition = rune.definition
		var domain := "any"
		if def != null and def.domain is Array and not def.domain.is_empty():
			domain = str(def.domain[0])
		out.append(domain)
	return out


# Tracked board-presence keywords currently on a unit, used by the scorer to
# value generic unit qualities (combat keywords, mobility) on field/base.
static func _unit_keywords(u: CardInstance) -> Array:
	var kws: Array = []
	for kw_id in SCORED_KEYWORDS:
		if u.has_keyword(kw_id):
			kws.append(kw_id)
	return kws


# ── Scoring features ──────────────────────────────────────────────────────────


# Flatten a search line into the flat feature dict the scorer consumes. Merges
# leaf-state features (positional) with action/outcome deltas measured against
# the root snapshot and the line's executed steps. Keeping this here (rather than
# in ScoringProfile) keeps the scorer decoupled from snapshot internals.
static func build_score_features(root_snap: Dictionary, leaf_snap: Dictionary, steps: Array) -> Dictionary:
	var ai_index := int(leaf_snap.get("ai_index", 0))
	var features: Dictionary = {}

	# ── passthrough (terminal + battlefield weighting + end-of-turn) ──
	features["ai_index"] = ai_index
	features["game_over"] = bool(leaf_snap.get("game_over", false))
	features["winner_index"] = int(leaf_snap.get("winner_index", -1))
	features["my_score"] = int(leaf_snap.get("my_score", 0))
	features["opp_score"] = int(leaf_snap.get("opp_score", 0))
	features["victory_score"] = int(leaf_snap.get("victory_score", 8))
	features["bf"] = leaf_snap.get("bf", {})
	features["bf_scored"] = leaf_snap.get("bf_scored", [])
	features["my_hand"] = int(leaf_snap.get("my_hand", 0))
	features["my_ready_runes"] = int(leaf_snap.get("my_ready_runes", 0))

	# ── state diffs (me vs opponent at the leaf) ──
	features["score_diff"] = int(leaf_snap.get("my_score", 0)) - int(leaf_snap.get("opp_score", 0))
	features["unit_might_diff"] = int(leaf_snap.get("my_unit_might", 0)) - int(leaf_snap.get("opp_unit_might", 0))
	features["cards_in_hand_self"] = int(leaf_snap.get("my_hand", 0))
	# features["cards_in_hand_opponent"] = int(leaf_snap.get("opp_hand", 0))
	features["runes_available_diff"] = int(leaf_snap.get("my_ready_runes", 0)) - int(leaf_snap.get("opp_ready_runes", 0))
	features["keyword_net"] = _keyword_net(leaf_snap, ai_index)
	# How many Action/Reaction cards in hand the AI can actually afford to play on
	# the opponent's turn with its leftover ready runes (a combination check when
	# more than one is individually affordable). Rewards ending the turn with live
	# reactive threats rather than a tapped-out board. unusable_runes counts ready
	# runes that no reactive card could ever consume — dead weight, slightly bad.
	var reactive := _reactive_eval(leaf_snap)
	features["reactive_potential"] = reactive["potential"]
	features["unusable_runes"] = maxi(0, int(leaf_snap.get("my_ready_runes", 0)) - int(reactive["usable_runes"]))

	# ── action / outcome deltas (root → leaf) ──
	features["cards_played"] = int(leaf_snap.get("my_cards_played", 0)) - int(root_snap.get("my_cards_played", 0))
	features["cards_discarded"] = int(leaf_snap.get("my_cards_discarded", 0)) - int(root_snap.get("my_cards_discarded", 0))
	features["units_moved"] = _count_move_steps(steps)
	features["points_scored"] = int(leaf_snap.get("my_score", 0)) - int(root_snap.get("my_score", 0))
	features["cards_drawn"] = maxi(0, int(leaf_snap.get("my_hand", 0)) - int(root_snap.get("my_hand", 0)))
	# Spending runes is not penalised (the pool empties each turn anyway, and
	# reactive_potential already values leftover ready runes); spending domain
	# power is slightly penalised below as a tempo cost.
	features["power_used"] = maxi(0, int(root_snap.get("my_energy", 0)) - int(leaf_snap.get("my_energy", 0)))

	var kills := _unit_losses(root_snap, leaf_snap, ai_index)
	features["enemy_units_killed"] = kills["enemy"]
	features["own_units_lost"] = kills["own"]

	# Holding fix: a conquer only earns a point — and so only counts as an
	# aggression signal — if that battlefield was actually scored this turn
	# (each battlefield scores at most once per turn). Re-taking an already
	# scored battlefield no longer inflates the score.
	features["battlefields_conquered"] = _scoring_conquers(root_snap, leaf_snap, ai_index)
	return features


static func _keyword_net(snap: Dictionary, ai_index: int) -> Dictionary:
	var net: Dictionary = {}
	for kw_id in SCORED_KEYWORDS:
		net[kw_id] = 0
	var units: Dictionary = snap.get("units", {})
	for inst_id in units:
		var u: Dictionary = units[inst_id]
		var sign := 1 if int(u.get("owner", -1)) == ai_index else -1
		for kw_id in u.get("keywords", []):
			net[kw_id] = int(net.get(kw_id, 0)) + sign
	return net


static func _count_move_steps(steps: Array) -> int:
	var count := 0
	for step in steps:
		if str(step.get("kind", "scripted")) != "scripted":
			continue
		if str(step.get("command", "")).begins_with("move "):
			count += 1
	return count


static func _unit_losses(root_snap: Dictionary, leaf_snap: Dictionary, ai_index: int) -> Dictionary:
	var enemy := 0
	var own := 0
	var root_units: Dictionary = root_snap.get("units", {})
	var leaf_units: Dictionary = leaf_snap.get("units", {})
	for inst_id in root_units:
		if leaf_units.has(inst_id):
			continue
		if int(root_units[inst_id].get("owner", -1)) == ai_index:
			own += 1
		else:
			enemy += 1
	return {"enemy": enemy, "own": own}


static func _scoring_conquers(root_snap: Dictionary, leaf_snap: Dictionary, ai_index: int) -> int:
	var count := 0
	var root_bf: Dictionary = root_snap.get("bf", {})
	var leaf_bf: Dictionary = leaf_snap.get("bf", {})
	var scored: Array = leaf_snap.get("bf_scored", [])
	for bf_id in leaf_bf:
		if int(leaf_bf[bf_id]) != ai_index:
			continue
		if int(root_bf.get(bf_id, -1)) == ai_index:
			continue
		if bf_id in scored:
			count += 1
	return count


# Evaluate the AI's reactive resource situation from its leftover ready runes and
# the Action/Reaction cards in hand. Each ready rune is one flexible resource (1
# energy via tap, or 1 power of its domain via recycle). Returns:
#   "potential":     largest set of A/R cards payable SIMULTANEOUSLY (the reactive
#                    threat) — brute-forced over subsets since hands are tiny.
#   "usable_runes":  the most runes any payable subset could actually consume, so
#                    callers can derive how many ready runes are dead weight.
static func _reactive_eval(snap: Dictionary) -> Dictionary:
	var cards: Array = snap.get("my_hand_reactive", [])
	var runes: Array = snap.get("my_ready_rune_domains", [])
	if cards.is_empty() or runes.is_empty():
		return {"potential": 0, "usable_runes": 0}
	# Cap to keep the subset enumeration bounded on pathological hands.
	if cards.size() > 12:
		cards = cards.slice(0, 12)
	var n := cards.size()
	var best_count := 0
	var best_runes := 0
	for mask in range(1, 1 << n):
		var energy := 0
		var power: Array = []
		var size := 0
		for i in range(n):
			if mask & (1 << i):
				size += 1
				energy += int(cards[i].get("energy", 0))
				for pc in cards[i].get("power", []):
					power.append(pc)
		if not _runes_can_pay(runes, energy, power):
			continue
		# Runes a payable subset consumes equals its total cost (one rune per
		# energy or power pip), so it bounds how many runes can be put to use.
		var rune_cost := energy
		for pc in power:
			rune_cost += int(pc.get("amount", 0))
		best_count = maxi(best_count, size)
		best_runes = maxi(best_runes, rune_cost)
	return {"potential": best_count, "usable_runes": best_runes}


# Can a pool of ready runes (domains) cover energy + power costs? Each rune covers
# either 1 energy or 1 power of its own domain (or any domain, for an "any" rune).
static func _runes_can_pay(rune_domains: Array, energy_cost: int, power_cost: Array) -> bool:
	var avail: Dictionary = {}
	var any_runes := 0
	for d in rune_domains:
		if str(d) == "any":
			any_runes += 1
		else:
			avail[d] = int(avail.get(d, 0)) + 1
	var any_power := 0
	# Satisfy specific-domain power needs from matching-domain runes first,
	# falling back to "any" runes when a domain is short.
	for pc in power_cost:
		var d := str(pc.get("domain", ""))
		var amt := int(pc.get("amount", 0))
		if d == "any" or d == "":
			any_power += amt
			continue
		var have := int(avail.get(d, 0))
		var use := mini(have, amt)
		avail[d] = have - use
		amt -= use
		if amt > 0:
			if any_runes < amt:
				return false
			any_runes -= amt
	# Remaining runes (domain leftovers + any) cover "any" power and energy.
	var leftover := any_runes
	for d in avail:
		leftover += int(avail[d])
	return leftover >= energy_cost + any_power


# ── Hashing ───────────────────────────────────────────────────────────────────


static func structural_hash(snapshot_dict: Dictionary) -> String:
	return JSON.stringify(_canonicalize(snapshot_dict))


static func _canonicalize(value: Variant) -> Variant:
	if value is Dictionary:
		var out: Dictionary = {}
		var keys: Array = value.keys()
		keys.sort()
		for key in keys:
			out[str(key)] = _canonicalize(value[key])
		return out
	if value is Array:
		var arr: Array = []
		for item in value:
			arr.append(_canonicalize(item))
		return arr
	return value
