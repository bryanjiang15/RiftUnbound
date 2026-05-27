# Riftbound AI Agent System Plan

A design document for a Python based reasoning agent that plays the Riftbound TCG against or alongside a Godot game simulation.

---

## 1. Purpose and scope

This document specifies the AI agent that plays Riftbound inside a Godot simulation. The agent observes a summarized game state, reasons about the situation, optionally requests more detail or performs lookups through skills, and returns a single decision consisting of a chosen action plus a written justification for that action.

The agent is an oracle, not an authority. Godot owns the rules engine, the full game state, and the final say on legality. The agent only proposes moves. Every proposed move is validated by Godot before it takes effect, and an illegal move is returned to the agent as a structured error to retry from.

This plan covers what the agent does, the context it receives, the skills it can call, the memory it keeps, the structure of its output, the control loop it lives in, and how its reasoning is captured for debugging.

---

## 2. System overview

The agent runs as a separate Python process from the Godot game. Godot drives the loop: when the game reaches a decision point for the AI player, Godot sends a brief state to the Python agent service and waits asynchronously for a decision in return. The agent never touches Godot internals; it sees only JSON views and acts only through declared skills.

The high level flow for a single decision:

1. Godot reaches an AI decision point and serializes a brief game state.
2. Godot sends the brief state to the Python agent service.
3. The agent loads its system instruction, relevant memory, and the brief state into context.
4. The agent reasons. It may call read skills to pull more detailed state or look up a rule. It may call helper skills to compute legal options.
5. The agent emits a final structured decision: a reasoning field and a move.
6. The Python service returns the decision to Godot.
7. Godot validates the move against its rules engine.
8. If legal, Godot applies it and the loop continues. If illegal, Godot returns a structured rejection and the agent retries from step 4 with the error in context.
9. The decision, its reasoning, and the resulting outcome are written to persistent memory.

```
+-----------+        brief state         +---------------------+
|           |  ------------------------> |                     |
|  Godot    |                            |  Python agent       |
|  (engine, |   skill calls (read /      |  (reasoning loop,   |
|  rules,   |   helper) <--------------> |  tools, memory)     |
|  truth)   |                            |                     |
|           |  <------------------------ |                     |
+-----------+   decision (reason + move) +---------------------+
       |                                          |
       |  validate move                           |  append to
       v                                          v
  legal? apply / reject                     persistent memory
```

---

## 3. What the agent does

The agent has one job: given the current situation, choose the best legal action for the AI player and explain why.

Concretely, on each invocation the agent:

- Reads the brief game state and identifies the current decision type (for example: main phase action, responding to an opponent action, combat decision, mulligan, target selection).
- Recalls relevant prior context from memory (what has happened this game, what the opponent has been doing, what its own plan was).
- Decides whether the brief state is sufficient. If not, it calls read skills to pull the specific detail it needs rather than asking for the entire game state every time.
- Optionally consults the rules skill when it encounters an interaction it is unsure about.
- Optionally calls a helper skill to enumerate legal moves or simulate a simple outcome.
- Produces exactly one decision: a structured object containing its reasoning and its chosen move.

The agent does not manage the game loop, enforce rules, track the authoritative state, or decide when it is its turn. Godot does all of that.

---

## 4. Context the agent receives

Context is split into four layers. Keep the stable, large material out of the per turn payload and make it reachable through skills instead. This keeps each turn cheap and keeps model attention focused.

### 4.1 System instruction (stable, set once per session)

The system instruction defines the agent's identity and contains:

- **Goal.** Win the game of Riftbound by reducing the opponent to a losing condition while protecting your own. Play to win, not to stall. Prefer lines that improve your position even under uncertainty.
- **Role and boundaries.** You are a player agent. You propose one legal move at a time. You do not control the rules engine. If a move is rejected as illegal, read the rejection and propose a different legal move.
- **High frequency rules.** A concise summary of the rules that come up almost every turn: turn structure and phases, resource and energy mechanics, how units and battlefields work, combat resolution at a high level, the win and loss conditions, and the priority and timing model. This is the subset the agent should not need to look up. The full ruleset lives behind a skill.
- **Output contract.** The exact required output shape (see Section 7). The agent must always return a reasoning string and a move object, and nothing else.
- **Behavioral guidance.** Be decisive. State assumptions explicitly. When uncertain about a rules interaction, call the rules skill rather than guessing. Keep reasoning concise and focused on the decision at hand.

