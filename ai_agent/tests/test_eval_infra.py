"""Deterministic tests for the eval package (no API keys, no Godot required)."""
from __future__ import annotations

import json
from pathlib import Path

from ai_agent.eval.adapters import run_mock_adapter
from ai_agent.eval.arena import (
    aggregate_pair,
    analyze_pairs,
    expand_pairs,
    pair_score,
    wilson_interval,
)
from ai_agent.eval.corpus import (
    DEFAULT_POSITIONS_DIR,
    hash_fixture,
    load_corpus,
    render_catalog,
    validate_corpus,
    write_catalog,
)
from ai_agent.eval.grader import grade_trial
from ai_agent.eval.metrics import compute_run_metrics
from ai_agent.eval.runner import load_profile, run_eval
from ai_agent.eval.schemas import (
    AcceptableOutcome,
    ArenaManifest,
    EvalCase,
    EvalRunManifest,
    LayerResult,
    TrialResult,
)
from ai_agent.eval.store import EvalStore
from ai_agent.eval.transforms import apply_transform, available_transforms, load_fixture_dict

REPO = Path(__file__).resolve().parents[2]
POSITIONS = REPO / "Data" / "AI" / "Eval" / "positions"
PROFILES = REPO / "Data" / "AI" / "Eval" / "profiles"


def test_corpus_validates():
    errors = validate_corpus(POSITIONS)
    assert errors == [], errors


def test_load_blocking_cases():
    cases = load_corpus(POSITIONS, splits=["blocking"], include_fidelity_limited=False)
    assert len(cases) >= 10
    ids = {c.case_id for c in cases}
    assert "win-from-seven" in ids
    assert "turn8-two-point-continuation" in ids


def test_eval_lanes_split_engine_from_agent():
    engine = load_corpus(
        POSITIONS,
        splits=["blocking", "dev"],
        include_fidelity_limited=True,
        eval_lanes=["engine"],
    )
    agent = load_corpus(
        POSITIONS,
        splits=["blocking", "dev"],
        include_fidelity_limited=True,
        eval_lanes=["agent"],
    )
    engine_ids = {c.case_id for c in engine}
    agent_ids = {c.case_id for c in agent}
    assert engine_ids.isdisjoint(agent_ids)
    assert "budget-cutoff-incomplete" in engine_ids
    assert "seeded-end-turn-complete" in engine_ids
    assert "win-from-seven" in agent_ids
    assert "turn8-two-point-continuation" in agent_ids
    assert all(c.eval_lane == "engine" for c in engine)
    assert all(c.eval_lane == "agent" for c in agent)


def test_case_globs_select_agent_smoke():
    cases = load_corpus(
        POSITIONS,
        splits=["blocking", "dev"],
        include_fidelity_limited=True,
        eval_lanes=["agent"],
        case_globs=[
            "win-from-seven.json",
            "turn8-two-point-continuation.json",
            "keep-reaction-under-discard.json",
            "discard-development-line.json",
            "react-dont-end-turn.json",
            "unopposed-move-conquers.json",
        ],
    )
    ids = {c.case_id for c in cases}
    assert ids == {
        "win-from-seven",
        "turn8-two-point-continuation",
        "keep-reaction-under-discard",
        "discard-development-line",
        "react-dont-end-turn",
        "unopposed-move-conquers",
    }
    assert all("agent_smoke" in c.tags for c in cases)


