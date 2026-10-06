#!/usr/bin/env bash
# Headless Reasoner multi-game baseline runner (SelfPlaySim).
#
# Prerequisites (see Data/AI/Baseline/README.md):
#   - Reasoner agent on port 8765 (RIFTBOUND_REASONER=on, SEARCH_ARGMAX=off,
#     RIFTBOUND_DB_PATH / RIFTBOUND_DATA_ORIGIN set for archival)
#   - Base-argmax agent on port 8766 (RIFTBOUND_REASONER=off, SEARCH_ARGMAX=on)
#   - Godot EngineServer on 8770 (default below) so it does not collide with 8766
#
# Usage (from repo root):
#   ./Scripts/run_reasoner_baseline.sh
#   ./Scripts/run_reasoner_baseline.sh --games 20 --seed 5000 --turn-cap 100
#
# Extra args are forwarded to SelfPlaySim.gd. With no args, uses the smoke
# defaults from Data/AI/Baseline/README.md (N=2, seed 5000, dual-agent URLs).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GODOT="${GODOT:-/Applications/Godot.app/Contents/MacOS/Godot}"
if ! command -v "$GODOT" >/dev/null 2>&1 && [ ! -x "$GODOT" ]; then
	GODOT="godot"
fi

# Godot-side baseline defaults (only fill unset vars so the operator can override).
export RIFTBOUND_SEARCH="${RIFTBOUND_SEARCH:-on}"
export RIFTBOUND_REASONER="${RIFTBOUND_REASONER:-on}"
export RIFTBOUND_ENGINE_SERVER="${RIFTBOUND_ENGINE_SERVER:-on}"
export RIFTBOUND_ENGINE_PORT="${RIFTBOUND_ENGINE_PORT:-8770}"
export RIFTBOUND_AI_THINK_DELAY="${RIFTBOUND_AI_THINK_DELAY:-0}"
export RIFTBOUND_LOG_INPUTS="${RIFTBOUND_LOG_INPUTS:-1}"

REASONER_URL="${RIFTBOUND_REASONER_AGENT_URL:-http://localhost:8765}"
ARGMAX_URL="${RIFTBOUND_ARGMAX_AGENT_URL:-http://localhost:8766}"

if ! curl -fsS -m 3 "${REASONER_URL%/}/health" >/dev/null 2>&1; then
	echo "ERROR: Reasoner agent not reachable at ${REASONER_URL%/}/health" >&2
	echo "Start it with RIFTBOUND_SEARCH=on RIFTBOUND_REASONER=on RIFTBOUND_SEARCH_ARGMAX=off" >&2
	exit 1
fi
if ! curl -fsS -m 3 "${ARGMAX_URL%/}/health" >/dev/null 2>&1; then
	echo "ERROR: base-argmax agent not reachable at ${ARGMAX_URL%/}/health" >&2
	echo "Start it with RIFTBOUND_SEARCH=on RIFTBOUND_REASONER=off RIFTBOUND_SEARCH_ARGMAX=on" >&2
	exit 1
fi

if [ "$#" -eq 0 ]; then
	set -- \
		--games 2 \
		--seed 5000 \
		--turn-cap 100 \
		--p1-profile res://Data/AI/scoring_profile.json \
		--p2-profile res://Data/AI/scoring_profile.json \
		--p1-agent-url "$REASONER_URL" \
		--p2-agent-url "$ARGMAX_URL"
fi

exec "$GODOT" --headless --path "$ROOT" --script res://Scripts/Tools/SelfPlaySim.gd -- "$@"
