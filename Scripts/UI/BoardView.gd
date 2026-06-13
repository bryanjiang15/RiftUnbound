class_name BoardView
extends Control

signal card_hovered(inst: CardInstance)
signal card_unhovered()
signal card_clicked(inst: CardInstance)

# ── Layout constants ──────────────────────────────────────────────────────────
const HUD_H       := 38
const RUNE_ROW_H  := 82
const BASE_ROW_H  := 128
const CHAIN_W     := 176

# Zone widths
const W_RUNE_DECK := 72
const W_CHAMPION  := 92
const W_LEGEND    := 92
const W_MAIN_DECK := 80
const W_TRASH     := 72

# Card thumbnail dimensions inside the Base zone
const CARD_W := 88
const CARD_H := 110

# Rune slot dimensions
const RUNE_W := 54
const RUNE_H := 68

# ── Colors ────────────────────────────────────────────────────────────────────
const C_BG         := Color(0.055, 0.055, 0.075)
const C_P1         := Color(0.85,  0.25,  0.20)
const C_P2         := Color(0.15,  0.42,  0.90)
const C_ZONE       := Color(0.09,  0.09,  0.12)
const C_ZONE_BDR   := Color(0.22,  0.22,  0.30)
const C_HUD_BG     := Color(0.04,  0.04,  0.06)
const C_BF_BASE    := Color(0.10,  0.12,  0.10)
const C_CONTESTED  := Color(0.90,  0.50,  0.10)
const C_CHAIN_BG   := Color(0.08,  0.06,  0.14)
const C_CHAIN_BDR  := Color(0.44,  0.26,  0.72)
const C_LABEL_DIM  := Color(0.50,  0.50,  0.55)
const C_LABEL_BRT  := Color(0.88,  0.90,  0.88)

# ── Dynamic node references ───────────────────────────────────────────────────
# HUD
var _hud_turn:  Label
var _hud_phase: Label
var _hud_score: Label
var _hud_pool:  Label

# Per-player base-zone card containers  [pi]
var _base_scroll:     Array = [null, null]   # ScrollContainer
var _base_cards:      Array = [null, null]   # HBoxContainer inside scroll

# Per-player hand containers  [pi]
var _hand_scroll:     Array = [null, null]   # ScrollContainer
var _hand_cards:      Array = [null, null]   # HBoxContainer inside scroll

# Per-player rune containers  [pi]
var _rune_slots:      Array = [null, null]   # HBoxContainer

# Per-player fixed-slot card areas  [pi]
var _champion_card_area: Array = [null, null]   # CenterContainer
var _legend_card_area:   Array = [null, null]
var _deck_label:      Array = [null, null]   # Label (deck count)
var _rune_deck_label: Array = [null, null]
var _trash_label:     Array = [null, null]

# Battlefield panels
var _bf_panels: Array = []   # Array[PanelContainer]  length 2
var _bf_unit_cards: Array = []  # [bf_index][pi] → HBoxContainer

# Chain panel
var _chain_items_vbox: VBoxContainer


func _ready() -> void:
	_build_ui()


# ── UI Construction ───────────────────────────────────────────────────────────

func _build_ui() -> void:
	# Outer HBox: main board (left+center) | chain column (right)
	var root_hbox := HBoxContainer.new()
	root_hbox.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	root_hbox.add_theme_constant_override("separation", 0)
	add_child(root_hbox)

	# ── Left / center: all rows stacked vertically ──
	var board_vbox := VBoxContainer.new()
	board_vbox.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	board_vbox.add_theme_constant_override("separation", 2)
	root_hbox.add_child(board_vbox)

	# HUD
	board_vbox.add_child(_build_hud())

	# P2 rune row  (their mat's bottom row, now at screen top)
	board_vbox.add_child(_build_rune_row(1))

	# P2 base row  (their mat's middle row)
	board_vbox.add_child(_build_base_row(1))

	# Battlefields  (shared center, expands to fill remaining height)
	board_vbox.add_child(_build_battlefield_row())

	# P1 base row
	board_vbox.add_child(_build_base_row(0))

	# P1 rune row
	board_vbox.add_child(_build_rune_row(0))

	# ── Right: chain column ──
	root_hbox.add_child(_build_chain_column())


# ── HUD bar ───────────────────────────────────────────────────────────────────

func _build_hud() -> PanelContainer:
	var pc := PanelContainer.new()
	pc.custom_minimum_size = Vector2(0, HUD_H)
	pc.add_theme_stylebox_override("panel", _flat_sb(C_HUD_BG, Color(0.18, 0.18, 0.24)))

	var hbox := HBoxContainer.new()
	hbox.add_theme_constant_override("separation", 0)
	pc.add_child(hbox)

	_hud_turn  = _hud_lbl("Turn 1 | P1's Turn",      Color(0.90, 0.85, 0.30))
	_hud_phase = _hud_lbl("Awaken Phase",              Color(0.60, 0.80, 0.60))
	_hud_score = _hud_lbl("P1: 0   P2: 0   ⚑ 8",     Color(0.90, 0.90, 0.90))
	_hud_pool  = _hud_lbl("Pool: —",                   Color(0.55, 0.80, 0.55))

	hbox.add_child(_hud_turn)
	hbox.add_child(_vsep())
	hbox.add_child(_hud_phase)
	hbox.add_child(_vsep())
	hbox.add_child(_hud_score)
	hbox.add_child(_vsep())
	hbox.add_child(_hud_pool)
	return pc


