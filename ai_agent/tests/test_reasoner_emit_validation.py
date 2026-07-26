from ai_agent.reasoner import _validated_emit
from ai_agent.reasoner_context import ReasonerTurnContext, install_context, reset_context
from ai_agent.schemas import ReasonerEmit


_STATE = {
    "turn_number": 2,
    "legal_moves": ["pass", "end turn"],
}


def test_verified_legal_line_is_accepted():
    context = ReasonerTurnContext("g", _STATE, "root")
    line = context.registry.register({
        "line_id": "line-1",
        "moves": ["pass", "end turn"],
        "move_contexts": [{}, {}],
        "expected_pre_hashes": ["root", "next"],
        "root_state_hash": "root",
        "legal": True,
        "complete": True,
    }, source="scout")
    assert line is not None
    emit = ReasonerEmit(
        kind="line",
        confidence="commit",
        chosen_line_id=line["line_id"],
    )
    token = install_context(context)
    try:
        out = _validated_emit(emit, brief_state=_STATE)
    finally:
        reset_context(token)
    assert out.kind == "line"


def test_unverified_line_falls_back_to_base_search():
    context = ReasonerTurnContext("g", _STATE, "root")
    emit = ReasonerEmit(
        kind="line",
        confidence="commit",
        chosen_line_id="invented-line",
    )
    token = install_context(context)
    try:
        out = _validated_emit(emit, brief_state=_STATE)
    finally:
        reset_context(token)
    assert out.kind == "base_search_fallback"
    assert out.goal_set is None
