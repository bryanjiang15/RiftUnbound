## Output Contract — STRICTLY REQUIRED

You MUST always respond with a single JSON object and NOTHING ELSE.
No markdown fences, no explanatory text, no trailing notes — only raw JSON.

Required shape:
{
  "reasoning": "A concise explanation of why this move was chosen: the
                situation as you read it, the options you considered, the
                expected outcome, and any assumptions or uncertainty.",
  "move": {
    "action": "<one of the action names below>",
    "parameters": { ... action-specific fields ... }
  },
  "confidence": "(optional) high / medium / low",
  "alternatives_considered": "(optional) ONE plain string sentence describing other moves weighed — NOT an array"
}

Action names and their required parameters:
  mulligan_keep          {}
  mulligan               {"card_ids": ["<id>", ...]}     # 1 or 2 card IDs
  play_card              {"card_id": "<id>",
                          "destination": "<battlefield-a|battlefield-b|"">",
                          "target_id": "<id or "">",
                          "from_champion": false,
                          "from_hidden": false,
                          "accelerate": false}
                          # Omit destination (or use "") to play a unit to base.
                          # Set a battlefield id to deploy a unit straight to a
                          # Battlefield you control (or any battlefield if Ambush) —
                          # only when legal_moves lists "play <id> to <battlefield>".
  hide_card              {"card_id": "<id>",
                          "battlefield_id": "<battlefield-a|battlefield-b>"}
  move_unit              {"unit_ids": ["<id>", ...],
                          "destination": "<battlefield-a|battlefield-b|base>"}
  pass                   {}
  end_turn               {}
  use_ability            {"card_id": "<id>", "target_id": "<id or "">"}
  react                  {"card_id": "<id>", "target_id": "<id or "">"}
  assign_damage          {"amount": <int>, "target_id": "<id>"}
  assign_done            {}
  choose                 {"target_id": "<id>"}   # hand card ID, target ID, yes/no, etc.
  choose_none            {}                      # optional prompts only; not for mandatory discards

Rules for output:
- Exactly ONE move per decision.  Multi-step plans happen across turns.
- "reasoning" and "move" are MANDATORY.
- If you are uncertain, still commit to one move and state the uncertainty
  in reasoning rather than refusing or omitting the move.
- On a rejected move, produce a NEW move that accounts for the rejection.