func _hud_lbl(txt: String, col: Color) -> Label:
	var l := Label.new()
	l.text = "  " + txt + "  "
	l.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	l.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	l.add_theme_color_override("font_color", col)
	l.add_theme_font_size_override("font_size", 13)
	return l


# ── Base row (champion · legend · base zone · main deck) ─────────────────────

func _build_base_row(pi: int) -> PanelContainer:
	var row_color := C_P1 if pi == 0 else C_P2
	var label_str := "P%d — BASE" % (pi + 1)

	var pc := PanelContainer.new()
	pc.custom_minimum_size = Vector2(0, BASE_ROW_H)
	var bg := row_color * 0.08
	bg.a = 1.0
	pc.add_theme_stylebox_override("panel", _flat_sb(bg, row_color * 0.5, 1))

	var hbox := HBoxContainer.new()
	hbox.add_theme_constant_override("separation", 2)
	pc.add_child(hbox)

	# P1: champion first; P2: main deck first (mirror)
	if pi == 0:
		var champ_slot := _make_named_slot("CHAMPION", W_CHAMPION, row_color)
		_champion_card_area[pi] = champ_slot.card_area
		hbox.add_child(champ_slot.panel)
		var legend_slot := _make_named_slot("LEGEND", W_LEGEND, C_ZONE_BDR)
		_legend_card_area[pi] = legend_slot.card_area
		hbox.add_child(legend_slot.panel)
		hbox.add_child(_build_base_zone(pi, row_color))
		hbox.add_child(_make_deck_slot("MAIN\nDECK", W_MAIN_DECK, row_color, pi, 0))
	else:
		hbox.add_child(_make_deck_slot("MAIN\nDECK", W_MAIN_DECK, row_color, pi, 0))
		hbox.add_child(_build_base_zone(pi, row_color))
		var legend_slot := _make_named_slot("LEGEND", W_LEGEND, C_ZONE_BDR)
		_legend_card_area[pi] = legend_slot.card_area
		hbox.add_child(legend_slot.panel)
		var champ_slot := _make_named_slot("CHAMPION", W_CHAMPION, row_color)
		_champion_card_area[pi] = champ_slot.card_area
		hbox.add_child(champ_slot.panel)

	return pc


func _build_base_zone(pi: int, border_color: Color) -> HBoxContainer:
	var outer := HBoxContainer.new()
	outer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	outer.add_theme_constant_override("separation", 2)

	# ── Left half: HAND (next to champion/legend for P1; opponent card backs for P2) ──
	var hand_pc := PanelContainer.new()
	hand_pc.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	hand_pc.add_theme_stylebox_override("panel",
		_flat_sb(Color(0.07, 0.07, 0.10), border_color * 0.3, 1, 3))

	var hand_vbox := VBoxContainer.new()
	hand_vbox.add_theme_constant_override("separation", 2)
	hand_pc.add_child(hand_vbox)

	var hand_title := Label.new()
	hand_title.text = "  HAND" if pi == 0 else "  HAND  (opponent)"
	hand_title.add_theme_font_size_override("font_size", 9)
	hand_title.add_theme_color_override("font_color", C_LABEL_DIM)
	hand_vbox.add_child(hand_title)

	var hand_scroll := ScrollContainer.new()
	hand_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_AUTO
	hand_scroll.vertical_scroll_mode   = ScrollContainer.SCROLL_MODE_DISABLED
	hand_scroll.size_flags_vertical    = Control.SIZE_EXPAND_FILL
	hand_vbox.add_child(hand_scroll)

	var hand_hbox := HBoxContainer.new()
	hand_hbox.add_theme_constant_override("separation", 4)
	hand_hbox.size_flags_vertical = Control.SIZE_EXPAND_FILL
	hand_scroll.add_child(hand_hbox)

	_hand_scroll[pi] = hand_scroll
	_hand_cards[pi]  = hand_hbox

	# ── Right half: BASE PERMANENTS ──
	var base_pc := PanelContainer.new()
	base_pc.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	base_pc.add_theme_stylebox_override("panel",
		_flat_sb(Color(0.08, 0.09, 0.08), border_color * 0.4, 1, 3))

	var base_vbox := VBoxContainer.new()
	base_vbox.add_theme_constant_override("separation", 2)
	base_pc.add_child(base_vbox)

	var base_title := Label.new()
	base_title.text = "  BASE"
	base_title.add_theme_font_size_override("font_size", 9)
	base_title.add_theme_color_override("font_color", C_LABEL_DIM)
	base_vbox.add_child(base_title)

	var base_scroll := ScrollContainer.new()
	base_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_AUTO
	base_scroll.vertical_scroll_mode   = ScrollContainer.SCROLL_MODE_DISABLED
	base_scroll.size_flags_vertical    = Control.SIZE_EXPAND_FILL
	base_vbox.add_child(base_scroll)

	var base_hbox := HBoxContainer.new()
	base_hbox.add_theme_constant_override("separation", 4)
	base_hbox.size_flags_vertical = Control.SIZE_EXPAND_FILL
	base_scroll.add_child(base_hbox)

	_base_scroll[pi] = base_scroll
	_base_cards[pi]  = base_hbox

	# For P1: hand on left, permanents on right (hand is next to legend).
	# For P2: permanents on left, hand/backs on right (backs are next to legend).
	if pi == 0:
		outer.add_child(hand_pc)
		outer.add_child(_vsep())
		outer.add_child(base_pc)
	else:
		outer.add_child(base_pc)
		outer.add_child(_vsep())
		outer.add_child(hand_pc)

	return outer


