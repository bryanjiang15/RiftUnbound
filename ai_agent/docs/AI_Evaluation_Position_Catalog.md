# AI Evaluation Position Catalog

Generated from `Data/AI/Eval/positions/*.json`. Do not hand-edit;
regenerate with `python -m ai_agent.eval render-catalog`.

Total positions: **33**

## Blocking (15)

### `budget-cutoff-incomplete` — Budget cutoff marks incomplete lines

- **Summary:** Zero expansion budget promotes an incomplete frontier candidate that must not look complete.
- **Objective:** Never commit incomplete budget-cutoff lines as full turns.
- **Desired result:** Candidate legal but complete=false with terminal_reason node_budget.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/search_reorderable.json` (hash `b1381b3fdc6eb9bf`)
- **Seat / decision:** seat 0, `main_phase`
- **Label / fidelity:** gold / authoritative
- **Eval lane:** `engine` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** reasoner, safety, blocking, engine_contract
- **Setup:** Zero expansion budget promotes an incomplete frontier candidate that must not look complete.
- **Hard invariants:** incomplete_not_committed: Incomplete lines not committed
- **Acceptable outcomes:** incomplete_budget_cutoff: Explicit incomplete marker
- **Trap outcomes:** (none)
- **Exclusions:** none
- **Source:** RuleSearchTests._test_budget_cutoff_line_is_incomplete

### `canonical-end-turn-commit` — Canonical reasoner end-turn commit executes

- **Summary:** A complete hashed end-turn line must execute and flip the turn player.
- **Objective:** Validate _try_commit_reasoner_line happy path.
- **Desired result:** Commit accepted; turn_player_index becomes 1.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/search_reorderable.json` (hash `b1381b3fdc6eb9bf`)
- **Seat / decision:** seat 0, `main_phase`
- **Label / fidelity:** gold / authoritative
- **Eval lane:** `engine` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** reasoner, contract, blocking, engine_contract
- **Setup:** A complete hashed end-turn line must execute and flip the turn player.
- **Hard invariants:** commit_accepted: Commit accepted
- **Acceptable outcomes:** turn_advances: Turn player flips
- **Trap outcomes:** (none)
- **Exclusions:** none
- **Source:** RuleReasonerTests._test_canonical_reasoner_line_executes

### `greedy-discard-keeps-reaction` — Greedy discard keeps reaction

- **Summary:** Forced discard should keep gust and discard fading-memories.
- **Objective:** Preserve playable reaction under discard pressure.
- **Desired result:** choose fading-memories; gust remains in hand.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/eval_greedy_discard.json` (hash `7730f5ae28182b69`)
- **Seat / decision:** seat 0, `pending_choice`
- **Label / fidelity:** gold / authoritative
- **Eval lane:** `engine` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** targets, resources, blocking, engine_contract
- **Setup:** Pending choose_discard with gust and fading-memories; one ready fury rune.
- **Hard invariants:** legal_choice: Choice must be legal
- **Acceptable outcomes:** discard_card: Discard do-nothing card
- **Trap outcomes:** (none)
- **Exclusions:** none
- **Source:** RuleSearchTests._test_discard_picks_best_card

### `hashless-line-rejected` — Hashless invented line rejected

- **Summary:** Lines without expected_pre_hashes must never execute.
- **Objective:** Reject hashless commit.
- **Desired result:** Commit rejected; board unchanged.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/search_reorderable.json` (hash `b1381b3fdc6eb9bf`)
- **Seat / decision:** seat 0, `main_phase`
- **Label / fidelity:** gold / authoritative
- **Eval lane:** `engine` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** reasoner, safety, blocking, engine_contract
- **Setup:** Lines without expected_pre_hashes must never execute.
- **Hard invariants:** hashless_line_rejected: Hashless invent rejected
- **Acceptable outcomes:** reject_hashless: No mutation
- **Trap outcomes:** (none)
- **Exclusions:** none
- **Source:** RuleReasonerTests._test_hashless_reasoner_line_rejected

### `jinx-auto-discard-chain` — Jinx play auto-discard hash chain

