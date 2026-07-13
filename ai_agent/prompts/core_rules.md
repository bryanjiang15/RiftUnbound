## Riftbound — Core Rules (always apply)

### Turn Structure
1. Awaken Phase — ready all your permanents.
2. Beginning Phase — score 1 point per battlefield you control (Hold).
3. Channel Phase — take top 2 Runes from your Rune Deck onto the board.
4. Draw Phase — draw 1 card; both players' Rune Pools empty.
5. Main Phase — your primary action window (Neutral Open state).
6. Ending Phase — heal all units; expire "this turn" effects; Rune Pool empties.

### Resources (essentials — full mechanics via lookup_rule)
- **play_card auto-pays its full cost** — you never manually tap or recycle runes.
- **Legality comes from `legal_moves` only.** Do not guess whether you can afford a
  play or whether a Power cost is payable — the engine auto-pays. Only propose moves
  that appear in `legal_moves` (or call `list_legal_moves` for a fresh list). Printed
  hand costs (e.g. 3E+1FUR) are for strategic planning, not legality, and exclude
  optional costs like Accelerate.
- For `play_card` with Accelerate: set `accelerate: true` **only** if `legal_moves`
  contains `"play <card_id> accelerate"`; otherwise play without it.
- For HOW runes pay cost (Energy by tapping vs Power by recycling, including
  recycling exhausted runes), rune channeling, and floating pool energy, call
  `lookup_rule('paying costs')` — you rarely need it, since legal_moves already
  reflects what you can afford.

### Units
- Permanents — stay on board after play.  Units are played to base by default
  (omit `destination` or use `""`).  You may also deploy a unit straight to a
  Battlefield you control by setting `destination` to that battlefield id — but
  only when `legal_moves` lists `"play <id> to <battlefield>"`.
- Enter exhausted when played (cannot act that turn), unless Accelerate.
- Use `move_unit` on a later action to send a ready base unit to a Battlefield.
- Standard Move: exhaust a unit to move it Base <-> Battlefield.
- A unit dies during Cleanup when damage >= its Might. Damage heals at the end of
  each player's turn and after Combat.

### Battlefields & Scoring (this is the win engine)
- Score 8 points to win (checked every Cleanup: >= 8 points AND more than opponent).
- **Hold:** at the start of each of your turns you score 1 point for EVERY
  battlefield you control.
- **Conquer:** the first time you take a battlefield each turn from neutral.
- To score the 8th point and win the game, you must either a) Hold a battlefield 
  for the 8th point. b) Conquer both battlefield in the same turn
- Moving a unit into a battlefield you don't control triggers a Showdown:
  opponent already there -> Combat Showdown (combat starts); empty uncontrolled ->
  Non-Combat Showdown.

### Combat (summary — see detailed module when in a showdown)
- Combat is SYMMETRIC. When opposing units share a battlefield, BOTH sides deal
  damage simultaneously: your attacking units take the defender's Might back.
- Evaluate an attack as a trade — what you kill vs. what you lose — not just
  whether you can deal lethal.

### Priority / Focus (summary — see detailed module in closed/showdown states)
- **Priority**: right to react/pass on the Chain in Closed states (`i_have_priority`).
- **Focus**: right to play Actions/pass during Showdown Open (`i_have_focus`).
- If neither is true you should not be asked to decide.

### Need more detail?
For combat damage math, Priority/Focus timing, scoring edge cases, or any keyword
not shown in this prompt, call `lookup_rule` (e.g. lookup_rule('combat damage'))
or `get_keyword` (e.g. get_keyword('Tank')) instead of guessing.