func _make_named_slot(label_text: String, width: int, border_color: Color) -> Dictionary:
	var pc := PanelContainer.new()
	pc.custom_minimum_size = Vector2(width, 0)
	pc.size_flags_vertical = Control.SIZE_EXPAND_FILL
	pc.add_theme_stylebox_override("panel", _flat_sb(C_ZONE, border_color * 0.5, 1, 3))

	var vbox := VBoxContainer.new()
	vbox.name = "VBox"
	vbox.add_theme_constant_override("separation", 2)
	pc.add_child(vbox)

	var lbl := Label.new()
	lbl.text = label_text
	lbl.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	lbl.add_theme_font_size_override("font_size", 9)
	lbl.add_theme_color_override("font_color", C_LABEL_DIM)
	vbox.add_child(lbl)

	var card_area := CenterContainer.new()
	card_area.name = "CardArea"
	card_area.custom_minimum_size = Vector2(CARD_W, CARD_H)
	card_area.size_flags_vertical = Control.SIZE_EXPAND_FILL
	vbox.add_child(card_area)

	return { "panel": pc, "card_area": card_area }


## slot_kind:  0 = main deck,  1 = rune deck,  2 = trash
func _make_deck_slot(label_text: String, width: int, border_color: Color,
					  pi: int, slot_kind: int) -> PanelContainer:
	var pc := PanelContainer.new()
	pc.custom_minimum_size = Vector2(width, 0)
	pc.size_flags_vertical  = Control.SIZE_EXPAND_FILL
	pc.add_theme_stylebox_override("panel", _flat_sb(C_ZONE, border_color * 0.5, 1, 3))

	var vbox := VBoxContainer.new()
	vbox.name = "VBox"
	pc.add_child(vbox)

	var lbl := Label.new()
	lbl.text = label_text
	lbl.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	lbl.add_theme_font_size_override("font_size", 9)
	lbl.add_theme_color_override("font_color", C_LABEL_DIM)
	vbox.add_child(lbl)

	var count_lbl := Label.new()
	count_lbl.name = "Count"
	count_lbl.text = "0"
	count_lbl.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	count_lbl.add_theme_font_size_override("font_size", 18)
	count_lbl.add_theme_color_override("font_color", border_color)
	count_lbl.size_flags_vertical = Control.SIZE_EXPAND_FILL
	count_lbl.vertical_alignment  = VERTICAL_ALIGNMENT_CENTER
	vbox.add_child(count_lbl)

	match slot_kind:
		0: _deck_label[pi]      = count_lbl
		1: _rune_deck_label[pi] = count_lbl
		2: _trash_label[pi]     = count_lbl
	return pc


# ── Rune row (rune deck · rune slots · trash) ─────────────────────────────────

func _build_rune_row(pi: int) -> PanelContainer:
	var row_color := C_P1 if pi == 0 else C_P2

	var pc := PanelContainer.new()
	pc.custom_minimum_size = Vector2(0, RUNE_ROW_H)
	var bg := row_color * 0.06; bg.a = 1.0
	pc.add_theme_stylebox_override("panel", _flat_sb(bg, row_color * 0.3, 1))

	var hbox := HBoxContainer.new()
	hbox.add_theme_constant_override("separation", 2)
	pc.add_child(hbox)

	# Rune Deck
	hbox.add_child(_make_deck_slot("RUNE\nDECK", W_RUNE_DECK, row_color, pi, 1))

	# Rune slots (scrollable HBox)
	var rune_pc := PanelContainer.new()
	rune_pc.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	rune_pc.add_theme_stylebox_override("panel", _flat_sb(C_ZONE, row_color * 0.25, 1, 3))

	var r_vbox := VBoxContainer.new()
	r_vbox.add_theme_constant_override("separation", 1)
	rune_pc.add_child(r_vbox)

	var r_title := Label.new()
	r_title.text = "  RUNES  (tap rune-N or recycle rune-N)"
	r_title.add_theme_font_size_override("font_size", 9)
	r_title.add_theme_color_override("font_color", C_LABEL_DIM)
	r_vbox.add_child(r_title)

	var rune_scroll := ScrollContainer.new()
	rune_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_AUTO
	rune_scroll.vertical_scroll_mode   = ScrollContainer.SCROLL_MODE_DISABLED
	rune_scroll.size_flags_vertical    = Control.SIZE_EXPAND_FILL
	r_vbox.add_child(rune_scroll)

	var rune_hbox := HBoxContainer.new()
	rune_hbox.add_theme_constant_override("separation", 3)
	rune_scroll.add_child(rune_hbox)
	_rune_slots[pi] = rune_hbox

	hbox.add_child(rune_pc)

	# Trash
	hbox.add_child(_make_deck_slot("TRASH", W_TRASH, C_LABEL_DIM, pi, 2))

	return pc


# ── Battlefield row ───────────────────────────────────────────────────────────

func _build_battlefield_row() -> PanelContainer:
	var pc := PanelContainer.new()
	pc.size_flags_vertical = Control.SIZE_EXPAND_FILL
	pc.add_theme_stylebox_override("panel", _flat_sb(Color(0.07, 0.08, 0.07), C_ZONE_BDR, 1))

	var hbox := HBoxContainer.new()
	hbox.add_theme_constant_override("separation", 3)
	pc.add_child(hbox)

	_bf_panels.clear()
	_bf_unit_cards.clear()
	for i in range(2):
		var bf := _build_single_battlefield(i)
		hbox.add_child(bf)
		_bf_panels.append(bf)

	return pc