- **Summary:** Seeded play jinx-demolitionist must expand through intermediate choose steps with full hashes.
- **Objective:** Produce a complete hashed line including both auto-discard choices.
- **Desired result:** Complete line: play jinx + 2 intermediate chooses; parallel arrays equal length.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/eval_jinx_auto_discard.json` (hash `cf01aeb46f01647b`)
- **Seat / decision:** seat 0, `main_phase`
- **Label / fidelity:** gold / authoritative
- **Eval lane:** `engine` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** jinx, pending_choice, reasoner, blocking, engine_contract
- **Setup:** P0 has jinx + 2 fury runes + void-seeker; pool 10E + 1 fury.
- **Hard invariants:** chosen_line_complete: Complete hashed line
- **Acceptable outcomes:** seeded_jinx_auto_choices: Two intermediate chooses
- **Trap outcomes:** (none)
- **Exclusions:** none
- **Source:** RuleSearchTests._test_jinx_seed_search_captures_auto_choices

### `jinx-base-cost-recycles` — Jinx base cost auto-recycles for power

- **Summary:** Playing jinx with 0 pool power must auto-recycle a fury rune for domain power.
- **Objective:** Do not assume all runes only tap for energy.
- **Desired result:** Play succeeds with auto-recycle; jinx enters exhausted without accelerate.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/eval_jinx_cost_recycle.json` (hash `5fb0476b79ece0ee`)
- **Seat / decision:** seat 0, `main_phase`
- **Label / fidelity:** gold / authoritative
- **Eval lane:** `agent` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** resources, jinx, blocking, agent_decision
- **Setup:** Playing jinx with 0 pool power must auto-recycle a fury rune for domain power.
- **Hard invariants:** command_legal: Base play is legal
- **Acceptable outcomes:** command_prefix: Play jinx without accelerate
- **Trap outcomes:** (none)
- **Exclusions:** none
- **Source:** RuleResourcesTests._test_jinx_base_cost_recycles_for_power

### `keep-reaction-under-discard` — Keep reaction under forced discard

- **Summary:** Forced discard should keep gust and discard fading-memories.
- **Objective:** Preserve playable reaction under discard pressure.
- **Desired result:** choose fading-memories; gust remains in hand.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/eval_greedy_discard.json` (hash `7730f5ae28182b69`)
- **Seat / decision:** seat 0, `pending_choice`
- **Label / fidelity:** gold / authoritative
- **Eval lane:** `agent` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** agent_smoke, preference, targets, resources, blocking, agent_decision
- **Setup:** Pending choose_discard with gust and fading-memories; one ready fury rune.
- **Hard invariants:** legal_choice: Choice must be legal
- **Acceptable outcomes:** discard_card: Discard do-nothing card; keep gust
- **Trap outcomes:** (none)
- **Exclusions:** Never discard gust when fading-memories is a legal choice.
- **Source:** RuleSearchTests._test_discard_picks_best_card

### `react-dont-end-turn` — Reactive window does not end turn

- **Summary:** In showdown focus, open with pass/play/react — never main-phase end turn.
- **Objective:** First reactive move is pass/play/react, never end turn or move.
- **Desired result:** No end-turn or move opener in the reactive window.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/eval_reactive_showdown.json` (hash `88fa2fa9c2acf1a0`)
- **Seat / decision:** seat 0, `showdown_focus`
- **Label / fidelity:** gold / fidelity_limited
- **Eval lane:** `agent` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** agent_smoke, priority, reactions, blocking, agent_decision
- **Setup:** Showdown open on battlefield-a; P0 has void-seeker in hand and energy to react.
- **Hard invariants:** reactive_mode: Decision is in a reactive / showdown window
- **Acceptable outcomes:** no_end_turn_opener: Does not open with end turn or move
- **Trap outcomes:** (none)
- **Exclusions:** Opponent responses auto-passed in simulation; diagnostic until contested modeling improves. Never open with end turn.
- **Source:** RuleSearchTests._test_reactive_search_in_showdown_window

### `reactive-showdown-search` — Reactive search in showdown window

