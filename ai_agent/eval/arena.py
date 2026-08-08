"""Paired opponent-panel arena helpers.

SelfPlaySim extensions emit machine-readable game JSON; this module aggregates
pair-level results and persists them. Sequential SPRT gating is intentionally
deferred until pilot variance is measured.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .schemas import ArenaManifest
from .store import EvalStore


def load_arena_manifest(path: Path | str) -> ArenaManifest:
    return ArenaManifest.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def expand_pairs(manifest: ArenaManifest) -> list[dict[str, Any]]:
    """Expand opponent panel × seeds into ordered pair legs A/B."""
    jobs: list[dict[str, Any]] = []
    for opponent in manifest.opponents:
        for offset in range(manifest.num_pairs):
            seed = manifest.seed_base + offset
            pair_id = f"{manifest.run_id}-pair-{opponent.opponent_id}-{seed}"
            # Leg A: candidate seat 0, first player 0
            jobs.append(
                {
                    "pair_id": pair_id,
                    "pair_leg": "a",
                    "seed": seed,
                    "opponent_id": opponent.opponent_id,
                    "candidate_seat": 0,
                    "first_player_index": 0,
                    "candidate_profile": manifest.candidate_profile,
                    "opponent_profile": opponent.profile_path,
                    "candidate_deck": manifest.candidate_deck,
                    "opponent_deck": opponent.deck_path,
                    "p1_profile": manifest.candidate_profile,
                    "p2_profile": opponent.profile_path,
                    "p1_deck": manifest.candidate_deck,
                    "p2_deck": opponent.deck_path,
                }
            )
            # Leg B: swap seats and first player
            jobs.append(
                {
                    "pair_id": pair_id,
                    "pair_leg": "b",
                    "seed": seed,
                    "opponent_id": opponent.opponent_id,
                    "candidate_seat": 1,
                    "first_player_index": 1,
                    "candidate_profile": manifest.candidate_profile,
                    "opponent_profile": opponent.profile_path,
                    "candidate_deck": manifest.candidate_deck,
                    "opponent_deck": opponent.deck_path,
                    "p1_profile": opponent.profile_path,
                    "p2_profile": manifest.candidate_profile,
                    "p1_deck": opponent.deck_path,
                    "p2_deck": manifest.candidate_deck,
                }
            )
    return jobs


def pair_score(candidate_wins: int) -> int:
    """Map 0..2 candidate wins across a pair to -2..+2."""
    if candidate_wins <= 0:
        return -2
    if candidate_wins == 1:
        return 0
    return 2


def aggregate_pair(leg_a: dict[str, Any], leg_b: dict[str, Any]) -> dict[str, Any]:
    wins = int(bool(leg_a.get("candidate_won"))) + int(bool(leg_b.get("candidate_won")))
    both = bool(leg_a.get("finished")) and bool(leg_b.get("finished"))
    return {
        "pair_id": leg_a["pair_id"],
        "seed": leg_a["seed"],
        "opponent_id": leg_a["opponent_id"],
        "candidate_wins": wins,
        "pair_score": pair_score(wins) if both else 0,
        "both_finished": both,
    }


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return ((centre - margin) / denom, (centre + margin) / denom)


def analyze_pairs(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    finished = [p for p in pairs if p.get("both_finished")]
    # Treat a pair as a candidate win when candidate_wins == 2; split = 0 contribution
    # to Bernoulli "won the pair" rate. Report mean pair score separately.
    strict_wins = sum(1 for p in finished if int(p.get("candidate_wins", 0)) == 2)
    mean_score = (
        sum(int(p.get("pair_score", 0)) for p in finished) / len(finished) if finished else 0.0
    )
    low, high = wilson_interval(strict_wins, len(finished)) if finished else (0.0, 0.0)
    by_opponent: dict[str, dict[str, Any]] = {}
    for pair in finished:
        oid = pair["opponent_id"]
        bucket = by_opponent.setdefault(oid, {"n": 0, "strict_wins": 0, "scores": []})
        bucket["n"] += 1
        bucket["scores"].append(int(pair.get("pair_score", 0)))
        if int(pair.get("candidate_wins", 0)) == 2:
            bucket["strict_wins"] += 1
    return {
        "pairs": len(pairs),
        "finished_pairs": len(finished),
        "strict_pair_wins": strict_wins,
        "mean_pair_score": mean_score,
        "wilson95": {"low": low, "high": high},
        "by_opponent": by_opponent,
        "note": "SPRT/GSPRT deferred until pilot variance is measured.",
    }


def persist_arena_results(
    store: EvalStore,
    run_id: str,
    games: list[dict[str, Any]],
    pairs: list[dict[str, Any]],
) -> None:
    for game in games:
        store.record_arena_game(run_id, game)
    for pair in pairs:
        store.record_arena_pair(run_id, pair)