func _build_single_battlefield(bf_index: int) -> PanelContainer:
	var pc := PanelContainer.new()
	pc.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	pc.size_flags_vertical   = Control.SIZE_EXPAND_FILL
	pc.add_theme_stylebox_override("panel", _flat_sb(C_BF_BASE, C_ZONE_BDR, 2, 5))

	var vbox := VBoxContainer.new()
	vbox.add_theme_constant_override("separation", 4)
	pc.add_child(vbox)

	_bf_unit_cards.append([null, null])

	var name_row := HBoxContainer.new()
	vbox.add_child(name_row)

	var name_lbl := Label.new()
	name_lbl.name = "NameLabel"
	name_lbl.text = "BATTLEFIELD"
	name_lbl.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	name_lbl.horizontal_alignment  = HORIZONTAL_ALIGNMENT_CENTER
	name_lbl.add_theme_font_size_override("font_size", 13)
	name_lbl.add_theme_color_override("font_color", C_LABEL_BRT)
	name_row.add_child(name_lbl)

	var ctrl_lbl := Label.new()
	ctrl_lbl.name = "CtrlLabel"
	ctrl_lbl.text = "Uncontrolled"
	ctrl_lbl.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	ctrl_lbl.add_theme_font_size_override("font_size", 11)
	ctrl_lbl.add_theme_color_override("font_color", C_LABEL_DIM)
	vbox.add_child(ctrl_lbl)

	vbox.add_child(_build_bf_player_zone(bf_index, 1))

	var divider := HSeparator.new()
	divider.add_theme_color_override("color", C_ZONE_BDR)
	vbox.add_child(divider)

	vbox.add_child(_build_bf_player_zone(bf_index, 0))

	return pc


func _build_bf_player_zone(bf_index: int, pi: int) -> PanelContainer:
	var row_color := C_P1 if pi == 0 else C_P2

	var zone_pc := PanelContainer.new()
	zone_pc.size_flags_vertical   = Control.SIZE_EXPAND_FILL
	zone_pc.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	zone_pc.add_theme_stylebox_override("panel",
		_flat_sb(row_color * 0.06, row_color * 0.35, 1, 3))

	var zone_vbox := VBoxContainer.new()
	zone_vbox.add_theme_constant_override("separation", 2)
	zone_pc.add_child(zone_vbox)

	var title := Label.new()
	title.text = "  P%d" % (pi + 1)
	title.add_theme_font_size_override("font_size", 9)
	title.add_theme_color_override("font_color", row_color * 0.8)
	zone_vbox.add_child(title)

	var scroll := ScrollContainer.new()
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_AUTO
	scroll.vertical_scroll_mode   = ScrollContainer.SCROLL_MODE_DISABLED
	scroll.size_flags_vertical    = Control.SIZE_EXPAND_FILL
	zone_vbox.add_child(scroll)

	var hbox := HBoxContainer.new()
	hbox.add_theme_constant_override("separation", 4)
	hbox.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.add_child(hbox)

	_bf_unit_cards[bf_index][pi] = hbox
	return zone_pc


# ── Chain column ──────────────────────────────────────────────────────────────

func _build_chain_column() -> PanelContainer:
	var pc := PanelContainer.new()
	pc.custom_minimum_size = Vector2(CHAIN_W, 0)
	pc.add_theme_stylebox_override("panel", _flat_sb(C_CHAIN_BG, C_CHAIN_BDR, 2))

	var vbox := VBoxContainer.new()
	vbox.add_theme_constant_override("separation", 4)
	pc.add_child(vbox)

	var title := Label.new()
	title.text = "— CHAIN —"
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	title.add_theme_color_override("font_color", Color(0.70, 0.50, 0.90))
	title.add_theme_font_size_override("font_size", 12)
	vbox.add_child(title)

	vbox.add_child(HSeparator.new())

	_chain_items_vbox = VBoxContainer.new()
	_chain_items_vbox.add_theme_constant_override("separation", 6)
	_chain_items_vbox.size_flags_vertical = Control.SIZE_EXPAND_FILL
	vbox.add_child(_chain_items_vbox)

	var empty_lbl := Label.new()
	empty_lbl.name = "EmptyLabel"
	empty_lbl.text = "(empty)"
	empty_lbl.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	empty_lbl.add_theme_color_override("font_color", C_LABEL_DIM)
	empty_lbl.add_theme_font_size_override("font_size", 11)
	_chain_items_vbox.add_child(empty_lbl)

	return pc


# ── Refresh (called after every state change) ─────────────────────────────────

func refresh(gs: GameState) -> void:
	if gs == null:
		return

	_refresh_hud(gs)

	for pi in range(2):
		_refresh_base_zone(gs, pi)
		_refresh_hand_zone(gs, pi)
		_refresh_rune_zone(gs, pi)
		_refresh_deck_counts(gs, pi)

	for i in range(gs.board.battlefields.size()):
		if i < _bf_panels.size():
			_refresh_battlefield(gs, i)

	_refresh_chain(gs)


func _refresh_hud(gs: GameState) -> void:
	var tp: int = gs.turn_player_index
	_hud_turn.text = "  Turn %d  |  P%d's Turn  " % [gs.turn_number, tp + 1]
	_hud_turn.add_theme_color_override("font_color", C_P1 if tp == 0 else C_P2)
	_hud_phase.text = "  %s  |  %s  " % [gs.get_phase_name(), gs.get_state_name()]
	_hud_score.text = "  P1: %d   P2: %d   ⚑ %d  " % [
		gs.players[0].score, gs.players[1].score, gs.victory_score
	]
	var pool: RunePool = gs.players[tp].rune_pool
	_hud_pool.text = "  P%d Pool: %s  " % [tp + 1, pool.describe()]


