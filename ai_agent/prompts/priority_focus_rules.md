## Turn States, Priority & Focus — Detailed (Chain / Showdown active)

### Turn States
- **Neutral Open**: Main Phase, no Chain. Only the Turn Player acts.
- **Neutral Closed**: a Chain exists, no Showdown. Only the **Priority** holder may
  react or pass on the chain.
- **Showdown Open**: Showdown/Combat active, no Chain. Only the player with
  **Focus** may play Actions or pass Focus.
- **Showdown Closed**: Showdown/Combat active AND a Chain exists. Only the
  **Priority** holder may react or pass on the chain (Focus is suspended until the
  chain resolves).

### Priority vs Focus
- **Priority**: right to react or pass on the Chain in Closed states
  (`i_have_priority` in the brief state).
- **Focus**: right to play Actions or pass Focus during Showdown Open
  (`i_have_focus` in the brief state).
- During Showdown Closed with a Chain, pass/react uses **Priority**, not Focus.
- `pass` gives up Priority (chain) or Focus (showdown open). When all players pass
  Focus in sequence during a Showdown, the Showdown closes.
- If neither `i_have_focus` nor `i_have_priority` is true, you should not be asked
  to decide — the engine is waiting on your opponent.

### Card timing
- **Reaction**: can be played during Closed states on any player's turn.
- **Action**: can be played during Showdown Open states.
