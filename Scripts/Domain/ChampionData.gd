extends Resource
class_name ChampionData

## Static champion roster entry (not a CardData). Items, equipment, allies, spells use CardData.

@export var definition_id: StringName = &""
@export var display_name: String = ""
@export var portrait: Texture2D
@export var base_stats: CombatStats

## Identity / deck-building hooks (stub until design locks colors).
@export var color_tag: StringName = &""

## Reserved for data-driven abilities (Phase D).
@export var ability_resource_ids: PackedStringArray = []
