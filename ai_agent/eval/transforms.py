"""Deterministic metamorphic transforms for eval fixtures / cases."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Callable

from .corpus import fixture_abs_path
from .schemas import EvalCase

TransformFn = Callable[[dict[str, Any]], dict[str, Any]]


def identity(fixture: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(fixture)


def reorder_hand(fixture: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(fixture)
    for player in out.get("players", []):
        hand = player.get("hand")
        if isinstance(hand, list) and len(hand) > 1:
            player["hand"] = list(reversed(hand))
    return out


def reorder_base_units(fixture: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(fixture)
    for player in out.get("players", []):
        base = player.get("base")
        if isinstance(base, list) and len(base) > 1:
            player["base"] = list(reversed(base))
    return out


def swap_battlefield_ids(fixture: dict[str, Any]) -> dict[str, Any]:
    """Swap battlefield definition IDs when both are uncontrolled empty fields."""
    out = copy.deepcopy(fixture)
    bfs = out.get("battlefields")
    control = out.get("battlefield_control", [-1, -1])
    if not isinstance(bfs, list) or len(bfs) < 2:
        return out
    # Only apply when both uncontrolled to preserve strategic meaning.
    if list(control)[:2] != [-1, -1]:
        return out
    out["battlefields"] = [bfs[1], bfs[0]] + list(bfs[2:])
    return out


TRANSFORMS: dict[str, TransformFn] = {
    "identity": identity,
    "reorder_hand": reorder_hand,
    "reorder_base_units": reorder_base_units,
    "swap_battlefield_ids": swap_battlefield_ids,
}


def available_transforms() -> list[str]:
    return sorted(TRANSFORMS)


def apply_transform(name: str, fixture: dict[str, Any]) -> dict[str, Any]:
    fn = TRANSFORMS.get(name)
    if fn is None:
        raise KeyError(f"unknown transform: {name}")
    return fn(fixture)


def load_fixture_dict(case: EvalCase) -> dict[str, Any]:
    path = fixture_abs_path(case.fixture_path)
    return json.loads(path.read_text(encoding="utf-8"))


def materialize_transformed_fixture(
    case: EvalCase,
    transform: str,
    *,
    dest_dir: Path,
) -> Path:
    """Write a transformed fixture JSON and return its path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    fixture = apply_transform(transform, load_fixture_dict(case))
    out = dest_dir / f"{case.case_id}__{transform}.json"
    out.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")
    return out
