"""Opt-in Godot-backed eval tests (skipped when GODOT is unavailable)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from ai_agent.eval.adapters import run_argmax_adapter, run_mock_adapter
from ai_agent.eval.corpus import load_corpus
from ai_agent.eval.godot_host import find_godot, run_godot_oneshot
from ai_agent.eval.grader import grade_trial
from ai_agent.eval.runner import load_profile

REPO = Path(__file__).resolve().parents[2]
POSITIONS = REPO / "Data" / "AI" / "Eval" / "positions"
PROFILES = REPO / "Data" / "AI" / "Eval" / "profiles"

pytestmark = pytest.mark.skipif(
    find_godot() is None,
    reason="Godot binary not found (set GODOT)",
)


def test_godot_search_winning_line_ready_payload():
    payload = run_godot_oneshot(
        fixture="res://Scripts/Tests/Tcg/fixtures/search_winning_line.json",
        mode="search",
        node_budget=80,
        time_budget_ms=1000,
    )
    assert payload["ok"] is True
    assert payload["candidate_count"] > 0
    assert any(
        bool((line.get("resolved_state") or {}).get("wins_game"))
        for line in payload.get("candidate_lines", [])
        if isinstance(line, dict)
    )


def test_argmax_adapter_grades_win_from_seven():
    case = next(c for c in load_corpus(POSITIONS, splits=["blocking"]) if c.case_id == "win-from-seven")
    profile = load_profile(PROFILES / "baseline-argmax.json")
    assert profile.adapter == "argmax"
    trial = run_argmax_adapter(case, profile)
    graded = grade_trial(case, trial)
    assert not trial.error, trial.error
    assert graded.overall_pass, graded.model_dump()
    assert trial.metrics.get("wins_game") is True


def test_argmax_adapter_rejects_stale_root():
    case = next(
        c for c in load_corpus(POSITIONS, splits=["blocking"]) if c.case_id == "stale-root-rejected"
    )
    profile = load_profile(PROFILES / "baseline-argmax.json")
    trial = run_argmax_adapter(case, profile)
    graded = grade_trial(case, trial)
    assert not trial.error, trial.error
    assert graded.overall_pass, graded.model_dump()
    assert trial.metrics.get("stale_root_rejected") is True


@pytest.mark.skipif(
    os.environ.get("RIFTBOUND_EVAL_LIVE_LLM", "").strip().lower()
    not in {"1", "true", "yes", "on"},
    reason="Set RIFTBOUND_EVAL_LIVE_LLM=1 to run live Reasoner eval",
)
def test_reasoner_adapter_live_optional():
    from ai_agent.eval.adapters import run_reasoner_adapter

    case = next(c for c in load_corpus(POSITIONS, splits=["blocking"]) if c.case_id == "win-from-seven")
    profile = load_profile(PROFILES / "reasoner-default.json")
    trial = run_reasoner_adapter(case, profile)
    graded = grade_trial(case, trial, layers=["contract", "validity", "cost"])
    assert not trial.error, trial.error
    assert graded.overall_pass or trial.metrics.get("fallback"), graded.model_dump()
