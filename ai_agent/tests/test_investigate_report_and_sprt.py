from __future__ import annotations

import json
from pathlib import Path

from ai_agent.eval.arena import analyze_pairs, sprt_bernoulli, write_sprt_report
from ai_agent.eval.investigate_report import (
    archive_baseline_stub,
    write_investigation_report,
)
from ai_agent.eval.metrics import compute_profile_metrics
from ai_agent.eval.schemas import EvalCase, TrialResult


def test_archive_baseline_and_report(tmp_path: Path):
    run_dir = archive_baseline_stub(tmp_path, run_id="baseline-test")
    assert (run_dir / "investigation_report.md").exists()
    assert (run_dir / "investigation_metrics.json").exists()
    summary = json.loads((run_dir / "investigation_metrics.json").read_text())
    assert summary["eligible_turns"] >= 20
    assert summary["trials"] >= 24

    # Re-summarize via investigate-report path
    out = write_investigation_report(run_dir)
    assert out.exists()


def test_compute_profile_metrics_includes_investigation_rates():
    case = EvalCase(
        case_id="inv-1",
        title="t",
        summary="s",
        objective="o",
        desired_result="d",
        fixture_path="res://Scripts/Tests/Tcg/fixtures/search_winning_line.json",
        difficulty="easy",
        fidelity_status="authoritative",
    )
    trial = TrialResult(
        case_id="inv-1",
        profile_id="reasoner-investigate-v2",
        metrics={
            "latency_ms": 10,
            "model_calls": 2,
            "prompt_tokens": 100,
            "investigation_exemption": None,
            "novel_investigation": True,
            "local_fork_attempted": True,
            "novel_suffix_found": True,
            "investigation_satisfied": True,
            "failed_search_calls": 0,
            "recovered_failed_searches": 0,
            "score_primary_rationale": False,
            "scout_agreement": False,
            "committed": True,
            "chosen_line_complete": True,
            "reasoner_kind": "line",
        },
    )
    metrics = compute_profile_metrics([trial], {case.case_id: case})
    assert metrics["novel_investigation_rate"] == 1.0
    assert metrics["local_fork_rate"] == 1.0
    assert "investigation" in metrics


def test_sprt_accepts_strong_candidate_and_writes_report(tmp_path: Path):
    decision = sprt_bernoulli(successes=18, n=20, p0=0.5, p1=0.6)
    assert decision["decision"] == "accept_h1"
    weak = sprt_bernoulli(successes=2, n=20, p0=0.5, p1=0.6)
    assert weak["decision"] == "accept_h0"
    cont = sprt_bernoulli(successes=0, n=0)
    assert cont["decision"] == "continue"

    pairs = [
        {
            "pair_id": f"p{i}",
            "seed": i,
            "opponent_id": "mirror",
            "candidate_wins": 2,
            "pair_score": 2,
            "both_finished": True,
        }
        for i in range(20)
    ]
    analysis = analyze_pairs(pairs)
    assert analysis["sprt"]["decision"] == "accept_h1"
    out = write_sprt_report(pairs, tmp_path / "sprt.md")
    assert out.exists()
    assert "accept_h1" in out.read_text()