func _refresh_fixed_card_slot(card_area: CenterContainer, inst: CardInstance) -> void:
	if card_area == null:
		return
	_clear_children(card_area)
	if inst:
		card_area.add_child(_make_card_thumb(inst))
	else:
		var empty_lbl := Label.new()
		empty_lbl.text = "—"
		empty_lbl.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		empty_lbl.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
		empty_lbl.size_flags_vertical = Control.SIZE_EXPAND_FILL
		empty_lbl.add_theme_color_override("font_color", C_LABEL_DIM)
		empty_lbl.add_theme_font_size_override("font_size", 10)
		card_area.add_child(empty_lbl)


func _refresh_base_zone(gs: GameState, pi: int) -> void:
	var ps: PlayerState = gs.players[pi]
	var cards_hbox: HBoxContainer = _base_cards[pi]
	if cards_hbox == null:
		return
	_clear_children(cards_hbox)

	_refresh_fixed_card_slot(_champion_card_area[pi], ps.champion_zone)
	_refresh_fixed_card_slot(_legend_card_area[pi], ps.legend)

	# Units at base
	for unit in ps.get_units_at_base():
		cards_hbox.add_child(_make_card_thumb(unit))

	# Unattached gear at base
	for gear in ps.get_unattached_gear_at_base():
		cards_hbox.add_child(_make_card_thumb(gear))

	if ps.get_units_at_base().is_empty() and ps.get_unattached_gear_at_base().is_empty():
		var empty_lbl := Label.new()
		empty_lbl.text = "(no permanents at base)"
		empty_lbl.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
		empty_lbl.size_flags_vertical = Control.SIZE_EXPAND_FILL
		empty_lbl.add_theme_color_override("font_color", C_LABEL_DIM)
		empty_lbl.add_theme_font_size_override("font_size", 10)
		cards_hbox.add_child(empty_lbl)


func _refresh_hand_zone(gs: GameState, pi: int) -> void:
	var ps: PlayerState = gs.players[pi]
	var hand_hbox: HBoxContainer = _hand_cards[pi]
	if hand_hbox == null:
		return
	_clear_children(hand_hbox)

	if ps.hand.is_empty():
		var lbl := Label.new()
		lbl.text = "(empty hand)"
		lbl.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
		lbl.size_flags_vertical = Control.SIZE_EXPAND_FILL
		lbl.add_theme_color_override("font_color", C_LABEL_DIM)
		lbl.add_theme_font_size_override("font_size", 10)
		hand_hbox.add_child(lbl)
		return

	# P1 (human) — show card faces; P2 (AI opponent) — show card backs
	for card in ps.hand:
		if pi == 0:
			hand_hbox.add_child(_make_card_thumb(card))
		else:
			hand_hbox.add_child(_make_card_back(pi))


func _make_card_back(owner_pi: int) -> Control:
	var wrapper := Control.new()
	wrapper.custom_minimum_size = Vector2(CARD_W, CARD_H)
	wrapper.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	wrapper.clip_contents = false

	var card := Control.new()
	card.set_size(Vector2(CARD_W, CARD_H))
	wrapper.add_child(card)

	# Darkened card art as back face (always uses fallback — art is hidden)
	var tex := TextureRect.new()
	tex.texture = _load_card_texture("")
	tex.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	tex.stretch_mode = TextureRect.STRETCH_SCALE
	tex.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	card.add_child(tex)

	# Heavy dark overlay to obscure art
	var dim := ColorRect.new()
	dim.color = Color(0.0, 0.0, 0.0, 0.72)
	dim.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	card.add_child(dim)

	# Owner-colored border
	var owner_color := C_P1 if owner_pi == 0 else C_P2
	var border_panel := Panel.new()
	border_panel.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	border_panel.add_theme_stylebox_override("panel",
		_flat_sb(Color(0, 0, 0, 0), owner_color * 0.5, 2, 4))
	card.add_child(border_panel)

	# "?" centered
	var lbl := Label.new()
	lbl.text = "?"
	lbl.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	lbl.vertical_alignment   = VERTICAL_ALIGNMENT_CENTER
	lbl.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	lbl.add_theme_font_size_override("font_size", 28)
	lbl.add_theme_color_override("font_color", owner_color * 0.60)
	card.add_child(lbl)

	return wrapper


func _refresh_rune_zone(gs: GameState, pi: int) -> void:
	var ps: PlayerState = gs.players[pi]
	var rune_hbox: HBoxContainer = _rune_slots[pi]
	if rune_hbox == null:
		return
	_clear_children(rune_hbox)

	if ps.channeled_runes.is_empty():
		var lbl := Label.new()
		lbl.text = "no runes channeled"
		lbl.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
		lbl.size_flags_vertical = Control.SIZE_EXPAND_FILL
		lbl.add_theme_color_override("font_color", C_LABEL_DIM)
		lbl.add_theme_font_size_override("font_size", 10)
		rune_hbox.add_child(lbl)
		return

	for i in range(ps.channeled_runes.size()):
		rune_hbox.add_child(_make_rune_slot(i, ps.channeled_runes[i], pi))


func _refresh_deck_counts(gs: GameState, pi: int) -> void:
	var ps: PlayerState = gs.players[pi]

	if _deck_label[pi]:
		_deck_label[pi].text = str(ps.deck.size())
	if _rune_deck_label[pi]:
		_rune_deck_label[pi].text = str(ps.rune_deck.size())
	if _trash_label[pi]:
		_trash_label[pi].text = str(ps.trash.size())


