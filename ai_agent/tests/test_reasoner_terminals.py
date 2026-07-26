from ai_agent.reasoner import (
    _investigation_exemption,
    _successful_search,
    _terminal_emit,
)
from ai_agent.reasoner_context import ReasonerTurnContext, install_context, reset_context


def _register(context, *, complete=True, root="root"):
    line = context.registry.register({
        "line_id": "line-1",
        "moves": ["pass", "end turn"],
        "move_contexts": [{}, {}],
        "expected_pre_hashes": ["root", "next"],
        "root_state_hash": root,
        "legal": True,
        "complete": complete,
        "terminal_reason": "end_turn" if complete else "node_budget",
    }, source="scout")
    assert line is not None
    return line


def test_commit_terminal_accepts_only_complete_root_matched_registry_line():
    context = ReasonerTurnContext("g", {}, "root")
    line = _register(context)
    token = install_context(context)
    try:
        emit, error = _terminal_emit(
            "commit_line",
            {"line_id": line["line_id"], "rationale": "Scout line wins."},
            turn=1,
            root_state_hash="root",
            investigation_satisfied=True,
            exemption=None,
            comparison_required=False,
        )
    finally:
        reset_context(token)
    assert error is None
    assert emit is not None and emit.kind == "line"


def test_incomplete_and_root_mismatched_lines_are_rejected():
    context = ReasonerTurnContext("g", {}, "root")
    incomplete = _register(context, complete=False)
    token = install_context(context)
    try:
        emit, error = _terminal_emit(
            "commit_line",
            {"line_id": incomplete["line_id"], "rationale": "Try it."},
            turn=1,
            root_state_hash="root",
            investigation_satisfied=True,
            exemption=None,
            comparison_required=False,
        )
        assert emit is None and "incomplete" in str(error)

        other = context.registry.register({
            **incomplete,
            "line_id": "line-2",
            "moves": ["end turn"],
            "move_contexts": [{}],
            "expected_pre_hashes": ["other"],
            "root_state_hash": "other",
            "complete": True,
        }, source="deepen")
        assert other is not None
        emit, error = _terminal_emit(
            "commit_line",
            {"line_id": other["line_id"], "rationale": "Try it."},
            turn=1,
            root_state_hash="root",
            investigation_satisfied=True,
            exemption=None,
            comparison_required=False,
        )
        assert emit is None and "root state" in str(error)
    finally:
        reset_context(token)


def test_emit_goals_rejects_one_invalid_goal_without_partial_acceptance():
    context = ReasonerTurnContext("g", {}, "root")
    token = install_context(context)
    try:
        emit, error = _terminal_emit(
            "emit_goals",
            {
                "goal_set": {
                    "turn": 0,
                    "goals": [
                        {"id": "ok", "kind": "weight_bias", "feature": "battlefield_control"},
                        {"id": "bad", "kind": "invented"},
                    ],
                },
                "rationale": "Control the map.",
            },
            turn=9,
            root_state_hash="root",
            investigation_satisfied=True,
            exemption=None,
            comparison_required=False,
        )
    finally:
        reset_context(token)
    assert emit is None
    assert "literal_error" in str(error)


def test_failed_empty_or_presim_search_does_not_satisfy_gate():
    assert not _successful_search(
        "search_for", {"source": "live_engine", "matches": []}
    )
    assert not _successful_search(
        "deepen", {"source": "live_engine", "error": "seed failed", "candidate_lines": []}
    )
    assert not _successful_search(
        "search_for", {"source": "presim_corpus", "matches": [{"line_id": "x"}]}
    )


def test_investigation_gate_forced_and_single_line_exemptions():
    assert _investigation_exemption(
        {"legal_moves": ["end turn"]}, []
    ) == "forced"
    assert _investigation_exemption(
        {"legal_moves": ["pass", "end turn"]},
        [{"line_id": "only", "complete": True}],
    ) == "single_playable_line"


def test_emit_goals_rejects_schema_valid_but_off_vocabulary_goal():
    context = ReasonerTurnContext("g", {}, "root")
    token = install_context(context)
    try:
        emit, error = _terminal_emit(
            "emit_goals",
            {
                "goal_set": {
                    "goals": [{
                        "id": "invented",
                        "kind": "weight_bias",
                        "feature": "make_everything_free",
                    }],
                },
                "rationale": "Invalid vocabulary probe.",
            },
            turn=1,
            root_state_hash="root",
            investigation_satisfied=True,
            exemption=None,
            comparison_required=False,
        )
    finally:
        reset_context(token)
    assert emit is None
    assert "not a registry weight" in str(error)
