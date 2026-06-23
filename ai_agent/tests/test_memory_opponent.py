from __future__ import annotations

from ai_agent.memory import Memory


def _mem(tmp_path):
    return Memory(db_path=tmp_path / "mem.db")


def test_count_opponent_material_actions_counts_plays_and_abilities(tmp_path):
    mem = _mem(tmp_path)
    g = "game-1"
    mem.record_opponent_action(game_id=g, turn=2, action="played noxus-hopeful-1 to battlefield-a")
    mem.record_opponent_action(game_id=g, turn=2, action="used ability cemetery-attendant-2")
    mem.record_opponent_action(game_id=g, turn=2, action="played reaction get-excited-3 targeting u1")
    assert mem.count_opponent_material_actions(g) == 3


def test_count_opponent_material_actions_ignores_pass_move_choose_end(tmp_path):
    mem = _mem(tmp_path)
    g = "game-1"
    mem.record_opponent_action(game_id=g, turn=2, action="passed")
    mem.record_opponent_action(game_id=g, turn=2, action="moved unit to battlefield-a")
    mem.record_opponent_action(game_id=g, turn=2, action="chose yes")
    mem.record_opponent_action(game_id=g, turn=2, action="ended their turn")
    assert mem.count_opponent_material_actions(g) == 0


def test_count_opponent_material_actions_is_scoped_per_game(tmp_path):
    mem = _mem(tmp_path)
    mem.record_opponent_action(game_id="g1", turn=1, action="played card-1")
    mem.record_opponent_action(game_id="g2", turn=1, action="played card-2")
    assert mem.count_opponent_material_actions("g1") == 1