- **Summary:** Reactive mode must navigate a showdown focus window without emitting main-phase end turn.
- **Objective:** First reactive move is pass/play/react, never end turn or move.
- **Desired result:** search_stats.mode == reactive; no end-turn opener.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/eval_reactive_showdown.json` (hash `88fa2fa9c2acf1a0`)
- **Seat / decision:** seat 0, `showdown_focus`
- **Label / fidelity:** gold / fidelity_limited
- **Eval lane:** `engine` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** priority, reactions, blocking, engine_contract
- **Setup:** Reactive mode must navigate a showdown focus window without emitting main-phase end turn.
- **Hard invariants:** reactive_mode: Search mode reactive
- **Acceptable outcomes:** no_end_turn_opener: Does not open with end turn
- **Trap outcomes:** (none)
- **Exclusions:** Opponent responses auto-passed in simulation; diagnostic until contested modeling improves.
- **Source:** RuleSearchTests._test_reactive_search_in_showdown_window

### `reorderable-transposition` — Reorderable moves / transposition safety

- **Summary:** Two ready units can move in either order; search should dedupe permutations.
- **Objective:** Return complete legal candidates without mutating live state.
- **Desired result:** Search returns candidates; transposition hits > 0 for deeper budgets.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/search_reorderable.json` (hash `b1381b3fdc6eb9bf`)
- **Seat / decision:** seat 0, `main_phase`
- **Label / fidelity:** gold / authoritative
- **Eval lane:** `engine` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** search, mechanics, blocking, engine_contract
- **Setup:** Two ready units can move in either order; search should dedupe permutations.
- **Hard invariants:** live_state_unchanged: Search must not mutate the fixture root
- **Acceptable outcomes:** has_complete_candidates: At least one complete candidate
- **Trap outcomes:** (none)
- **Exclusions:** none
- **Source:** RuleSearchTests._test_transposition_table_dedupes_reorderings

### `seeded-end-turn-complete` — Seeded end-turn completeness contract

- **Summary:** A forced end-turn seed must produce a complete hashed line.
- **Objective:** Preserve root hash, parallel move/context/hash arrays, and complete=true.
- **Desired result:** Exactly one complete end_turn line with matching root hash.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/search_reorderable.json` (hash `b1381b3fdc6eb9bf`)
- **Seat / decision:** seat 0, `main_phase`
- **Label / fidelity:** gold / authoritative
- **Eval lane:** `engine` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** reasoner, contract, blocking, engine_contract
- **Setup:** A forced end-turn seed must produce a complete hashed line.
- **Hard invariants:** chosen_line_complete: Line complete; root_hash_matched: Root hash retained
- **Acceptable outcomes:** terminal_reason: Ends turn
- **Trap outcomes:** (none)
- **Exclusions:** none
- **Source:** RuleSearchTests._test_seeded_end_turn_line_is_complete

### `stale-root-rejected` — Stale root hash rejected

- **Summary:** Reasoner commits with mismatched root_state_hash must be rejected before step zero.
- **Objective:** Reject stale commit without mutating the board.
- **Desired result:** Commit rejected; structural hash unchanged.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/search_reorderable.json` (hash `b1381b3fdc6eb9bf`)
- **Seat / decision:** seat 0, `main_phase`
- **Label / fidelity:** gold / authoritative
- **Eval lane:** `engine` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** reasoner, safety, blocking, engine_contract
- **Setup:** Reasoner commits with mismatched root_state_hash must be rejected before step zero.
- **Hard invariants:** stale_root_rejected: Mismatched root rejected
- **Acceptable outcomes:** reject_stale_root: No mutation on reject
- **Trap outcomes:** (none)
- **Exclusions:** none
- **Source:** RuleReasonerTests._test_root_mismatch_rejected_before_step_zero

### `tap-rune-energy` — Tap rune for energy

- **Summary:** Basic resource action: tapping a ready rune adds one energy.
- **Objective:** Enumerate and prefer tap when energy is needed.
- **Desired result:** After tap rune-0, energy increases by 1.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/resources_tap_rune.json` (hash `2562b66a9aa081fe`)
- **Seat / decision:** seat 0, `main_phase`
- **Label / fidelity:** gold / authoritative
- **Eval lane:** `engine` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** resources, blocking, engine_contract
- **Setup:** Basic resource action: tapping a ready rune adds one energy.
- **Hard invariants:** command_legal: tap rune-0 is legal
- **Acceptable outcomes:** command_prefix: Tap a rune
- **Trap outcomes:** (none)
- **Exclusions:** none
- **Source:** RuleResourcesTests._test_tap_adds_energy

### `turn8-two-point-continuation` — Turn 8 multi-action two-point continuation

- **Summary:** Search must discover a multi-action line that scores at least two points, not stop after one conquer.
- **Objective:** Reach my_score_after >= 4 from score 2 via multi-action play/move chain.
- **Desired result:** At least one complete candidate scores >= 4; agent prefers a two-point continuation over a one-ply scout.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/reasoner_turn8_two_point.json` (hash `c6bad80f2bfca311`)
- **Seat / decision:** seat 0, `main_phase`
- **Label / fidelity:** gold / authoritative
- **Eval lane:** `agent` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** agent_smoke, ordering, reasoner, blocking, agent_decision
- **Setup:** P0 score 2, energy 6, hand blazing-scorcher + scrapheap, flame-chompers at base.
- **Hard invariants:** root_hash_matched: Decision pinned to fixture root
- **Acceptable outcomes:** score_after_at_least: Reach score >= 4
- **Trap outcomes:** (none)
- **Exclusions:** none
- **Source:** RuleReasonerTests._test_turn8_two_point_continuation_discoverable