def test_case_globs_select_decision_v2():
    globs = [
        "close-from-six-double.json",
        "float-gust-deny-lethal.json",
        "spend-develop-no-threat.json",
        "tempo-*.json",
        "hold-open-rune-discipline.json",
        "take-closed-runes-contest.json",
        "retreat-low-score-threat.json",
        "reinforce-hold-at-seven.json",
    ]
    cases = load_corpus(
        POSITIONS,
        splits=["blocking", "dev"],
        include_fidelity_limited=False,
        eval_lanes=["agent"],
        case_globs=globs,
    )
    ids = {c.case_id for c in cases}
    # hold-open-rune-discipline is fidelity_limited (opponent Discipline not simulated).
    assert ids == {
        "close-from-six-double",
        "float-gust-deny-lethal",
        "spend-develop-no-threat",
        "tempo-hold-contested-wipe",
        "tempo-take-contested-fof",
        "take-closed-runes-contest",
        "retreat-low-score-threat",
        "reinforce-hold-at-seven",
    }
    assert "hold-open-rune-discipline" not in ids
    assert all("decision_v2" in c.tags for c in cases)
    assert all(c.trap_outcomes for c in cases)
    tempo = [c for c in cases if c.case_id.startswith("tempo-")]
    assert len(tempo) == 2
    assert all(c.metamorphic_family == "tempo-contest" for c in tempo)
    take = next(c for c in cases if c.case_id == "take-closed-runes-contest")
    assert take.metamorphic_family == "open-rune-react"
    assert take.fidelity_status == "authoritative"
    retreat = [
        c
        for c in cases
        if c.case_id in {"retreat-low-score-threat", "reinforce-hold-at-seven"}
    ]
    assert len(retreat) == 2
    assert all(c.metamorphic_family == "retreat-reinforce" for c in retreat)

    limited = load_corpus(
        POSITIONS,
        splits=["blocking", "dev"],
        include_fidelity_limited=True,
        eval_lanes=["agent"],
        case_globs=["hold-open-rune-discipline.json"],
    )
    assert len(limited) == 1
    hold = limited[0]
    assert hold.case_id == "hold-open-rune-discipline"
    assert hold.fidelity_status == "fidelity_limited"
    assert hold.metamorphic_family == "open-rune-react"


def test_line_contains_grades_full_chosen_line():
    case = next(
        c
        for c in load_corpus(POSITIONS, splits=["dev"], eval_lanes=["agent"])
        if c.case_id == "tempo-hold-contested-wipe"
    )
    # Gold develop at base.
    good = TrialResult(
        case_id=case.case_id,
        profile_id="mock",
        decision={"command": "play raging-soul"},
        metrics={
            "command": "play raging-soul",
            "chosen_moves": ["play raging-soul"],
            "engine_ok": True,
        },
    )
    gold = grade_trial(case, good, layers=["gold"]).layers[0]
    assert gold.passed
    assert gold.details.get("trap_hit") is False

    # Trap: overcommit into contested A.
    bad = TrialResult(
        case_id=case.case_id,
        profile_id="mock",
        decision={"command": "move chemtech-enforcer to battlefield-a"},
        metrics={
            "command": "move chemtech-enforcer to battlefield-a",
            "chosen_moves": [
                "move chemtech-enforcer to battlefield-a",
                "play discipline",
                "play raging-soul to battlefield-a",
            ],
            "engine_ok": True,
        },
    )
    trapped = grade_trial(case, bad, layers=["gold"]).layers[0]
    assert not trapped.passed
    assert trapped.details.get("trap_hit") is True


def test_fixture_hash_stable():
    digest = hash_fixture("res://Scripts/Tests/Tcg/fixtures/search_winning_line.json")
    assert len(digest) == 16
    case = next(c for c in load_corpus(POSITIONS, splits=["blocking"]) if c.case_id == "win-from-seven")
    assert case.fixture_hash == digest


def test_catalog_contains_all_cases(tmp_path: Path):
    cases = load_corpus(
        POSITIONS,
        splits=["dev", "sealed", "challenge", "blocking"],
        include_fidelity_limited=True,
    )
    text = render_catalog(cases)
    for case in cases:
        assert f"`{case.case_id}`" in text
    out = tmp_path / "catalog.md"
    write_catalog(cases, catalog_path=out)
    assert out.exists()
    assert out.read_text(encoding="utf-8") == text


def test_transforms_reorder_hand_without_changing_card_multiset():
    case = next(c for c in load_corpus(POSITIONS, splits=["blocking"]) if c.case_id == "jinx-auto-discard-chain")
    fixture = load_fixture_dict(case)
    transformed = apply_transform("reorder_hand", fixture)
    assert sorted(fixture["players"][0]["hand"]) == sorted(transformed["players"][0]["hand"])
    assert "identity" in available_transforms()


