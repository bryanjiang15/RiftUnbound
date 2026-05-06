extends RefCounted
class_name DeckInstanceBuilder

## Converts static Deck definitions into live CardInstance objects for the current run.
##
## Instances are stamped with unique IDs from `scope` so each run's cards are
## distinguishable even when the same definition appears multiple times.

## Instantiates every card in `deck.main` using `scope` for unique ID assignment.
## Returns an empty array if either argument is null.
static func build_main_deck_cards(deck: Deck, scope: InstanceIdScope) -> Array[CardInstance]:
	var out: Array[CardInstance] = []
	if deck == null or scope == null:
		return out
	for def in deck.main:
		if def != null:
			out.append(CardInstance.from_definition(def, scope, 0, 0))
	return out