The full Riftbound Core Rules document is versioned and updated with every set release. Treat the rules text as data loaded behind a skill, not as a constant baked into the prompt. Version it so you can reproduce why the agent made a decision under a given ruleset.

### 4.2 Brief game state (per decision, supplied by Godot)

A compact JSON projection that is enough for most decisions without a follow up lookup. It should include:

- Whose turn it is, the current phase or step, and the decision type being asked of the agent.
- The agent's resources and energy available.
- The agent's hand size and, for the agent's own hand, the cards in it.
- A summary of the board: the agent's units and the opponent's units with key stats, and the state of contested battlefields or objectives.
- Score or victory progress for both sides.
- The opponent's visible public information (resources, board, known effects) without hidden information the agent should not have.
- A short list of the legal action categories available right now, if Godot can cheaply provide it. This anchors the agent and reduces illegal proposals.

The brief state must never leak hidden information the AI player is not entitled to. The agent should only ever see what a fair player in that seat would see.

### 4.3 Memory (per decision, supplied by the agent service)

A summarized or recent slice of the persistent memory described in Section 6, injected into context so the agent has continuity within the game.

### 4.4 Detailed state (on demand, via skills)

Anything not in the brief state is reachable by calling a read skill. The agent pulls only the slice it needs.

---

## 5. Skills

Skills are the agent's only means of getting more information or affecting the world. They divide into three groups. All skill calls go to the Python service, which routes read and helper skills locally or to Godot as needed; action skills are realized as the agent's final move and validated by Godot.

### 5.1 Read skills (pull more detailed state)

These never change game state. They answer questions.