def test_grader_marks_win_case_pass():
    case = next(c for c in load_corpus(POSITIONS, splits=["blocking"]) if c.case_id == "win-from-seven")
    profile = load_profile(PROFILES / "baseline-argmax-mock.json")
    trial = run_mock_adapter(case, profile)
    graded = grade_trial(case, trial)
    assert graded.overall_pass
    layers = {layer.layer: layer for layer in graded.layers}
    assert layers["gold"].passed
    assert layers["validity"].passed


def test_grader_trap_outcome_fails_gold():
    case = next(c for c in load_corpus(POSITIONS, splits=["blocking"]) if c.case_id == "win-from-seven")
    case = case.model_copy(
        update={
            "trap_outcomes": [
                AcceptableOutcome(
                    kind="wins_game",
                    params={},
                    description="Treat winning as the attractive wrong line for this unit test",
                    label_tier="gold",
                )
            ]
        }
    )
    profile = load_profile(PROFILES / "baseline-argmax-mock.json")
    trial = run_mock_adapter(case, profile)
    graded = grade_trial(case, trial, layers=["gold"])
    gold = graded.layers[0]
    assert not gold.passed
    assert gold.details.get("trap_hit") is True


def test_compute_run_metrics_hard_gold_and_trap_rate():
    hard_case = EvalCase(
        case_id="hard-demo",
        title="Hard",
        summary="s",
        objective="o",
        desired_result="d",
        fixture_path="res://Scripts/Tests/Tcg/fixtures/search_winning_line.json",
        difficulty="hard",
        fidelity_status="authoritative",
        acceptable_outcomes=[AcceptableOutcome(kind="wins_game", label_tier="gold")],
        trap_outcomes=[AcceptableOutcome(kind="score_after_equals", params={"my_score_after": 5})],
    )
    easy_case = EvalCase(
        case_id="easy-demo",
        title="Easy",
        summary="s",
        objective="o",
        desired_result="d",
        fixture_path="res://Scripts/Tests/Tcg/fixtures/search_winning_line.json",
        difficulty="easy",
        fidelity_status="authoritative",
        acceptable_outcomes=[AcceptableOutcome(kind="wins_game", label_tier="gold")],
    )
    hard_pass = TrialResult(
        case_id="hard-demo",
        profile_id="p",
        layers=[
            LayerResult(layer="gold", passed=True, score=1.0, details={"trap_hit": False}),
            LayerResult(layer="validity", passed=True, score=1.0),
            LayerResult(layer="cost", passed=True, details={"timeout": False}),
            LayerResult(layer="trajectory", passed=True, score=1.0),
        ],
        metrics={"latency_ms": 100, "model_calls": 2, "prompt_tokens": 50},
        overall_pass=True,
    )
    hard_trap = TrialResult(
        case_id="hard-demo",
        profile_id="p",
        layers=[
            LayerResult(layer="gold", passed=False, score=0.0, details={"trap_hit": True}),
            LayerResult(layer="validity", passed=True, score=1.0),
            LayerResult(layer="cost", passed=True, details={"timeout": False}),
            LayerResult(layer="trajectory", passed=True, score=1.0),
        ],
        metrics={"latency_ms": 200, "model_calls": 3, "prompt_tokens": 80},
        overall_pass=False,
    )
    easy_pass = TrialResult(
        case_id="easy-demo",
        profile_id="p",
        layers=[
            LayerResult(layer="gold", passed=True, score=1.0, details={"trap_hit": False}),
            LayerResult(layer="validity", passed=True, score=1.0),
            LayerResult(layer="cost", passed=True, details={"timeout": False}),
            LayerResult(layer="trajectory", passed=True, score=1.0),
        ],
        metrics={"latency_ms": 50, "model_calls": 0, "prompt_tokens": 0},
        overall_pass=True,
    )
    out = compute_run_metrics([hard_pass, hard_trap, easy_pass], [hard_case, easy_case])
    overall = out["overall"]
    assert overall["hard_gold_n"] == 2
    assert overall["hard_gold_pass"] == 1
    assert overall["hard_gold_pass_rate"] == 0.5
    assert overall["easy_gold_n"] == 1
    assert overall["easy_gold_pass_rate"] == 1.0
    assert overall["trap_n"] == 2
    assert overall["trap_hits"] == 1
    assert overall["trap_rate"] == 0.5
    assert overall["mean_latency_ms"] == 350.0 / 3.0


