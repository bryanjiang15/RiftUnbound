"""Shared helpers for same-turn CF and multi-turn outcome rollouts."""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Optional

from . import predicate_packs as packs


def json_load(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return None


def leaf_hash(line: dict) -> str:
    state = line.get("search_state") or line.get("resolved_state") or line.get("checkpoint") or {}
    blob = json.dumps(state, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def write_temp_json(obj: Any, suffix: str = ".json") -> Path:
    tmp = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8")
    json.dump(obj, tmp, default=str)
    tmp.close()
    return Path(tmp.name)


def normalize_engine_lines(payload: dict) -> list[dict[str, Any]]:
    lines = payload.get("candidate_lines") or payload.get("lines") or payload.get("principal_variations") or []
    out: list[dict[str, Any]] = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        moves = line.get("moves") or []
        out.append({
            "line_id": line.get("line_id"),
            "score": line.get("score", 0.0),
            "moves": moves,
            "canonical_moves": packs.canonical_moves(moves),
            "breakdown": line.get("breakdown") or line.get("score_breakdown") or {},
            "features": line.get("features") or {},
            "resolved_state": line.get("resolved_state") or {},
            "search_state": line.get("search_state") or {},
            "complete": bool(line.get("complete", False)),
            "terminal_reason": line.get("terminal_reason", ""),
            "leaf_hash": leaf_hash(line),
            "path_segments": line.get("path_segments") or [],
            "root_line_id": line.get("root_line_id"),
            "source": line.get("source"),
            "checkpoint": line.get("checkpoint") or {},
            "depth_player_turns": line.get("depth_player_turns"),
        })
    return out


def first_strategic_move(moves: Any) -> str:
    for raw in packs.canonical_moves(moves):
        cmd = str(raw).strip().lower()
        if cmd in ("", "pass", "end turn", "end_turn"):
            continue
        if cmd.startswith("choose "):
            continue
        return cmd
    return ""


def diversify_roots(
    *,
    played: Optional[dict],
    original: list[dict],
    offline: Optional[list[dict]] = None,
    root_alt_cap: int = 4,
) -> list[dict[str, Any]]:
    """Played + up to root_alt_cap distinct alternatives.

    Prefer distinct first strategic actions, then fill with full-line-distinct.
    """
    roots: list[dict[str, Any]] = []
    seen_full: set[str] = set()
    seen_first: set[str] = set()

    def _add(line: Optional[dict], source: str, *, is_played: bool = False) -> None:
        if not line:
            return
        moves = packs.canonical_moves(line.get("moves") or line.get("canonical_moves"))
        if not moves and not is_played:
            return
        full_key = "|".join(moves)
        first = first_strategic_move(moves)
        if full_key in seen_full:
            return
        if not is_played and len(roots) > 1 and first and first in seen_first:
            # Defer duplicates-of-first; may fill later if capacity remains.
            return
        seen_full.add(full_key)
        if first:
            seen_first.add(first)
        roots.append({
            "line_id": str(line.get("line_id") or ("played" if is_played else f"{source}-{len(roots)}")),
            "moves": moves,
            "source": "played" if is_played else source,
            "score": line.get("score"),
            "is_played": is_played,
        })

    _add(played, "played", is_played=True)

    # Fresh offline search first so analysis is not limited to lines the live
    # AI happened to keep. Live candidates fill remaining distinct firsts.
    deferred: list[tuple[dict, str]] = []
    for src_name, pool in (("offline", offline or []), ("original", original or [])):
        for line in pool:
            if played and packs.canonical_moves(line.get("moves")) == packs.canonical_moves(played.get("moves")):
                continue
            first = first_strategic_move(line.get("moves"))
            full_key = "|".join(packs.canonical_moves(line.get("moves")))
            if full_key in seen_full:
                continue
            if first and first in seen_first:
                deferred.append((line, src_name))
                continue
            if len([r for r in roots if not r.get("is_played")]) >= root_alt_cap:
                break
            _add(line, src_name)
        if len([r for r in roots if not r.get("is_played")]) >= root_alt_cap:
            break

    # Pass 2: fill with full-line-distinct deferred / remaining.
    if len([r for r in roots if not r.get("is_played")]) < root_alt_cap:
        for line, src_name in deferred:
            if len([r for r in roots if not r.get("is_played")]) >= root_alt_cap:
                break
            # Force-add ignoring first-action uniqueness.
            moves = packs.canonical_moves(line.get("moves"))
            full_key = "|".join(moves)
            if full_key in seen_full:
                continue
            seen_full.add(full_key)
            roots.append({
                "line_id": str(line.get("line_id") or f"{src_name}-{len(roots)}"),
                "moves": moves,
                "source": src_name,
                "score": line.get("score"),
                "is_played": False,
            })

    return roots