| Skill | Purpose | Example input | Returns |
|---|---|---|---|
| `get_full_state` | Full authorized game state snapshot | none | Complete JSON state visible to this seat |
| `get_zone` | Detail on one zone | zone id (e.g. a battlefield, a unit's attachments) | Detailed contents of that zone |
| `get_card_detail` | Full text and current modified stats of a card | card instance id | Card text, base and current stats, status effects |
| `get_opponent_history` | What the opponent has done this game | optional turn range | Ordered list of opponent actions observed |
| `lookup_rule` | Query the versioned ruleset | a topic or keyword | The relevant rules text passage and version |

`lookup_rule` is the rules skill. The agent calls it when it hits an interaction it is unsure about instead of guessing. It returns text from the versioned Core Rules so the answer is reproducible.

### 5.2 Helper skills (compute, do not mutate)

These help the agent reason without committing to anything.

| Skill | Purpose | Returns |
|---|---|---|
| `list_legal_moves` | Enumerate currently legal moves for this decision | A structured list of legal move options |
| `simulate_move` | Apply a hypothetical move to a copy of the state and report the result | Resulting state summary, no real effect |
| `evaluate_position` | Return a heuristic score of the current or a hypothetical position | A numeric or structured assessment |

`list_legal_moves` is the most important helper. Calling it before deciding sharply reduces illegal proposals and gives the agent a concrete option set to reason over. `simulate_move` lets the agent check a line one ply deep without risk.

### 5.3 Action skills (the agent's move)

The agent does not call these mid reasoning. Instead, the agent's final decision names one action and its parameters. The Python service hands that move to Godot, which validates and applies it. Common action shapes to support:

| Action | Parameters | Notes |
|---|---|---|
| `play_card` | card id, targets, payment | Play a card from hand |
| `activate_ability` | source id, ability id, targets | Use an ability |
| `move_unit` | unit id, destination | Reposition a unit |
| `declare_attack` | attacker ids, target | Commit to combat |
| `declare_block` | blocker assignments | Respond in combat |
| `pass_priority` | none | Decline to act |
| `mulligan_decision` | keep or mulligan, cards | Opening hand decision |
| `choose_target` | chosen target ids | Resolve a required choice |
| `concede` | none | Reserved; only under explicit policy |

Keep action skills small and common. Rare or complex sequences are expressed as a sequence of these atomic moves across multiple decision points, not as one giant action.

### 5.4 Skill design rules

- Read and helper skills are free of side effects. Only the validated final move changes the game.
- Every action is validated by Godot. The agent is never trusted to produce only legal moves.
- An illegal move returns a structured error: which move was attempted, why it was rejected, and, where possible, the legal alternatives. The agent retries from this.
- Skill schemas are versioned alongside the state and action schemas. The contract between Godot and Python is one JSON schema for state and one for actions; pin it down early.

---

## 6. Persistent memory

Separate two kinds of memory. Conflating them leads to overcomplicated storage.

### 6.1 Episodic game history (within a game)

An append only, typed event log of everything that happened this game: each decision, the reasoning behind it, the move chosen, whether it was accepted, and the resulting state change or opponent response. This does not need a vector database. A structured list serialized to SQLite (or JSON per game) is simpler, fully inspectable, and replayable.

Each turn, a summarized or recent slice of this log is injected into context so the agent has continuity: what its plan was, what the opponent has been doing, what worked and what did not.

Suggested event record fields:

- `game_id`, `turn`, `decision_index`
- `decision_type`
- `brief_state_digest` (a hash or compact form of what the agent saw)
- `reasoning` (the agent's written justification)
- `move` (the structured action it chose)
- `accepted` (boolean) and `rejection_reason` (if any)
- `outcome` (resulting state summary or opponent reply)
- `timestamp`

### 6.2 Cross game knowledge (across games)

Optional and added later. Strategies that worked, recurring opponent tendencies, openings that performed well. Only this kind of memory benefits from similarity retrieval. Even then, start with SQLite plus a vector extension (such as sqlite-vec) or a lightweight store before reaching for anything heavier. Do not build this until the within game agent is solid.

### 6.3 Memory hygiene

- The agent's reasoning is stored as data next to the move and the game state, in one place, replayable and diffable across games.
- Never store anything the AI seat should not know. Memory is scoped to one seat's fair view.
- Keep injected memory bounded. Summarize old turns rather than feeding the full log every decision.

---

## 7. Output contract: reasoning plus move

This is a hard requirement. Every decision the agent returns must contain both a reasoning explanation and a single move. The agent returns nothing else.

Make the reasoning an explicit output field, not a reliance on the model's hidden internal chain of thought. An explicit justification field is reproducible, lives next to the game state, is diffable across games, and does not depend on model internals or SDK plumbing that may not surface cleanly.

### 7.1 Required output schema

```json
{
  "reasoning": "string. A concise explanation of why this move was chosen: the situation as the agent reads it, the options considered, the expected outcome, and any assumptions or uncertainty.",
  "move": {
    "action": "one of the action skill names, e.g. play_card",
    "parameters": {
      "...": "action specific parameters"
    }
  },
  "confidence": "optional. A qualitative or numeric self assessment.",
  "alternatives_considered": "optional. A short list of other moves weighed and why they were rejected."
}
```

`reasoning` and `move` are mandatory. `confidence` and `alternatives_considered` are optional but recommended; they make post game review far easier and cost little.

### 7.2 Output rules

- Exactly one move per decision. Multi step plans are realized across multiple decision points.
- The reasoning must justify the specific move returned, not describe the game in general.
- If the agent is uncertain, it still commits to one move and states the uncertainty in the reasoning rather than refusing or returning nothing.
- On a rejected move, the retry must produce a new move and reasoning that accounts for the rejection.

---

## 8. Control loop

The loop the Python service runs per decision request from Godot:

1. Receive brief state and decision type from Godot.
2. Assemble context: system instruction, memory slice, brief state.
3. Enter the reasoning loop:
   - Call the model.
   - If the model requests a read or helper skill, execute it, append the result to context, and loop.
   - If the model emits a final decision, validate that it matches the output schema. If malformed, return a schema error to the model and loop.
4. Send the validated move to Godot.
5. Godot validates legality.
   - If legal: Godot applies it. Record accepted decision and outcome in memory. Return control.
   - If illegal: append the structured rejection to context and re enter the reasoning loop. Bound retries (for example, three attempts) before falling back to a safe default such as `pass_priority` and flagging the failure.
6. Append the final decision, reasoning, acceptance, and outcome to episodic memory.

Bounding retries matters. An agent that cannot find a legal move after a few tries should fall back to a safe legal action and the failure should be logged loudly for review, not loop forever.

---

## 9. Reasoning capture and observability

Two distinct things are worth capturing, and they answer different questions.

**The agent's workflow.** Which skills it called, in what order, with what inputs and outputs, and what the model said at each step. This is what you want when the agent makes a bad play and you need to see what it saw and what it called. Capture this with a tracing layer. Group all decisions in one game under a single trace keyed by game id so a full match replays as one linked story rather than scattered, disconnected runs. Write spans into the same store as the episodic event log so the decision trace and the game state sit side by side.

**The strategic reasoning.** Why it chose the move. This is the explicit `reasoning` field in the output contract, stored next to the move and the resulting state. This is the higher signal artifact for a game agent and it does not depend on capturing model internals. Do not architect around verbatim model chain of thought; if a reasoning model summary is available it is only a summary, useful as a hint, not as ground truth.

Together: tracing for the mechanical "what did it do," the explicit reasoning field for the strategic "why did it do that." When the agent loses a game, you want to scan the per turn reasoning to find the turn where the plan went wrong, then drop into the trace for that turn to see exactly what it saw and called.

---

## 10. Recommended tech stack

- **Game engine:** Godot 4.x with GDScript. Owns the simulation, the rules engine, and the authoritative state. Exposes one deterministic full state serializer and one brief state projection.
- **Transport:** Godot drives. Godot calls a local Python HTTP service (or websocket) at each AI decision point and waits asynchronously with a loading state in the UI. Godot calling out is correct because the game is the source of truth and the legality authority; the agent is an oracle it consults.
- **Agent service:** A thin Python service (FastAPI is a natural fit: async, gives you the decision endpoint plus the read and helper skill endpoints cleanly).
- **Agent core:** The model provider SDK plus your own orchestration loop. For a single agent with a small fixed tool set and a turn based control flow you already understand, a heavy multi agent framework adds abstraction that gets in the way of debugging strategic mistakes. Own the roughly one hundred fifty line loop. Adopt a framework later only if you genuinely need branching multi step planning graphs.
- **Memory:** Append only typed event log in process, serialized to SQLite or JSON per game. Add a vector store only if and when you build cross game knowledge.
- **Rules:** The versioned Core Rules text loaded as data behind the `lookup_rule` skill, not baked into the prompt. Pin the version per game for reproducibility.
- **Schemas:** One JSON schema for state, one for actions, one for the decision output. Version all three. Most painful integration bugs trace back to this boundary drifting, so pin it early.

---

## 11. Build order

A suggested sequence so each layer is testable before the next:

1. Define and freeze the three schemas: brief state, action, decision output.
2. Build Godot's full and brief state serializers and the legality validator with structured rejections.
3. Stand up the Python service with a stub agent that returns a fixed legal move, to prove the Godot to Python round trip.
4. Implement the read and helper skills, especially `list_legal_moves`, against the schema.
5. Implement the real agent reasoning loop with the output contract enforced.
6. Add episodic memory and the per game trace grouping.
7. Tune the system instruction: move rules that come up every turn into it, leave the rest behind `lookup_rule`.
8. Only after the within game agent is solid, consider cross game knowledge.

---

## 12. Key invariants

These should hold no matter what:

- The agent never sees hidden information its seat is not entitled to.
- The agent never mutates game state directly; only a Godot validated move changes the game.
- Every decision returns both reasoning and exactly one move, always conforming to the output schema.
- Every illegal move produces a structured, machine readable rejection the agent can act on.
- Retries are bounded and failures fall back to a safe legal action and are logged.
- Reasoning is stored as explicit data next to the move and outcome, not left implicit in model internals.
- State, action, and decision schemas are versioned, and the ruleset version is pinned per game.

---

## 13. Implemented rule constraints and deferred features

This section tracks rules that have been deliberately simplified or deferred in the current implementation. It exists so design decisions are explicit rather than accidental, and so future implementors know where to re-open the work.

### 13.1 Unit placement — Ambush keyword (deferred)

**Rule:** Units are played from hand to the player's **base**. Direct deployment onto a Battlefield normally requires the **Ambush** keyword.

**Current implementation:** The Ambush keyword is not yet implemented. The `play` command enforces that any unit played with a `to battlefield-*` destination is immediately rejected with an error. Units must always be played to base, then repositioned via the `move` command.

**Implication for the agent:** `play_card` actions for units must omit `destination` or set it to `base`. The only way to get a unit onto a Battlefield is a subsequent `move_unit` action on the unit once it is ready.

**When to revisit:** Implement Ambush as a keyword effect that overrides the base-only placement restriction. At that point, remove the destination guard in `_cmd_play` and add a keyword check in `_place_unit` instead.