from __future__ import annotations

import asyncio
from unittest.mock import patch

from ai_agent import reasoner
from ai_agent import skills
from ai_agent.reasoner_context import (
    ReasonerTurnContext,
    install_context,
    reset_context,
)
from ai_agent.schemas import ReasonerEmit


def _line(line_id: str, moves: list[str], root: str = "root") -> dict:
    return {
        "line_id": line_id,
        "moves": moves,
        "move_contexts": [{"kind": "scripted"} for _ in moves],
        "expected_pre_hashes": [f"{root}-{i}" for i in range(len(moves))],
        "root_state_hash": root,
        "legal": True,
        "complete": True,
        "terminal_reason": "end_turn",
        "search_mode": "main",
        "search_state": {"turn": {"points_scored": 1}},
    }


def test_registry_dedupes_sequences_and_namespaces_repeated_engine_ids():
    context = ReasonerTurnContext("g", {}, "root")
    first = context.registry.register(_line("line-1", ["pass", "end turn"]), source="scout")
    duplicate = context.registry.register(
        _line("line-1", ["pass", "end turn"]), source="search-for-1"
    )
    distinct = context.registry.register(
        _line("line-1", ["end turn"]), source="deepen-1"
    )
    assert first is not None and duplicate is not None and distinct is not None
    assert duplicate["line_id"] == first["line_id"]
    assert duplicate["source_lineage"] == ["scout", "search-for-1"]
    assert distinct["line_id"] != first["line_id"]
    assert distinct["line_id"].startswith("deepen-1-line-1-")
    assert context.registry.unique_sequence_count == 2


def test_registry_upgrades_duplicate_frontier_when_complete_line_arrives():
    context = ReasonerTurnContext("g", {}, "root")
    frontier = _line("line-1", ["pass", "end turn"])
    frontier["complete"] = False
    frontier["terminal_reason"] = "node_budget"
    first = context.registry.register(frontier, source="search-for-1")
    completed = context.registry.register(
        _line("line-9", ["pass", "end turn"]), source="deepen-1"
    )
    assert first is not None and completed is not None
    assert completed["line_id"] == first["line_id"]
    assert completed["complete"] is True
    assert completed["terminal_reason"] == "end_turn"


def test_deepen_resolves_canonical_registry_id_and_preserves_metadata():
    context = ReasonerTurnContext("g", {}, "root")
    registered = context.registry.register(
        _line("line-1", ["pass", "end turn"]), source="search-for-1"
    )
    assert registered is not None
    captured = {}

    def fake_search(payload):
        captured.update(payload)
        return {
            "legal": True,
            "candidate_lines": [_line("line-1", ["pass", "end turn"])],
            "search_stats": {},
        }

    token = install_context(context)
    try:
        with patch("ai_agent.engine_client.search", side_effect=fake_search):
            out = skills.deepen(line_id=registered["line_id"])
    finally:
        reset_context(token)
    assert captured["seed_moves"] == ["pass"]
    result = out["candidate_lines"][0]
    assert result["expected_pre_hashes"]
    assert result["move_contexts"]
    assert result["complete"] is True
    assert result["line_id"] == registered["line_id"]


def test_reasoner_context_isolated_across_concurrent_tasks():
    async def read_state(game_id: str) -> tuple[str, str]:
        context = ReasonerTurnContext(
            game_id,
            {"full_state_text": game_id, "legal_moves": [game_id]},
            f"root-{game_id}",
        )
        token = install_context(context)
        try:
            await asyncio.sleep(0)
            return skills.get_full_state(), skills.list_legal_moves()[0]
        finally:
            reset_context(token)

    async def run_both():
        return await asyncio.gather(read_state("game-a"), read_state("game-b"))

    results = asyncio.run(run_both())
    assert results == [("game-a", "game-a"), ("game-b", "game-b")]


def test_reasoner_cache_invalidates_when_root_hash_changes():
    calls = 0

    async def fake_request(**kwargs):
        nonlocal calls
        calls += 1
        return ReasonerEmit(kind="base_search_fallback", confidence="fallback")

    engine = reasoner.Reasoner()

    async def run():
        common = {
            "client": object(),
            "model": "test",
            "game_id": "g",
            "brief_state": {"turn_number": 4},
            "opponent_action_count": 0,
        }
        with patch("ai_agent.reasoner._request_reasoning", side_effect=fake_request):
            _, cached1 = await engine.reason(**common, root_state_hash="root-a")
            _, cached2 = await engine.reason(**common, root_state_hash="root-a")
            _, cached3 = await engine.reason(**common, root_state_hash="root-b")
        return cached1, cached2, cached3

    assert asyncio.run(run()) == (False, True, False)
    assert calls == 2


def test_simulation_evidence_never_enters_commit_registry():
    context = ReasonerTurnContext(
        "g",
        {"legal_moves": ["pass"], "move_simulations": {}},
        "root",
    )
    token = install_context(context)
    try:
        with patch("ai_agent.engine_client.simulate", return_value={
            "legal": True,
            "applied_moves": ["pass"],
            "resolved_if_unanswered": {},
        }):
            result = skills.simulate_move({"action": "pass", "parameters": {}})
    finally:
        reset_context(token)
    assert result["legal"] is True
    assert context.registry.unique_sequence_count == 0