### `win-from-seven` — Forced win from seven points

- **Summary:** Two ready units can move to empty battlefields and conquer for the winning point.
- **Objective:** Find a line that wins the game this turn.
- **Desired result:** Chosen complete line sets wins_game / reaches victory score.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/search_winning_line.json` (hash `ff087a39b28029c1`)
- **Seat / decision:** seat 0, `main_phase`
- **Label / fidelity:** gold / authoritative
- **Eval lane:** `agent` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** agent_smoke, terminal_tactics, blocking, search, agent_decision
- **Setup:** P0 score 7 with Vi and Chemtech Enforcer ready at base; empty battlefields.
- **Hard invariants:** chosen_line_complete: Committed line must be complete
- **Acceptable outcomes:** wins_game: Line wins the game
- **Trap outcomes:** (none)
- **Exclusions:** none
- **Source:** RuleSearchTests._test_search_finds_winning_line

## Dev (16)

### `anytime-budget-returns-line` — Anytime node budget still returns a line

- **Summary:** Even with node_budget=1 search must return a candidate and report stop reason.
- **Objective:** Graceful degradation under budget pressure.
- **Desired result:** Non-empty candidates; stopped_reason node_budget when forced.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/search_reorderable.json` (hash `b1381b3fdc6eb9bf`)
- **Seat / decision:** seat 0, `main_phase`
- **Label / fidelity:** gold / authoritative
- **Eval lane:** `engine` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** reliability, search, dev, engine_contract
- **Setup:** Even with node_budget=1 search must return a candidate and report stop reason.
- **Hard invariants:** has_candidates: Returns candidates under budget
- **Acceptable outcomes:** has_candidates: Anytime returns a line
- **Trap outcomes:** (none)
- **Exclusions:** none
- **Source:** RuleSearchTests._test_anytime_budget_returns_lines

### `assault-trade-showdown` — Assault attacker wins equal trade

- **Summary:** Equal might with assault: attacker should survive the trade and conquer.
- **Objective:** Assign combat correctly under assault.
- **Desired result:** Attacker remains; defender dies; battlefield controlled by attacker.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/eval_assault_trade.json` (hash `c151ccb63c7465c9`)
- **Seat / decision:** seat 0, `showdown_focus`
- **Label / fidelity:** gold / fidelity_limited
- **Eval lane:** `agent` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** combat, assault, dev, agent_decision
- **Setup:** Equal might with assault: attacker should survive the trade and conquer.
- **Hard invariants:** combat_window: Showdown open
- **Acceptable outcomes:** attacker_survives_trade: Assault attacker wins trade
- **Trap outcomes:** (none)
- **Exclusions:** Manual combat assignment simplified in some simulation paths.
- **Source:** RuleCombatTests._test_assault_attacker_survives_defender_dies

### `close-from-six-double` — Close from six via double conquer

- **Summary:** At score 6 with two ready units and empty battlefields, execute the lethal double-conquer.
- **Objective:** Find a complete line that wins this turn from 6.
- **Desired result:** Chosen complete line sets wins_game.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/eval_close_from_six_double.json` (hash `ef0f4477ede96de1`)
- **Seat / decision:** seat 0, `main_phase`
- **Label / fidelity:** gold / authoritative
- **Eval lane:** `agent` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** decision_v2, lethal, trap, agent_decision
- **Setup:** P0 score 6; Vi + Chemtech Enforcer ready at base; both battlefields empty.
- **Hard invariants:** chosen_line_complete: Complete line
- **Acceptable outcomes:** wins_game: Double conquer closes from 6
- **Trap outcomes:** command_equals: Idle instead of closing
- **Exclusions:** Never end turn or develop without taking the available close.
- **Source:** eval_close_from_six_double.json

### `deploy-to-controlled-battlefield` — Deploy unit to controlled battlefield

