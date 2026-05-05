extends Resource
class_name CardData

## Playable cards: items, equipment, allies, spells. Champions use ChampionData, not CardData.

enum CardType {
	ITEM,
	EQUIPMENT,
	ALLY,
	SPELL,
	OTHER,
}

@export_category('Domain')
@export var card_kind: CardType = CardType.OTHER
@export var definition_id: StringName = &""

@export_category('Stats')
@export var title: String
@export var cost: int
@export var power: int
@export var defense: int
@export_multiline var text: String
@export var image: Texture2D

@export_category('Effects')
@export var effects: Dictionary[EffectTypes, Array]

## Deprecated for run mode: use CardInstance.instance_id / owner / controller for new code.
var instance_id: String = 'default'
var controller: int
var owner: int

enum EffectTypes {
	Resolve,
	EnterField,
	EnterGY,
	EnterBanish,
	EnterHand,
	EnterDeck,
	EffectActivated
}

func get_effects(type: EffectTypes) -> Array[Effect]:
	return effects[type]

## Hardcoded effect example
func _init():
	effects[EffectTypes.Resolve] = [Effect.Create(self).description("Pass priority.").then(PassAction.Create(self))]

func _validate_for_deck(deck: Array[CardData]):
	instance_id = 'deck'
	return true

func _add_to_game():
	instance_id = OS.get_unique_id()
