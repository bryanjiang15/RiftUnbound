# Riftbound AI Agent — Memory & Context Roadmap

## Purpose

This is the master roadmap for evolving the agent's memory from "last 10 raw
decisions in this game" to a layered system that also remembers specific
cards and situations across games. Each phase below is scoped to ship and
verify independently. Detailed per-phase design docs (like
`Phase1_STM_Improvements.md`) get written immediately before that phase
starts, not all up front — this doc is the index and the rationale.

Companion doc: `Agent_design_and_memory.md` (current architecture, context
assembly order, file map).

---

## Vocabulary (mapped to this codebase)

Modern agent-memory literature splits memory into layers; this section maps
them onto our existing/planned tables so later phases share one vocabulary.

| Literature term | What it means | Riftbound equivalent |
|---|---|---|
| **Working memory** | The current prompt/context window for this one decision | `_format_brief_state()` + the system prompt |
| **Episodic memory** | Specific past events, replayable, time-ordered | `decisions` / `opponent_actions` tables (in-game), `games` / `card_plays` (cross-game) |
| **Semantic memory** | Distilled facts/lessons abstracted away from any one episode | `knowledge/lessons.json`, `strategy_patterns.json` (Phase 3+) |
| **Procedural memory** | Reusable "how to do X" routines | N/A for now — our action space is fixed by `legal_moves`, not learned skills |

