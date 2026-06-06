#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GODOT="${GODOT:-/Applications/Godot.app/Contents/MacOS/Godot}"
if ! command -v "$GODOT" >/dev/null 2>&1 && [ ! -x "$GODOT" ]; then
	GODOT="godot"
fi
"$GODOT" --headless --path "$ROOT" --script res://Scripts/Tests/Tcg/TcgTestRunner.gd -- "$@"
