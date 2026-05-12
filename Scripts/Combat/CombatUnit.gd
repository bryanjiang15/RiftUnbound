extends RefCounted
class_name CombatUnit

## Source-agnostic runtime combat unit.
##
## All combat-relevant stats are copied from the source at creation time.
## The resolver never branches on source type; only the factory methods know
## where stats come from. This allows ally cards and summons to participate
## in combat without changing the resolver.

enum SourceKind { CHAMPION, ALLY_CARD, SUMMON }

# ── Identity (event log / UI replay only) ───────────────────────────────────
## Unique id within this combat (assigned by CombatBoard.from_snapshot).
var instance_id: int = 0
## What created this unit.
var source_kind: SourceKind = SourceKind.CHAMPION
## instance_id of the originating ChampionInstance / CardInstance.
var source_id: int = 0
## Human-readable name for event log and UI tokens.
var display_name: String = ""

# ── Placement ────────────────────────────────────────────────────────────────
var is_player_side: bool = true
## Mutable cell position during combat.
var cell: GridCoord

# ── Combat stats (copied once; never written back to the source) ─────────────
var max_health: int = 0
var current_health: int = 0
var attack: int = 0
var defense: int = 0
var speed: int = 0

## Returns true while this unit has positive health.
func is_alive() -> bool:
	return current_health > 0

## Creates a CombatUnit from a placed ChampionInstance.
## combat_id must be unique within the combat (typically an auto-increment counter).
static func from_champion(
	inst: ChampionInstance,
	player_side: bool,
	combat_id: int
) -> CombatUnit:
	var u := CombatUnit.new()
	u.instance_id  = combat_id
	u.source_kind  = SourceKind.CHAMPION
	u.source_id    = inst.instance_id
	u.display_name = inst.definition.display_name if inst.definition != null else "?"
	u.is_player_side = player_side
	u.cell = inst.cell
	if inst.stats != null:
		u.max_health     = inst.stats.max_health
		u.current_health = inst.stats.current_health if inst.stats.current_health > 0 else inst.stats.max_health
		u.attack  = inst.stats.attack
		u.defense = inst.stats.defense
		u.speed   = inst.stats.speed
	return u

## Creates a stub CombatUnit from a deployed ally CardInstance.
## Stats are set to 0 until ally combat is implemented in a later phase.
static func from_ally_card(
	inst: CardInstance,
	p_cell: GridCoord,
	player_side: bool,
	combat_id: int
) -> CombatUnit:
	var u := CombatUnit.new()
	u.instance_id  = combat_id
	u.source_kind  = SourceKind.ALLY_CARD
	u.source_id    = inst.instance_id
	u.display_name = inst.definition.title if inst.definition != null else "Ally"
	u.is_player_side = player_side
	u.cell = p_cell
	# Stats populated from CardData in a later phase.
	return u
