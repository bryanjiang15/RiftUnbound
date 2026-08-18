from __future__ import annotations

import json
from pathlib import Path

from ai_agent.analysis.persist_compact import STORAGE_MARK, compact_result_for_storage
from ai_agent.memory import Memory

FAT_STATE = {"board": "x" * 80, "units": {"vi": {"might": 5}}}


def _fat_path() -> dict:
    return {
        "line_id": "L1",
        "root_line_id": "R1",
        "moves": ["play vi", "end turn"],
        "canonical_moves": ["play vi", "end turn"],
        "score": 1.2,
        "search_state": FAT_STATE,
        "resolved_state": FAT_STATE,
        "features": {"score_diff": 1},
        "breakdown": {"score_diff": 1},
        "state_hash": "abc",
        "objective_value": 3,
        "my_score": 3,
        "opp_score": 1,
        "path_segments": [
            {
                "kind": "main",
                "seat": 0,
                "moves": ["play vi"],
                "search_state": FAT_STATE,
                "checkpoint": {
                    "turn_number": 3,
                    "acting_seat": 0,
                    "search_state": FAT_STATE,
                },
            }
        ],
        "checkpoint": {"turn_number": 4, "search_state": FAT_STATE},
    }


def test_outcome_rollout_drops_tree_and_search_state():
    result = {
        "ok": True,
        "status": "ok",
        "run_kind": "outcome_rollout",
        "horizon": "multi_turn",
        "candidate_lines": [_fat_path()],
        "rollout_tree": {
            "nodes": [{"search_state": FAT_STATE}],
            "paths": [_fat_path()],
        },
        "outcome_tiers": {
            "by_root": [{
                "root_line_id": "R1",
                "representative_paths": {"policy_pv": _fat_path()},
            }]
        },
        "roots": [_fat_path()],
        "target": {"kind": "win"},
    }
    out = compact_result_for_storage(result)
    assert out["storage"] == STORAGE_MARK
    assert "candidate_lines" not in out
    assert "rollout_tree" not in out
    path = out["outcome_tiers"]["by_root"][0]["representative_paths"]["policy_pv"]
    assert path["moves"] == ["play vi", "end turn"]
    assert path["path_segments"][0]["kind"] == "main"
    assert path["path_segments"][0]["seat"] == 0
    assert "search_state" not in path
    assert "resolved_state" not in path
    assert "search_state" not in path["path_segments"][0]
    assert "search_state" not in path["path_segments"][0]["checkpoint"]
    assert "search_state" not in path["checkpoint"]
    assert "search_state" not in out["roots"][0]
    assert compact_result_for_storage(out) == out


def test_same_turn_keeps_slim_candidate_lines():
    result = {
        "ok": True,
        "run_kind": "same_turn",
        "horizon": "1_player_turn",
        "candidate_lines": [_fat_path()],
        "comparison": {
            "played": {"line_id": "p", "moves": ["end turn"], "score": 1, "leaf_hash": "h"},
            "packs": [{
                "pack_id": "win_now",
                "offline_hard_matches": [{
                    "moves": ["play vi"],
                    "source_line": _fat_path(),
                }],
            }],
        },
    }
    out = compact_result_for_storage(result)
    assert len(out["candidate_lines"]) == 1
    assert out["candidate_lines"][0]["line_id"] == "L1"
    assert "search_state" not in out["candidate_lines"][0]
    match = out["comparison"]["packs"][0]["offline_hard_matches"][0]
    assert match["moves"] == ["play vi"]
    assert "source_line" not in match


def test_record_and_rewrite_compacts_legacy_blob(tmp_path: Path):
    mem = Memory(db_path=tmp_path / "cf.db")
    fat = {
        "ok": True,
        "run_kind": "outcome_rollout",
        "horizon": "multi_turn",
        "candidate_lines": [_fat_path()],
        "rollout_tree": {"nodes": [{"search_state": FAT_STATE}]},
        "outcome_tiers": {
            "by_root": [{
                "root_line_id": "R1",
                "representative_paths": {"policy_pv": _fat_path()},
            }]
        },
    }
    run_id = mem.record_counterfactual_run(
        game_id="g",
        turn=1,
        decision_index=0,
        root_state_hash="h",
        predicate_pack_version="1",
        search_inputs=None,
        profile_inputs=None,
        budget=None,
        assumptions={"horizon": "multi_turn"},
        status="ok",
        result=fat,
        run_kind="outcome_rollout",
    )
    stored = mem.get_counterfactual_run(run_id)["result"]
    assert stored["storage"] == STORAGE_MARK
    assert "candidate_lines" not in stored
    assert "rollout_tree" not in stored
    assert stored["outcome_tiers"]["by_root"][0]["root_line_id"] == "R1"

    with mem._connect() as conn:
        conn.execute(
            "UPDATE counterfactual_runs SET result_json=? WHERE id=?",
            (json.dumps(fat), run_id),
        )
    stats = mem.compact_counterfactual_run_payloads()
    assert stats["updated"] == 1
    assert stats["bytes_saved"] > 0
    rewritten = mem.get_counterfactual_run(run_id)["result"]
    assert rewritten["storage"] == STORAGE_MARK
    assert "rollout_tree" not in rewritten
