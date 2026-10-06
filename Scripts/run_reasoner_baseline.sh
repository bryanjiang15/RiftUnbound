#!/usr/bin/env bash
# Headless Reasoner multi-game baseline runner (SelfPlaySim).
#
# Prerequisites: agent service already up on RIFTBOUND_AGENT_PORT (default 8765)
# with RIFTBOUND_SEARCH=on RIFTBOUND_REASONER=on RIFTBOUND_SEARCH_ARGMAX=off
# and RIFTBOUND_DB_PATH / RIFTBOUND_DATA_ORIGIN set for archival.
#
# Usage (from repo root):
#   ./Scripts/run_reasoner_baseline.sh
#   ./Scripts/run_reasoner_baseline.sh --games 20 --seed 5000 --turn-cap 100
#
# Extra args are forwarded to SelfPlaySim.gd. With no args, uses the smoke
# defaults from Data/AI/Baseline/README.md (N=2, seed 5000, turn-cap 100).
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
export RIFTBOUND_ENGINE_PORT="${RIFTBOUND_ENGINE_PORT:-8766}"
export RIFTBOUND_AI_THINK_DELAY="${RIFTBOUND_AI_THINK_DELAY:-0}"
export RIFTBOUND_LOG_INPUTS="${RIFTBOUND_LOG_INPUTS:-1}"

AGENT_PORT="${RIFTBOUND_AGENT_PORT:-8765}"
if ! curl -fsS -m 3 "http://localhost:${AGENT_PORT}/health" >/dev/null 2>&1; then
	echo "ERROR: agent server not reachable at http://localhost:${AGENT_PORT}/health" >&2
	echo "Start it with RIFTBOUND_SEARCH=on RIFTBOUND_REASONER=on RIFTBOUND_SEARCH_ARGMAX=off" >&2
	exit 1
fi

if [ "$#" -eq 0 ]; then
	set -- \
		--games 2 \
		--seed 5000 \
		--turn-cap 100 \
		--p1-profile res://Data/AI/scoring_profile.json \
		--p2-profile res://Data/AI/scoring_profile.json
fi

exec "$GODOT" --headless --path "$ROOT" --script res://Scripts/Tools/SelfPlaySim.gd -- "$@"