func _refresh_battlefield(gs: GameState, bf_index: int) -> void:
	var bf: BoardState.BattlefieldEntry = gs.board.battlefields[bf_index]
	var panel: PanelContainer = _bf_panels[bf_index]
	var vbox: VBoxContainer = panel.get_child(0)
	if vbox == null:
		return

	var name_lbl: Label = vbox.get_node_or_null("HBoxContainer/NameLabel")
	var ctrl_lbl: Label = vbox.get_node_or_null("CtrlLabel")

	if name_lbl:
		name_lbl.text = "[%s]  %s" % [bf.battlefield_id.to_upper(), bf.display_name]

	# Control status & panel color
	var bg: Color; var border: Color
	if bf.is_contested:
		if ctrl_lbl: ctrl_lbl.text = "⚔  CONTESTED"
		if ctrl_lbl: ctrl_lbl.add_theme_color_override("font_color", C_CONTESTED)
		bg = Color(0.16, 0.10, 0.04); border = C_CONTESTED
	elif bf.controller_index == 0:
		if ctrl_lbl: ctrl_lbl.text = "P1 Controls"
		if ctrl_lbl: ctrl_lbl.add_theme_color_override("font_color", C_P1)
		bg = Color(0.13, 0.05, 0.05); border = C_P1
	elif bf.controller_index == 1:
		if ctrl_lbl: ctrl_lbl.text = "P2 Controls"
		if ctrl_lbl: ctrl_lbl.add_theme_color_override("font_color", C_P2)
		bg = Color(0.04, 0.05, 0.13); border = C_P2
	else:
		if ctrl_lbl: ctrl_lbl.text = "Uncontrolled"
		if ctrl_lbl: ctrl_lbl.add_theme_color_override("font_color", C_LABEL_DIM)
		bg = C_BF_BASE; border = C_ZONE_BDR
	panel.add_theme_stylebox_override("panel", _flat_sb(bg, border, 2, 5))

	for pi in [1, 0]:
		_refresh_bf_unit_row(bf_index, pi, bf.units[pi], bf)


func _refresh_bf_unit_row(bf_index: int, pi: int, units: Array,
		bf: BoardState.BattlefieldEntry) -> void:
	if bf_index >= _bf_unit_cards.size():
		return
	var hbox: HBoxContainer = _bf_unit_cards[bf_index][pi]
	if hbox == null:
		return
	_clear_children(hbox)

	var has_facedown := bf.facedown_card != null and bf.facedown_card.owner_index == pi
	if units.is_empty() and not has_facedown:
		var empty_lbl := Label.new()
		empty_lbl.text = "(no units)"
		empty_lbl.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
		empty_lbl.size_flags_vertical = Control.SIZE_EXPAND_FILL
		empty_lbl.add_theme_color_override("font_color", C_LABEL_DIM)
		empty_lbl.add_theme_font_size_override("font_size", 10)
		hbox.add_child(empty_lbl)
		return

	for u in units:
		hbox.add_child(_make_card_thumb(u))
	if has_facedown:
		hbox.add_child(_make_facedown_thumb(bf.facedown_card))


func _refresh_chain(gs: GameState) -> void:
	_clear_children(_chain_items_vbox)

	if gs.chain.is_empty():
		var lbl := Label.new()
		lbl.name = "EmptyLabel"
		lbl.text = "(empty)"
		lbl.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		lbl.add_theme_color_override("font_color", C_LABEL_DIM)
		lbl.add_theme_font_size_override("font_size", 11)
		_chain_items_vbox.add_child(lbl)
		return

	# Top of chain = last in array
	for i in range(gs.chain.size() - 1, -1, -1):
		var item: ChainItem = gs.chain[i]
		var item_pc := PanelContainer.new()
		var item_col := C_P1 if item.owner_index == 0 else C_P2
		item_pc.add_theme_stylebox_override("panel",
			_flat_sb(item_col * 0.12, item_col * 0.5, 1, 4))

		var vbox := VBoxContainer.new()
		vbox.add_theme_constant_override("separation", 2)
		item_pc.add_child(vbox)

		var pos_lbl := Label.new()
		pos_lbl.text = "[%d] %s" % [i, item.describe()]
		pos_lbl.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		pos_lbl.add_theme_font_size_override("font_size", 10)
		pos_lbl.add_theme_color_override("font_color", item_col)
		vbox.add_child(pos_lbl)

		_chain_items_vbox.add_child(item_pc)


# ── Card thumbnail builder ────────────────────────────────────────────────────
# Wrapper/inner-child pattern: wrapper reserves layout space; inner card rotates.
# Text labels are intentionally omitted — art carries all visual info.
# Hover emits card_hovered so the preview panel can display full card details.