- **Summary:** When controlling a battlefield, legal plays include deploying directly to that field.
- **Objective:** Prefer or at least enumerate play-to-battlefield commands.
- **Desired result:** Legal moves include play chemtech-enforcer to battlefield-a.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/eval_deploy_controlled_bf.json` (hash `d10bc05019510ef0`)
- **Seat / decision:** seat 0, `main_phase`
- **Label / fidelity:** gold / authoritative
- **Eval lane:** `agent` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** movement, legal_moves, dev, agent_decision
- **Setup:** When controlling a battlefield, legal plays include deploying directly to that field.
- **Hard invariants:** legal_move_contains: Deploy-to-BF enumerated
- **Acceptable outcomes:** command_contains: Play onto controlled BF
- **Trap outcomes:** (none)
- **Exclusions:** none
- **Source:** RuleMovementTests._test_play_unit_to_controlled_battlefield

### `discard-development-line` — Flame Chompers / Scrapheap discard development

- **Summary:** Hand supports discard-triggered development with Flame Chompers and Scrapheap.
- **Objective:** Use discard synergies rather than a do-nothing discard.
- **Desired result:** A line that develops via discard triggers / play-self is preferred over idle.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/eval_discard_development.json` (hash `17e2486d84135bc2`)
- **Seat / decision:** seat 0, `main_phase`
- **Label / fidelity:** silver / authoritative
- **Eval lane:** `agent` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** agent_smoke, cards, tempo, dev, agent_decision
- **Setup:** Hand: flame-chompers, scrapheap, fading-memories with fury runes.
- **Hard invariants:** chosen_line_legal: Legal complete line
- **Acceptable outcomes:** develops_via_discard: Uses discard development
- **Trap outcomes:** (none)
- **Exclusions:** none
- **Source:** CardScenarioTests flame-chompers/scrapheap

### `float-gust-deny-lethal` — Float Gust energy to stop opponent lethal

- **Summary:** You hold a big unit on BF-A; opponent at 6 has watcher + poro in base and can contest-kill then double-conquer for the win. Keep 1 energy for Gust.
- **Objective:** End turn floating energy so Gust can bounce the small unit when they try to take the second battlefield. Do not tap out on Chemtech Enforcer.
- **Desired result:** Chosen opener is end turn with Gust still in hand and energy available.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/eval_float_gust_deny_lethal.json` (hash `379bd09cab8a7cb4`)
- **Seat / decision:** seat 0, `main_phase`
- **Label / fidelity:** gold / authoritative
- **Eval lane:** `agent` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** decision_v2, resources, reaction, trap, agent_decision
- **Setup:** P0: blazing-scorcher (5) on BF-A; hand gust + chemtech; energy 2. P1 score 6: thousand-tailed-watcher (7) + stalwart-poro (2) ready in base. BF-B empty. Next turn P1 can kill scorcher with watcher then conquer B with poro for 8 unless Gust bounces the poro.
- **Hard invariants:** chosen_line_complete: Complete line
- **Acceptable outcomes:** command_equals: Float energy for Gust against next-turn lethal
- **Trap outcomes:** command_prefix: Tap out on a develop and risk discarding Gust while opponent is lethal
- **Exclusions:** Never empty the pool on Chemtech while Gust is the only answer to opponent's 6-score double-conquer lethal.
- **Source:** eval_float_gust_deny_lethal.json

### `gust-might-filter` — Gust respects might filter

- **Summary:** Gust may only target units within its might constraint.
- **Objective:** Do not target illegal high-might units.
- **Desired result:** Chosen gust target is within might filter at cast/resolution.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/eval_gust_target.json` (hash `7ced4215f517318c`)
- **Seat / decision:** seat 0, `main_phase`
- **Label / fidelity:** gold / authoritative
- **Eval lane:** `agent` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** targets, spells, dev, agent_decision
- **Setup:** Gust may only target units within its might constraint.
- **Hard invariants:** target_legal: Target in valid set
- **Acceptable outcomes:** gust_valid_target: Valid might-filtered target
- **Trap outcomes:** (none)
- **Exclusions:** none
- **Source:** CardScenarioTests._test_gust_might_filter

### `hold-open-rune-discipline` — Hold: take empty B instead of contesting into Discipline