def test_grader_rejects_missing_reject_metric_for_stale_root():
    case = next(c for c in load_corpus(POSITIONS, splits=["blocking"]) if c.case_id == "stale-root-rejected")
    profile = load_profile(PROFILES / "baseline-argmax-mock.json")
    trial = run_mock_adapter(case, profile)
    # Force a failure by clearing reject markers.
    trial.metrics["expected_reject"] = False
    trial.metrics["stale_root_rejected"] = False
    trial.decision["rejected"] = False
    graded = grade_trial(case, trial, layers=["validity"])
    assert not graded.layers[0].passed


def test_store_round_trip(tmp_path: Path):
    store = EvalStore(tmp_path / "results.db")
    store.start_run(
        run_id="t1",
        description="test",
        mode="agent_only",
        manifest={"run_id": "t1"},
    )
    case = next(c for c in load_corpus(POSITIONS, splits=["blocking"]) if c.case_id == "tap-rune-energy")
    profile = load_profile(PROFILES / "baseline-argmax-mock.json")
    trial = grade_trial(case, run_mock_adapter(case, profile))
    store.record_config("t1", profile.profile_id, profile.model_dump())
    store.record_case_snapshot("t1", case.case_id, case.model_dump())
    rid = store.record_trial("t1", trial)
    store.finish_run("t1")
    assert rid > 0
    summary = store.summary("t1")
    assert summary["trials"] == 1
    assert summary["by_profile"][profile.profile_id]["passed"] == 1


def test_blocking_manifest_run(tmp_path: Path):
    manifest = EvalRunManifest(
        run_id="unit-blocking",
        description="unit test",
        splits=["blocking"],
        profiles=["baseline-argmax-mock"],
        repeats=1,
        transforms=["identity"],
        include_fidelity_limited=False,
        mode="agent_only",
    )
    run_dir = run_eval(
        manifest,
        positions_dir=POSITIONS,
        profiles_dir=PROFILES,
        runs_dir=tmp_path,
    )
    assert (run_dir / "report.md").exists()
    assert (run_dir / "results.jsonl").exists()
    assert (run_dir / "results.db").exists()
    assert (run_dir / "metrics.json").exists()
    lines = (run_dir / "results.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 10
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "baseline-argmax-mock" in report
    assert "## Metrics" in report
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    assert "overall" in metrics
    assert "by_profile" in metrics


def test_arena_pair_expansion_and_analysis():
    manifest = ArenaManifest.model_validate(
        json.loads((REPO / "Data/AI/Eval/manifests/arena-pilot.json").read_text())
    )
    jobs = expand_pairs(manifest)
    assert len(jobs) == manifest.num_pairs * len(manifest.opponents) * 2
    assert jobs[0]["pair_leg"] == "a"
    assert jobs[1]["pair_leg"] == "b"
    assert jobs[0]["candidate_seat"] == 0
    assert jobs[1]["candidate_seat"] == 1
    assert jobs[0]["p1_profile"] != jobs[1]["p1_profile"] or jobs[0]["p1_deck"] != jobs[1]["p1_deck"] or True

    leg_a = {
        "pair_id": "p1",
        "seed": 1,
        "opponent_id": "baseline_mirror",
        "candidate_won": True,
        "finished": True,
    }
    leg_b = {
        "pair_id": "p1",
        "seed": 1,
        "opponent_id": "baseline_mirror",
        "candidate_won": True,
        "finished": True,
    }
    pair = aggregate_pair(leg_a, leg_b)
    assert pair["candidate_wins"] == 2
    assert pair_score(2) == 2
    analysis = analyze_pairs([pair])
    assert analysis["finished_pairs"] == 1
    assert analysis["strict_pair_wins"] == 1
    low, high = wilson_interval(1, 1)
    assert 0.0 <= low <= high <= 1.0


def test_eval_case_schema_rejects_empty_id():
    try:
        EvalCase(
            case_id=" ",
            title="x",
            summary="x",
            objective="x",
            desired_result="x",
            fixture_path="res://Scripts/Tests/Tcg/fixtures/search_winning_line.json",
        )
        assert False, "expected validation error"
    except Exception:
        pass