This mirrors the standard split used across current agent-memory surveys:
short-term/working memory as a limited-capacity scratchpad, long-term
episodic memory for specific past experiences, and semantic memory for
high-level summaries and facts distilled from raw experience ([Memory for
Autonomous LLM
Agents](https://arxiv.org/html/2603.07670v1), [Multi-Layered Memory
Architectures](https://arxiv.org/html/2603.29194v1)).

---

## Phase Overview

| Phase | Name | Memory layer | Status |
|---|---|---|---|
| 1 | STM correctness fixes | Working / episodic (in-game) | **Done** |
| 2 | Cross-game episodic store | Episodic (cross-game) | Not started |
| 3 | Reflection → semantic lessons | Semantic | Not started |
| 4 | Situation & card retrieval | Semantic (retrieval) | Not started |
| 5 | Memory governance | All layers | Not started |
| 6 | Claude migration + prompt caching | Infra | Not started |
| 7 | Resolved-effect & pass-intent enrichment | Working / episodic (in-game) | Not started |

---

## Phase 1 — STM Correctness Fixes (Done)

See `Phase1_STM_Improvements.md` for the full design. Summary of what shipped:
- `opponent_actions` table + `opponent_slice()` — the agent now sees a real
  opponent action log, not just a current-turn snapshot.
- `accepted` / `rejection_reason` are now actually written via
  `update_acceptance_by_game()` (previously always NULL).
- `games` table + `/game_over` endpoint — Godot now reports the final
  outcome, laying the groundwork for Phase 2.

This phase fixed *correctness* of the existing within-game window. It did
not change the shape of what gets injected.

**Update (2026-06-21):** `recent_slice()` and `opponent_slice()` (named above
and in `Phase1_STM_Improvements.md`) were merged into a single
`memory.timeline_slice()` that interleaves both tables by timestamp into one
chronological history instead of two separate per-side blocks, and trimmed
each entry to a compact one-liner (no inline reasoning text). See
`Agent_design_and_memory.md`'s "Short-Term Memory" section for the current
shape. This was prompt/injection-quality polish on top of Phase 1's
correctness fixes, not a new phase.

---

## Phase 2 — Cross-Game Episodic Store

**Goal:** persist what happened in *previous* games so phase 3/4 have
something to learn from. No retrieval or reflection logic yet — just the
storage layer and basic stat queries.

**New tables** (extends `games`, added in Phase 1):
```sql
CREATE TABLE card_plays (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id       TEXT NOT NULL,
    turn          INTEGER NOT NULL,
    card_id       TEXT NOT NULL,        -- base card id, not instance_id
    action        TEXT NOT NULL,        -- play_card / use_ability / react / ...
    decision_type TEXT NOT NULL,
    accepted      INTEGER,
    board_snapshot_hash TEXT,           -- ties back to decisions.brief_state_hash
    outcome       TEXT                  -- filled in by Phase 3 from game result
);
CREATE INDEX idx_card_plays_card ON card_plays (card_id);
```

This table is the substrate for "what happened the last N times I played
this card" — a per-entity episodic log, the same shape RAG-for-agents guides
recommend keeping *underneath* any retrieval layer: structured episodic facts
first, vector/semantic indexing on top of them later, not instead of them.

**Work:**
- Write one `card_plays` row per `decisions` row that has a `card_id` param,
  derived at write time (no new Godot endpoint needed — derived from
  `move_json`).
- Backfill `outcome` on `/game_over` by joining `card_plays.game_id`.
- Add a debug-only skill or CLI query: "win rate / acceptance rate for card
  X across all recorded games" — useful for verifying the data is sane before
  anything reads it automatically.

---

## Phase 3 — Reflection Loop → Semantic Lessons

**Goal:** turn raw episodes into distilled, reusable lessons — the step that
matters most according to both the Generative Agents and Diplomacy-agent
literature.

- In the Generative Agents architecture, removing the reflection step caused
  agent behavior to degenerate from coherent multi-step planning back to
  repetitive, context-free responses within two simulated days — reflection,
  not raw memory volume, was what kept behavior coherent
  ([Generative Agents](https://arxiv.org/html/2603.07670v1) summary of the
  original study; reflection is core to the architecture).
- **Richelieu** (Diplomacy) generalizes this to competitive multi-agent play:
  the agent explicitly recalls and integrates past negotiations/actions to
  inform current decisions and is described as capable of "profound
  reflection" that analyzes its own past decisions and adapts strategy
  accordingly ([Richelieu](https://arxiv.org/html/2407.06813v1)).

**Plan:**
- New `reflection.py`: after `/game_over`, run one async LLM call over that
  game's `decisions` + `card_plays` + outcome. Prompt: "What worked, what
  didn't, what would you do differently?" Output: a small number of natural-
  language lesson strings, each tagged with the card_id(s)/situation it
  applies to.
- New `consolidation.py`: periodically (e.g. every N games) merge/dedupe
  lessons into `knowledge/lessons.json` — same "intelligent forgetting /
  semantic consolidation" idea used in production agent-memory systems to
  keep semantic memory from growing unboundedly
  ([Architecture and Orchestration of Memory Systems](https://www.analyticsvidhya.com/blog/2026/04/memory-systems-in-ai-agents/)).
- This is async and out-of-band — it must never block a live `/decision`
  call. It writes to `knowledge/` for Phase 4 to read.

---

## Phase 4 — Situation & Card Retrieval (the "remembers specific cards" phase)

**Goal:** at decision time, retrieve the handful of past lessons/episodes
most relevant to *this* card or *this* situation — not a fixed recency
window, and not the whole lesson store.

This is the phase that directly answers "context about specific situation or
cards based on what they've encountered in the past":

- **Card-keyed lookup is cheap and should ship first:** index
  `knowledge/lessons.json` and `card_plays` by `card_id`. When the current
  hand/board contains card X, pull its lessons/history directly — no
  embeddings needed for this part, just a dict lookup. This alone covers most
  of the value (e.g. "last 3 times you played Gust here, it was rejected
  because the target had >3 Might").
- **Situation-keyed lookup needs similarity search:** build a numpy-based
  `EmbeddingStore` (zero external deps, cosine similarity) over situation
  fingerprints (board shape: score gap, battlefield control, hand size,
  decision type) so the agent can ask "have I been in a position like this
  before, and what happened?" via a new `get_similar_situations` skill.
- **Use hybrid retrieval, not pure similarity:** current guidance is explicit
  that vector similarity alone over-matches — "everything looks somewhat
  similar to everything else" once the store grows, diluting the model's
  attention with irrelevant context. Production systems run keyword/entity
  matching (card_id, decision_type) and semantic similarity in parallel and
  fuse the results rather than relying on embeddings alone
  ([State of AI Agent Memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026);
  [Memory for Autonomous LLM Agents](https://arxiv.org/html/2603.07670v1)).
  Concretely: card_id exact-match lookup is the keyword/entity pass;
  situation-fingerprint cosine similarity is the semantic pass; only fuse the
  two when both have hits, and cap total injected lessons (e.g. top 3) so
  retrieval quality is prioritized over recall, per the same guidance that
  poor injection timing/volume can make an agent worse, not better.
- Retrieval is opt-in per decision: only call `get_similar_situations` /
  inject card lessons when the current card/situation actually has matches —
  empty results inject nothing, keeping the common case's token cost
  unchanged from today.

---

## Phase 5 — Memory Governance

**Goal:** keep the system bounded and trustworthy as games accumulate. This
phase is policy, not a single feature — apply it incrementally rather than as
a single release.

- **Recency + importance + relevance scoring** for which lessons surface,
  the same composite scoring rule used in the Generative Agents memory
  stream, adapted so "importance" = lesson confidence/sample size rather than
  a simulated character's subjective rating.
- **Timestamps/versions on every lesson** so conflicting lessons (e.g. a
  card's evaluation changed after a balance patch) can be resolved by
  recency rather than silently averaged — directly recommended in recent
  memory-governance literature ([Governing Evolving Memory in LLM
  Agents](https://arxiv.org/html/2603.11768v1)).
- **Forgetting/decay:** lessons with low sample size or that haven't been
  retrieved in N games get pruned or down-weighted during consolidation
  (Phase 3's `consolidation.py` is the natural home for this).
- **Conflict resolution:** when two lessons about the same card disagree,
  consolidation should merge them into one lesson with both outcomes noted
  ("works when X, backfires when Y") rather than picking one arbitrarily.

---

## Phase 6 — Claude API Migration + Prompt Caching

**Goal:** infra change, decoupled from the memory work above.

- Replace `openai` client in `agent.py` with the Anthropic SDK
  (`claude-sonnet-4-6`).
- Add `cache_control` breakpoints after the stable system-prompt prefix
  (`GOAL_AND_ROLE` + `CORE_RULES` + `OUTPUT_CONTRACT`) so repeated decisions
  within a game reuse the cached prefix — this only pays off once memory
  injection (Phases 2-4) makes per-decision context larger and more variable,
  which is why it's sequenced after rather than before.
- No behavior change expected; verify via the existing `agent_inputs.log`
  diffing before/after on a recorded game.

---

## Phase 7 — Resolved-Effect & Pass-Intent Enrichment

**Goal:** today's `timeline_slice()` (see Phase 1 update above) shows *what
move was submitted* and whether it was accepted, but not *what actually
happened as a result* — a `use_ability` or `play_card` line never says "Vi's
Might increased to 11" or "unit X died," and a `pass` line never shows what
was on the chain that prompted it. This phase closes that gap using
machinery that already exists on the Godot side, unused for this purpose.

**What already exists:**
- `GameController._log()` (`Scripts/Game/GameController.gd:1847`) emits a
  `game_log_message` signal for every resolved effect, including the
  human-readable lines `ability_resolver.resolve_ability()` returns (Might
  changes, deaths, draws, zone moves) — not just command echoes.
- `AIPlayer.gd._on_game_log_message()` already subscribes to that signal, but
  today it only pattern-matches the `[P{n}] > {command}` line to detect
  opponent commands; it discards the effect lines that follow.
- `decisions.outcome_summary` (schema column, `update_outcome()` method) has
  existed since before Phase 1 but has never been written to anywhere — it's
  the natural home for this data once populated.

**Plan:**
- In `AIPlayer.gd`, capture the `_log()` lines that follow a command (own or
  opponent's) up to the next command/prompt boundary, and forward a short
  joined effect string alongside the existing `/outcome` and
  `/opponent_action` payloads.
- In `memory.py`, accept that effect text in `update_acceptance_by_game()` /
  `record_opponent_action()` and store it (`outcome_summary` for own
  decisions; extend `opponent_actions` with an `effect` column for the
  opponent side).
- In `timeline_slice()`, append the effect text to each line when present:
  `Turn 7 [main_phase]: You use_ability(...) → OK — Vi's Might increased to 11`.
- **Pass-intent is mostly free once this ships**, not a separate feature: a
  `pass` line has no effect text of its own, but because `timeline_slice` is
  already chronological (Phase 1 update), the triggering action's effect text
  sits directly above the resulting pass — e.g. "opponent played Gust
  targeting Vi" followed by "You passed" reads as cause-and-effect without
  any special-cased "passed on X" string.
- **Signal-to-noise risk:** `ability_resolver`'s log lines are written for a
  human reading a scrolling log, not for LLM context — some (rune-tap
  bookkeeping, internal state transitions) will need filtering before being
  surfaced. Prototype on a handful of real log lines from `agent_inputs.log`-
  style captures before committing to a filtering ruleset, rather than
  assuming all `_log()` output is useful as-is.

---

## Sequencing Notes

- Phases 2 and 3 are pure backend/offline work (no `/decision` path changes)
  and can run with the agent live in its current form.
- Phase 4 is the first phase that changes what gets injected into a live
  decision by anything other than recency — ship it behind a feature flag
  (env var, like `RIFTBOUND_LOG_INPUTS`) so it can be disabled instantly if
  retrieval quality turns out to hurt rather than help, per the standard
  warning that bad retrieval timing/volume can make an agent worse than no
  retrieval at all.
- Phase 5 isn't a release, it's an ongoing discipline applied inside Phases
  3/4's consolidation code as the lesson store grows.
- Phase 7 is the only phase that requires a Godot-side (`AIPlayer.gd`) change
  in addition to Python — sequence it whenever Godot work is convenient,
  independent of the cross-game phases above it.

## Sources

- [Memory for Autonomous LLM Agents: Mechanisms, Evaluation, and Emerging Frontiers](https://arxiv.org/html/2603.07670v1)
- [Multi-Layered Memory Architectures for LLM Agents](https://arxiv.org/html/2603.29194v1)
- [Governing Evolving Memory in LLM Agents (SSGM)](https://arxiv.org/html/2603.11768v1)
- [State of AI Agent Memory 2026: Benchmarks, Architectures & Production Gaps](https://mem0.ai/blog/state-of-ai-agent-memory-2026)
- [Architecture and Orchestration of Memory Systems in AI Agents](https://www.analyticsvidhya.com/blog/2026/04/memory-systems-in-ai-agents/)
- [A Practical Guide to Memory for Autonomous LLM Agents](https://towardsdatascience.com/a-practical-guide-to-memory-for-autonomous-llm-agents/)
- [Richelieu: Self-Evolving LLM-Based Agents for AI Diplomacy](https://arxiv.org/html/2407.06813v1)
- [A Survey on Large Language Model Based Game Agents](https://arxiv.org/html/2404.02039v2)
- [AriGraph: Learning Knowledge Graph World Models with Episodic Memory for LLM Agents](https://arxiv.org/pdf/2407.04363)
