extends RefCounted
class_name DeckInstanceBuilder

## Creates runtime CardInstance rows from a deck definition using the run's InstanceIdScope.

static func build_main_deck_cards(deck: Deck, scope: InstanceIdScope) -> Array[CardInstance]:
	var out: Array[CardInstance] = []
	if deck == null or scope == null:
		return out
	for def in deck.main:
		if def != null:
			out.append(CardInstance.from_definition(def, scope, 0, 0))
	return out
