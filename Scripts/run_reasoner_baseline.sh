#!/usr/bin/env bash
# Headless Reasoner multi-game baseline runner (SelfPlaySim).
#
# Prerequisites (see Data/AI/Baseline/README.md):
#   - Reasoner agent on port 8765 (RIFTBOUND_REASONER=on, SEARCH_ARGMAX=off,
#     RIFTBOUND_DB_PATH / RIFTBOUND_DATA_ORIGIN set for archival)
#   - Base-argmax agent on port 8766 (RIFTBOUND_REASONER=off, SEARCH_ARGMAX=on)
#   - Both agents must export RIFTBOUND_ENGINE_PORT=8770 so live tools hit
#     Godot's EngineServer (not the argmax uvicorn on 8766)
#   - Godot EngineServer on 8770 (default below) so it does not collide with 8766
#
# Usage (from repo root):
#   ./Scripts/run_reasoner_baseline.sh
#   ./Scripts/run_reasoner_baseline.sh --games 20 --seed 5000 --turn-cap 100
#
# Caller args override defaults. Dual-agent URLs and scoring profiles are always
# applied unless the caller already passed those flags — so `--games 20` still
# runs Reasoner (8765) vs base-argmax (8766), not Reasoner vs Reasoner.
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
	echo "and RIFTBOUND_ENGINE_PORT=8770 so tools reach Godot's EngineServer." >&2
	exit 1
fi
if ! curl -fsS -m 3 "${ARGMAX_URL%/}/health" >/dev/null 2>&1; then
	echo "ERROR: base-argmax agent not reachable at ${ARGMAX_URL%/}/health" >&2
	echo "Start it with RIFTBOUND_SEARCH=on RIFTBOUND_REASONER=off RIFTBOUND_SEARCH_ARGMAX=on" >&2
	echo "and RIFTBOUND_ENGINE_PORT=8770 so tools reach Godot's EngineServer." >&2
	exit 1
fi

_has_flag() {
	local flag="$1"
	shift
	while [ "$#" -gt 0 ]; do
		if [ "$1" = "$flag" ]; then
			return 0
		fi
		shift
	done
	return 1
}

args=("$@")
if ! _has_flag --games "${args[@]+"${args[@]}"}"; then
	args+=(--games 2)
fi
if ! _has_flag --seed "${args[@]+"${args[@]}"}"; then
	args+=(--seed 5000)
fi
if ! _has_flag --turn-cap "${args[@]+"${args[@]}"}"; then
	args+=(--turn-cap 100)
fi
if ! _has_flag --p1-profile "${args[@]+"${args[@]}"}"; then
	args+=(--p1-profile res://Data/AI/scoring_profile.json)
fi
if ! _has_flag --p2-profile "${args[@]+"${args[@]}"}"; then
	args+=(--p2-profile res://Data/AI/scoring_profile.json)
fi
if ! _has_flag --p1-agent-url "${args[@]+"${args[@]}"}"; then
	args+=(--p1-agent-url "$REASONER_URL")
fi
if ! _has_flag --p2-agent-url "${args[@]+"${args[@]}"}"; then
	args+=(--p2-agent-url "$ARGMAX_URL")
fi

exec "$GODOT" --headless --path "$ROOT" --script res://Scripts/Tools/SelfPlaySim.gd -- "${args[@]}"