func _make_card_thumb(inst: CardInstance) -> Control:
	var wrapper := Control.new()
	wrapper.custom_minimum_size = Vector2(CARD_W, CARD_H)
	wrapper.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	wrapper.clip_contents = false
	wrapper.mouse_filter = Control.MOUSE_FILTER_STOP

	# Emit hover signals so GameScene can update the preview panel
	wrapper.mouse_entered.connect(func(): card_hovered.emit(inst))
	wrapper.mouse_exited.connect(func(): card_unhovered.emit())
	wrapper.gui_input.connect(func(event: InputEvent) -> void:
		if event is InputEventMouseButton \
				and event.pressed \
				and event.button_index == MOUSE_BUTTON_LEFT:
			card_clicked.emit(inst)
	)

	# Inner card — holds all visuals, rotates when exhausted
	var card := Control.new()
	card.set_size(Vector2(CARD_W, CARD_H))
	card.clip_contents = false
	card.mouse_filter = Control.MOUSE_FILTER_IGNORE
	wrapper.add_child(card)

	# Full-bleed card art
	var tex := TextureRect.new()
	tex.texture = _load_card_texture(inst.definition.image)
	tex.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	tex.stretch_mode = TextureRect.STRETCH_SCALE
	tex.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	tex.mouse_filter = Control.MOUSE_FILTER_IGNORE
	card.add_child(tex)

	# Owner-colored border (transparent fill)
	var owner_color := C_P1 if inst.owner_index == 0 else C_P2
	var border_panel := Panel.new()
	border_panel.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	border_panel.add_theme_stylebox_override("panel",
		_flat_sb(Color(0, 0, 0, 0), owner_color, 2, 4))
	border_panel.mouse_filter = Control.MOUSE_FILTER_IGNORE
	card.add_child(border_panel)

	# Tiny instance-ID strip at the very bottom (needed for commands)
	var id_bg := ColorRect.new()
	id_bg.color = Color(0.0, 0.0, 0.0, 0.70)
	id_bg.anchor_left = 0.0; id_bg.anchor_right  = 1.0
	id_bg.anchor_top  = 0.88; id_bg.anchor_bottom = 1.0
	id_bg.mouse_filter = Control.MOUSE_FILTER_IGNORE
	card.add_child(id_bg)

	var id_lbl := Label.new()
	id_lbl.text = inst.instance_id
	id_lbl.clip_text = true
	id_lbl.anchor_left  = 0.0;  id_lbl.anchor_right  = 1.0
	id_lbl.anchor_top   = 0.89; id_lbl.anchor_bottom = 1.0
	id_lbl.offset_left = 2; id_lbl.offset_right = -2
	id_lbl.add_theme_font_size_override("font_size", 7)
	id_lbl.add_theme_color_override("font_color", Color(0.70, 0.70, 0.75))
	id_lbl.mouse_filter = Control.MOUSE_FILTER_IGNORE
	card.add_child(id_lbl)

	# Small status badges in top-left corner (damage / stun / buff / combat)
	var badges: Array[String] = []
	if inst.is_attacker:       badges.append("⚔")
	if inst.is_defender:       badges.append("🛡")
	if inst.damage > 0:        badges.append("❤%d" % inst.damage)
	if inst.is_stunned:        badges.append("~")
	if inst.buff_counters > 0: badges.append("★")
	if not badges.is_empty():
		var badge_bg := ColorRect.new()
		badge_bg.color = Color(0.0, 0.0, 0.0, 0.72)
		badge_bg.anchor_left = 0.0; badge_bg.anchor_right  = 0.55
		badge_bg.anchor_top  = 0.0; badge_bg.anchor_bottom = 0.18
		badge_bg.mouse_filter = Control.MOUSE_FILTER_IGNORE
		card.add_child(badge_bg)
		var badge_lbl := Label.new()
		badge_lbl.text = " ".join(badges)
		badge_lbl.anchor_left  = 0.0;  badge_lbl.anchor_right  = 0.55
		badge_lbl.anchor_top   = 0.01; badge_lbl.anchor_bottom = 0.17
		badge_lbl.offset_left = 2
		badge_lbl.add_theme_font_size_override("font_size", 8)
		badge_lbl.add_theme_color_override("font_color", Color(0.95, 0.35, 0.35))
		badge_lbl.mouse_filter = Control.MOUSE_FILTER_IGNORE
		card.add_child(badge_lbl)

	# Exhausted: dim overlay + rotate 90° (TCG "tapped" look)
	if inst.is_exhausted:
		var dim := ColorRect.new()
		dim.color = Color(0.0, 0.0, 0.0, 0.45)
		dim.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
		dim.mouse_filter = Control.MOUSE_FILTER_IGNORE
		card.add_child(dim)
		card.pivot_offset = Vector2(CARD_W / 2.0, CARD_H / 2.0)
		card.rotation_degrees = 90.0

	return wrapper