- **Summary:** Opponent holds BF-A with a 2-might unit, 2 ready runes, and Discipline. Move to empty BF-B; do not contest A or pass idle.
- **Objective:** Move Flame Chompers onto empty battlefield-b. Do not contest A (Discipline makes 4 > 3) and do not end turn doing nothing.
- **Desired result:** Chosen line takes battlefield-b.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/eval_hold_open_rune_discipline.json` (hash `9f486e5a7b74ef22`)
- **Seat / decision:** seat 0, `main_phase`
- **Label / fidelity:** gold / fidelity_limited
- **Eval lane:** `agent` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** decision_v2, open_rune, reaction, battlefield, trap, agent_decision
- **Setup:** P0: flame-chompers (3) ready in base. P1: stalwart-poro (2) on BF-A; hand discipline; two ready calm runes. BF-B empty. React Discipline → poro 4 > chompers 3.
- **Hard invariants:** root_hash_matched: Decision pinned to fixture root; has_candidates: Search returned candidates
- **Acceptable outcomes:** line_contains: Take empty BF-B instead of contested A
- **Trap outcomes:** line_contains: Contest A into Discipline buff (2+2 beats your 3); command_equals: Idle pass when empty BF-B is free
- **Exclusions:** Never move onto battlefield-a while opponent has Discipline and two ready runes. Never end turn when BF-B is free.
- **Source:** eval_hold_open_rune_discipline.json

### `reinforce-hold-at-seven` — Reinforce: hold A at score 7

- **Summary:** Both players at 7; same 2-might on A vs 4-might in opp base, but you have two 3-drops and energy to play both. Hold A by reinforcing.
- **Objective:** Keep and reinforce battlefield-a (play Flame Chompers onto A). Do not retreat to base.
- **Desired result:** Chosen line commits Flame Chompers to battlefield-a while keeping presence there.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/eval_reinforce_hold_at_seven.json` (hash `e7dff78d04c17bed`)
- **Seat / decision:** seat 0, `main_phase`
- **Label / fidelity:** gold / authoritative
- **Eval lane:** `agent` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** decision_v2, retreat, battlefield, trap, agent_decision
- **Setup:** P0 score 7: chemtech-enforcer (2) on BF-A; hand two flame-chompers (3); energy 6. P1 score 7: raging-soul (4) ready in base. BF-B empty. Reinforcing makes the pile beat 4.
- **Hard invariants:** root_hash_matched: Decision pinned to fixture root; has_candidates: Search returned candidates
- **Acceptable outcomes:** line_contains: Reinforce A to hold at score 7
- **Trap outcomes:** line_contains: Retreat off A when holding/reinforcing is required at 7
- **Exclusions:** Never recall Chemtech off A at score 7 when you can reinforce to beat the 4-might threat.
- **Source:** eval_reinforce_hold_at_seven.json

### `retreat-low-score-threat` — Retreat: leave A and develop at base

- **Summary:** Low scores; 2-might on A faces a 4-might in opponent base. Retreat and play Flame Chompers at base instead of reinforcing A.
- **Objective:** Move Chemtech Enforcer to base and develop Flame Chompers at base. Do not pile onto A.
- **Desired result:** Chosen line recalls the unit to base (and preferably plays the 3-drop at base).
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/eval_retreat_low_score_threat.json` (hash `c1090cfd7ddb5289`)
- **Seat / decision:** seat 0, `main_phase`
- **Label / fidelity:** gold / authoritative
- **Eval lane:** `agent` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** decision_v2, retreat, battlefield, trap, agent_decision
- **Setup:** P0 score 2: chemtech-enforcer (2) on BF-A; hand flame-chompers (3); energy 3. P1 score 2: raging-soul (4) ready in base. BF-B empty.
- **Hard invariants:** root_hash_matched: Decision pinned to fixture root; has_candidates: Search returned candidates
- **Acceptable outcomes:** line_contains: Retreat the 2-might off A
- **Trap outcomes:** line_contains: Reinforce A into a likely losing pile vs the 4-might
- **Exclusions:** Never reinforce battlefield-a with Flame Chompers while opponent has a ready 4-might and scores are low. Prefer recall + develop at base.
- **Source:** eval_retreat_low_score_threat.json

### `spend-develop-no-threat` — Develop instead of floating unused Gust

- **Summary:** Empty board; opponent has two small base units but is not on a lethal clock. Play the 2-drop rather than passing to float Gust.
- **Objective:** Develop Stalwart Poro. Holding energy for Gust is wrong when you have no board and no imminent lethal to answer.
- **Desired result:** Chosen line plays stalwart-poro.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/eval_spend_develop_no_threat.json` (hash `dd2211fa58e03a2d`)
- **Seat / decision:** seat 0, `main_phase`
- **Label / fidelity:** gold / authoritative
- **Eval lane:** `agent` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** decision_v2, resources, reaction, trap, agent_decision
- **Setup:** P0: empty board; hand gust + stalwart-poro; energy 2. P1 score 0: chemtech-enforcer + stalwart-poro in base. Both BFs empty — develop presence.
- **Hard invariants:** chosen_line_complete: Complete line
- **Acceptable outcomes:** command_prefix: Develop board instead of floating
- **Trap outcomes:** command_equals: Paranoid float when Gust has no lethal to stop and board is empty
- **Exclusions:** Never end turn floating Gust when you have no units and opponent is not threatening an immediate win.
- **Source:** eval_spend_develop_no_threat.json

