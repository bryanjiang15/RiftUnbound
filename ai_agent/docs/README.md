# AI Agent Docs Index

Status: living navigation guide for the Python AI service and its Godot search
integration.

Start with `../README.md` for setup, environment variables, endpoints, and the
current runtime architecture. This folder keeps the deeper design notes and
subsystem references.

## Current implementation references

| Doc | Use it for |
|---|---|
| `Goal_Oriented_Strategist.md` | `RIFTBOUND_GOALS`: the `/goals` pre-search handshake, per-turn `GoalSet`, compiler guardrails, engine overlay, scout search, and debugging logs. |
| `Scoring_Features_Reference.md` | The registry-driven linear evaluation used by `TurnSearch`, including how to add a scored feature and regenerate `Data/AI/feature_registry.json`. |
| `Score_Tuning_And_Evolution.md` | How captured search data is used to propose/tune weights; implemented Texel pieces vs. future CMA-ES/SPRT/feature-invention work. |
| `Statistical_Analysis_Storage.md` | SQLite capture schema for decisions, candidate lines, snapshots, weight versions, and card events. Some sections are still roadmap notes; check the status callouts. |
| `Card_Statistics_Reference.md` | Per-card event reporting and aggregation caveats. |
| `../prompts/README.md` | Static Markdown prompt modules and the Python loaders that consume them. |

## Phase and roadmap docs

These are useful for intent and tradeoffs, but some are older than the current
runtime. Prefer the implementation references above when they conflict.

| Doc | Status |
|---|---|
| `Agent_design_and_memory.md` | Baseline service/memory design, with a current-implementation note for search, prompts, and goals. |
| `Phase1_STM_Improvements.md` | Short-term memory improvements. |
| `Phase2_Decision_Infrastructure.md` | Staged Router -> Planner -> Actor -> Validator pipeline; now implemented behind `RIFTBOUND_PIPELINE=staged`. |
| `Phase2_5_Engine_Truth_Simulation.md` | Engine-truth simulation design for helper skills. |
| `Memory_Roadmap.md` | Cross-game memory roadmap; not the current SQLite tuning dataset. |
| `LLM_Data_Analysis_Loop.md` | Future analysis loop around captured games and tuning outputs. |

## Source map

- Godot search and scoring: `Scripts/Game/TurnSearch.gd`,
  `Scripts/Game/ScoreModel.gd`, `Scripts/Game/ScoringProfile.gd`,
  `Scripts/Game/FeatureRegistry.gd`.
- Godot AI bridge: `Scripts/AI/AIPlayer.gd`.
- Python service: `ai_agent/main.py`, `ai_agent/agent.py`.
- Staged and goal components: `ai_agent/router.py`, `ai_agent/planner.py`,
  `ai_agent/strategist.py`, `ai_agent/goal_compiler.py`.
- Capture/tuning: `ai_agent/capture.py`, `ai_agent/memory.py`,
  `ai_agent/texel_tune.py`, `ai_agent/feature_report.py`.