func _make_facedown_thumb(inst: CardInstance) -> Control:
	var wrapper := Control.new()
	wrapper.custom_minimum_size = Vector2(CARD_W, CARD_H)
	wrapper.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	wrapper.clip_contents = false
	wrapper.mouse_filter = Control.MOUSE_FILTER_STOP

	wrapper.mouse_entered.connect(func(): card_hovered.emit(inst))
	wrapper.mouse_exited.connect(func(): card_unhovered.emit())
	wrapper.gui_input.connect(func(event: InputEvent) -> void:
		if event is InputEventMouseButton \
				and event.pressed \
				and event.button_index == MOUSE_BUTTON_LEFT:
			card_clicked.emit(inst)
	)

	var card := Control.new()
	card.set_size(Vector2(CARD_W, CARD_H))
	card.mouse_filter = Control.MOUSE_FILTER_IGNORE
	wrapper.add_child(card)

	var tex := TextureRect.new()
	tex.texture = _load_card_texture("")
	tex.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	tex.stretch_mode = TextureRect.STRETCH_SCALE
	tex.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	tex.mouse_filter = Control.MOUSE_FILTER_IGNORE
	card.add_child(tex)

	var dim := ColorRect.new()
	dim.color = Color(0.0, 0.0, 0.0, 0.72)
	dim.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	dim.mouse_filter = Control.MOUSE_FILTER_IGNORE
	card.add_child(dim)

	var owner_color := C_P1 if inst.owner_index == 0 else C_P2
	var border_panel := Panel.new()
	border_panel.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	border_panel.add_theme_stylebox_override("panel",
		_flat_sb(Color(0, 0, 0, 0), owner_color * 0.5, 2, 4))
	border_panel.mouse_filter = Control.MOUSE_FILTER_IGNORE
	card.add_child(border_panel)

	var hidden_lbl := Label.new()
	hidden_lbl.text = "HIDDEN"
	hidden_lbl.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	hidden_lbl.vertical_alignment   = VERTICAL_ALIGNMENT_CENTER
	hidden_lbl.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	hidden_lbl.add_theme_font_size_override("font_size", 11)
	hidden_lbl.add_theme_color_override("font_color", owner_color * 0.60)
	hidden_lbl.mouse_filter = Control.MOUSE_FILTER_IGNORE
	card.add_child(hidden_lbl)

	var id_bg := ColorRect.new()
	id_bg.color = Color(0.0, 0.0, 0.0, 0.70)
	id_bg.anchor_left = 0.0; id_bg.anchor_right  = 1.0
	id_bg.anchor_top  = 0.88; id_bg.anchor_bottom = 1.0
	id_bg.mouse_filter = Control.MOUSE_FILTER_IGNORE
	card.add_child(id_bg)

	var id_lbl := Label.new()
	id_lbl.text = inst.instance_id
	id_lbl.clip_text = true
	id_lbl.anchor_left  = 0.0;  id_lbl.anchor_right  = 1.0
	id_lbl.anchor_top   = 0.89; id_lbl.anchor_bottom = 1.0
	id_lbl.offset_left = 2; id_lbl.offset_right = -2
	id_lbl.add_theme_font_size_override("font_size", 7)
	id_lbl.add_theme_color_override("font_color", Color(0.70, 0.70, 0.75))
	id_lbl.mouse_filter = Control.MOUSE_FILTER_IGNORE
	card.add_child(id_lbl)

	return wrapper


func _make_rune_slot(idx: int, rune: CardInstance, pi: int) -> Control:
	# Same wrapper/inner pattern so exhausted runes can rotate freely
	var wrapper := Control.new()
	wrapper.custom_minimum_size = Vector2(RUNE_W, RUNE_H)
	wrapper.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	wrapper.clip_contents = false

	var slot := PanelContainer.new()
	slot.set_size(Vector2(RUNE_W, RUNE_H))
	wrapper.add_child(slot)

	var domain: String = rune.definition.domain[0] if rune.definition.domain.size() > 0 else ""
	var d_color := CardDefinition.domain_color(domain)
	var bg  := d_color * (0.18 if not rune.is_exhausted else 0.07)
	bg.a = 1.0
	var bdr := d_color * (0.8 if not rune.is_exhausted else 0.3)
	slot.add_theme_stylebox_override("panel", _flat_sb(bg, bdr, 1, 4))

	var vbox := VBoxContainer.new()
	vbox.add_theme_constant_override("separation", 2)
	slot.add_child(vbox)

	var idx_lbl := Label.new()
	idx_lbl.text = str(idx)
	idx_lbl.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	idx_lbl.add_theme_font_size_override("font_size", 9)
	idx_lbl.add_theme_color_override("font_color", Color(0.55, 0.55, 0.55))
	vbox.add_child(idx_lbl)

	var d_lbl := Label.new()
	d_lbl.text = CardDefinition._domain_abbr(domain)
	d_lbl.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	d_lbl.add_theme_font_size_override("font_size", 13)
	d_lbl.add_theme_color_override("font_color",
		d_color if not rune.is_exhausted else Color(0.35, 0.35, 0.35))
	vbox.add_child(d_lbl)

	# Rotate inner slot 90° when exhausted; wrapper keeps its layout slot
	if rune.is_exhausted:
		slot.pivot_offset = Vector2(RUNE_W / 2.0, RUNE_H / 2.0)
		slot.rotation_degrees = 90.0

	return wrapper


# ── Helpers ───────────────────────────────────────────────────────────────────

func _flat_sb(bg: Color, border: Color, border_w: int = 1,
			   corner: int = 3) -> StyleBoxFlat:
	var sb := StyleBoxFlat.new()
	sb.bg_color = bg
	sb.border_color = border
	sb.set_border_width_all(border_w)
	sb.set_corner_radius_all(corner)
	sb.content_margin_left   = 4
	sb.content_margin_right  = 4
	sb.content_margin_top    = 3
	sb.content_margin_bottom = 3
	return sb


func _load_card_texture(image_path: String) -> Texture2D:
	const FALLBACK := "res://Assets/Champ_Card.jpg"
	if image_path.is_empty():
		return load(FALLBACK)
	var full := "res://Assets/" + image_path
	if ResourceLoader.exists(full):
		var tex = load(full)
		if tex is Texture2D:
			return tex
	return load(FALLBACK)


func _vsep() -> VSeparator:
	var sep := VSeparator.new()
	sep.add_theme_color_override("color", Color(0.22, 0.22, 0.30))
	return sep


func _card_type_color(card_type: String) -> Color:
	match card_type:
		"unit":        return Color(0.12, 0.22, 0.12)
		"spell":       return Color(0.08, 0.08, 0.22)
		"gear":        return Color(0.22, 0.16, 0.06)
		"rune":        return Color(0.18, 0.12, 0.22)
		"battlefield": return Color(0.14, 0.18, 0.14)
		"legend":      return Color(0.22, 0.18, 0.06)
	return Color(0.10, 0.10, 0.12)


func _short_name(full_name: String) -> String:
	if full_name.length() <= 14:
		return full_name
	return full_name.left(13) + "…"


func _clear_children(node: Node) -> void:
	for child in node.get_children():
		node.remove_child(child)
		child.free()