### `take-closed-runes-contest` — Take: contest A when opponent runes are down

- **Summary:** Same board as the open-rune hold twin, but opponent runes are exhausted. Contest A (3 > 2) instead of only taking empty B or passing.
- **Objective:** Move Flame Chompers onto battlefield-a. Empty B is available but the favorable contest on A is the correct line.
- **Desired result:** Chosen line contests battlefield-a.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/eval_take_closed_runes_contest.json` (hash `09e7a8930bfe11d4`)
- **Seat / decision:** seat 0, `main_phase`
- **Label / fidelity:** gold / authoritative
- **Eval lane:** `agent` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** decision_v2, open_rune, reaction, battlefield, trap, agent_decision
- **Setup:** Same board as hold-open-rune-discipline (poro on A, BF-B empty), but P1 calm runes are exhausted (pool 0). Discipline is in hand but unpayable. 3 > 2 wins combat on A.
- **Hard invariants:** root_hash_matched: Decision pinned to fixture root; has_candidates: Search returned candidates
- **Acceptable outcomes:** line_contains: Contest A while Discipline cannot be paid
- **Trap outcomes:** command_equals: Idle pass when a favorable contest exists; line_contains: Take empty B instead of the safe contest on A
- **Exclusions:** Never decline battlefield-a when opponent runes are exhausted. Prefer the favorable contest over only taking empty B or passing.
- **Source:** eval_take_closed_runes_contest.json

### `tempo-hold-contested-wipe` — Hold: refuse overcommit into wipe range

- **Summary:** Opponent holds BF-A with 3 might and a 7-might unit in base; do not dump buff + reinforce into A.
- **Objective:** Avoid spending resources to contest battlefield-a when opponent can wipe the pile next turn. Develop at base or take empty battlefield-b while keeping base presence.
- **Desired result:** Chosen line develops raging-soul at base and/or contests battlefield-b; never commits to battlefield-a.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/eval_tempo_hold_contested_wipe.json` (hash `64b6ca018a4281b9`)
- **Seat / decision:** seat 0, `main_phase`
- **Label / fidelity:** gold / authoritative
- **Eval lane:** `agent` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** decision_v2, tempo_axis, battlefield, overcommit, trap, agent_decision
- **Setup:** P0: chemtech-enforcer (2) ready at base; hand discipline (+2) + raging-soul (4); energy 6. P1: flame-chompers (3) on BF-A, thousand-tailed-watcher (7) ready at base. BF-B empty.
- **Hard invariants:** root_hash_matched: Decision pinned to fixture root; has_candidates: Search returned candidates
- **Acceptable outcomes:** line_contains: Develop the 4-might unit (base play omits destination); line_contains: Contest empty battlefield-b instead of A
- **Trap outcomes:** line_contains: Overcommit into contested A (buff/move/reinforce) into opponent wipe range
- **Exclusions:** Never move/play/buff into battlefield-a when opponent can answer with thousand-tailed-watcher from base.
- **Source:** eval_tempo_hold_contested_wipe.json

### `tempo-take-contested-fof` — Take: contest A when FoF protects next turn

