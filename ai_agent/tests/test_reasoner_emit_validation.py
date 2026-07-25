from ai_agent.reasoner import _validated_emit
from ai_agent.schemas import ReasonerEmit


_STATE = {
    "turn_number": 2,
    "legal_moves": ["pass", "end turn"],
}


def test_verified_legal_line_is_accepted():
    emit = ReasonerEmit(
        kind="line",
        confidence="commit",
        chosen_line_id="line-1",
        moves=["pass", "end turn"],
    )
    out = _validated_emit(
        emit,
        brief_state=_STATE,
        evidence={"line-1": ["pass", "end turn"]},
        verified_sequences={("pass", "end turn")},
    )
    assert out.kind == "line"
    assert out.moves == ["pass", "end turn"]


def test_unverified_or_illegal_line_downgrades_to_empty_goals():
    emit = ReasonerEmit(
        kind="line",
        confidence="commit",
        moves=["play invented-card"],
    )
    out = _validated_emit(
        emit,
        brief_state=_STATE,
        evidence={},
        verified_sequences=set(),
    )
    assert out.kind == "goals"
    assert out.goal_set is not None
    assert out.goal_set.goals == []