- **Summary:** Same contested A + watcher wipe setup, but Fight or Flight in hand with an open rune makes committing to A correct.
- **Objective:** Contest battlefield-a (buff / move / reinforce). Keep Fight or Flight in hand and leave at least one rune open so you can bounce or recall if the watcher contests next turn.
- **Desired result:** Chosen line commits to battlefield-a; FoF remains unspent this turn.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/eval_tempo_take_contested_fof.json` (hash `44b4927d4ef9ff81`)
- **Seat / decision:** seat 0, `main_phase`
- **Label / fidelity:** gold / authoritative
- **Eval lane:** `agent` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** decision_v2, tempo_axis, battlefield, overcommit, trap, agent_decision
- **Setup:** Same board as tempo-hold-contested-wipe, plus fight-or-flight in hand and an extra ready chaos rune. P0: chemtech ready; hand discipline + raging-soul + fight-or-flight; energy 6. P1: flame-chompers on A, thousand-tailed-watcher ready in base. BF-B empty.
- **Hard invariants:** root_hash_matched: Decision pinned to fixture root; has_candidates: Search returned candidates
- **Acceptable outcomes:** line_contains: Contest A while FoF answers the next-turn wipe
- **Trap outcomes:** command_equals: Pass when FoF makes the contested contest safe; line_contains: Spend FoF this turn instead of holding it for next-turn protection
- **Exclusions:** Never decline battlefield-a when Fight or Flight plus an open rune answers the watcher's next-turn contest. Keep FoF in hand this turn.
- **Source:** eval_tempo_take_contested_fof.json

### `unopposed-move-conquers` — Unopposed move conquers

- **Summary:** Moving the only unit to an empty battlefield conquers if unanswered.
- **Objective:** Select a move that conquers.
- **Desired result:** simulate/resolved_if_unanswered.conquer == true for the chosen move.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/movement_base_to_bf.json` (hash `0c092eb865d653a5`)
- **Seat / decision:** seat 0, `main_phase`
- **Label / fidelity:** gold / authoritative
- **Eval lane:** `agent` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** agent_smoke, battlefield, movement, dev, agent_decision
- **Setup:** Single ready unit at base; empty battlefields — take the free conquer.
- **Hard invariants:** live_state_unchanged: Simulation must not mutate live
- **Acceptable outcomes:** conquers_if_unanswered: Unanswered move conquers
- **Trap outcomes:** (none)
- **Exclusions:** Never idle/end turn when an unanswered move conquers.
- **Source:** RuleSimulationTests._test_simulate_unopposed_move_conquers

### `winning-point-draws` — Winning point draws instead of scoring eight

- **Summary:** At score 7, establishing control draws rather than scoring the eighth point.
- **Objective:** Respect winning-point replacement effect.
- **Desired result:** Score stays 7; draw occurs.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/winning_point_conquer.json` (hash `3ad9c2f5d36b057e`)
- **Seat / decision:** seat 0, `main_phase`
- **Label / fidelity:** gold / authoritative
- **Eval lane:** `engine` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** scoring, rules, dev, engine_contract
- **Setup:** At score 7, establishing control draws rather than scoring the eighth point.
- **Hard invariants:** score_cap_behavior: Winning point replacement
- **Acceptable outcomes:** score_remains: Does not reach 8 via hold
- **Trap outcomes:** (none)
- **Exclusions:** none
- **Source:** RuleScoringTests._test_winning_point_draws_instead

## Sealed (2)

### `sealed-turn8-holdout` — Sealed holdout: Turn 8 two-point continuation

- **Summary:** Sealed twin of the Turn 8 continuation for release scoring.
- **Objective:** Reach score >= 4.
- **Desired result:** Two-point continuation found.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/reasoner_turn8_two_point.json` (hash `c6bad80f2bfca311`)
- **Seat / decision:** seat 0, `main_phase`
- **Label / fidelity:** gold / authoritative
- **Eval lane:** `agent` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** ordering, sealed, agent_decision
- **Setup:** Sealed twin of the Turn 8 continuation for release scoring.
- **Hard invariants:** root_hash_matched: Pinned root
- **Acceptable outcomes:** score_after_at_least: Score >= 4
- **Trap outcomes:** (none)
- **Exclusions:** none
- **Source:** RuleReasonerTests._test_turn8_two_point_continuation_discoverable

### `sealed-win-from-seven-holdout` — Sealed holdout: win from seven

- **Summary:** Sealed copy of the lethal win position for release-candidate holdout scoring.
- **Objective:** Same as win-from-seven but not used for prompt tuning.
- **Desired result:** Wins the game.
- **Fixture:** `res://Scripts/Tests/Tcg/fixtures/search_winning_line.json` (hash `ff087a39b28029c1`)
- **Seat / decision:** seat 0, `main_phase`
- **Label / fidelity:** gold / authoritative
- **Eval lane:** `agent` (engine = Godot contracts, no LLM; agent = decision quality)
- **Tags:** terminal_tactics, sealed, agent_decision
- **Setup:** Sealed copy of the lethal win position for release-candidate holdout scoring.
- **Hard invariants:** chosen_line_complete: Complete line
- **Acceptable outcomes:** wins_game: Wins
- **Trap outcomes:** (none)
- **Exclusions:** none
- **Source:** RuleSearchTests._test_search_finds_winning_line
