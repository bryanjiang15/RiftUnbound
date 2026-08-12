"""WPA model: coefficient recovery, splits, calibration, bootstrap."""
from __future__ import annotations

import math
import random
from pathlib import Path

from ai_agent.analysis import wpa_model as wm
from ai_agent.analysis import wpa_report
from ai_agent.memory import Memory


def _row(game_id: str, turn: int, seat: int, *, score_diff: float, win: bool,
         first: int = 0, turn_player: int | None = None, split: str = "train") -> dict:
    my_score = 4 + score_diff / 2.0
    opp_score = 4 - score_diff / 2.0
    return {
        "game_id": game_id,
        "turn": turn,
        "my_player_index": seat,
        "turn_player_index": seat if turn_player is None else turn_player,
        "my_score": my_score,
        "opp_score": opp_score,
        "board_might_diff": score_diff,
        "bf_control_net": 1 if score_diff > 0 else -1,
        "cards_in_hand": 4,
        "cards_in_hand_opp": 3,
        "my_rune_count": 6,
        "my_ready_rune_count": 2,
        "winner_index": seat if win else 1 - seat,
        "first_player_index": first,
        "split": split,
    }


def test_synthetic_coefficient_recovery():
    rng = random.Random(0)
    rows = []
    for g in range(80):
        gid = f"g{g:03d}"
        split = "train" if g < 56 else ("calibration" if g < 68 else "test")
        diff = rng.uniform(-4, 4)
        # Higher score_diff → more likely seat 0 wins. Seat 1 sees negated diff.
        p0 = 1.0 / (1.0 + math.exp(-1.2 * diff))
        win0 = rng.random() < p0
        for seat in (0, 1):
            sd = diff if seat == 0 else -diff
            rows.append(_row(gid, turn=3, seat=seat, score_diff=sd, win=win0 if seat == 0 else (not win0), split=split))
    model = wm.fit_wpa_model(rows, epochs=1500, seed=1)
    assert model["ok"]
    names = model["fit"]["feature_names"]
    w = model["fit"]["w_std"]
    score_i = names.index("score_diff")
    # Standardized weight on score_diff should be clearly positive.
    assert w[score_i] > 0.15
    test = model["test"]
    assert test["brier"] < test["baseline_brier"] - 1e-4
    assert test["roc_auc"] > 0.6


def test_game_grouped_chronological_splits_no_seat_leakage():
    game_ids = [f"g{i}" for i in range(10)]
    splits = wm.chronological_game_splits(game_ids)
    assert splits["train"].isdisjoint(splits["calibration"])
    assert splits["train"].isdisjoint(splits["test"])
    assert splits["calibration"].isdisjoint(splits["test"])
    assert splits["train"] | splits["calibration"] | splits["test"] == set(game_ids)
    # Both seats of one game stay together because split is by game_id only.
    rows = []
    for gid in game_ids:
        split_name = (
            "train" if gid in splits["train"]
            else "calibration" if gid in splits["calibration"]
            else "test"
        )
        for seat in (0, 1):
            rows.append(_row(gid, 1, seat, score_diff=1.0, win=True, split=split_name))
    by_game = {}
    for r in rows:
        by_game.setdefault(r["game_id"], set()).add(r["split"])
    assert all(len(v) == 1 for v in by_game.values())


def test_platt_calibration_and_baseline():
    labels = [0.0] * 20 + [1.0] * 30
    probs = [0.4] * 50  # miscalibrated
    base = wm.constant_baseline_brier(labels)
    # Constant base-rate predictor should beat a badly calibrated flat 0.4.
    assert base < wm.brier_score(probs, labels)
    logits = [-1.0] * 20 + [1.0] * 30
    platt = wm.fit_platt(logits, labels, epochs=400)
    cal = [wm._sigmoid(platt["a"] * z + platt["b"]) for z in logits]
    assert wm.brier_score(cal, labels) < wm.brier_score(
        [wm._sigmoid(z) for z in logits], labels
    ) + 0.05


def test_bootstrap_intervals_deterministic():
    vals = [0.1, -0.2, 0.3, 0.0, 0.15]
    a = wm.bootstrap_mean_ci(vals, seed=7, n_boot=200)
    b = wm.bootstrap_mean_ci(vals, seed=7, n_boot=200)
    assert a == b
    assert a["lo"] <= a["mean"] <= a["hi"]


def test_turn_and_exchange_wpa_and_swings():
    rows = []
    # Seat 0: p increases a lot on turn 2 (swing), then opponent reply.
    seq = [
        {"game_id": "g", "turn": 1, "my_player_index": 0, "turn_player_index": 0, "p_win": 0.40, "split": "test"},
        {"game_id": "g", "turn": 2, "my_player_index": 0, "turn_player_index": 0, "p_win": 0.70, "split": "test"},
        {"game_id": "g", "turn": 3, "my_player_index": 0, "turn_player_index": 1, "p_win": 0.65, "split": "test"},
    ]
    with_turn = wpa_report.compute_turn_wpa(seq)
    assert with_turn[0]["turn_wpa"] is None
    assert abs(with_turn[1]["turn_wpa"] - 0.30) < 1e-9
    with_ex = wpa_report.compute_exchange_wpa(with_turn)
    t2 = next(r for r in with_ex if r["turn"] == 2)
    assert t2["exchange_wpa"] is not None
    assert abs(t2["exchange_wpa"] - (0.30 + (0.65 - 0.70))) < 1e-9
    swings = wpa_report.swing_turns(with_ex, split="test")
    assert any(abs(s["turn_wpa"]) >= 0.10 for s in swings)


def test_card_associated_wpa_multi_card_and_min_plays(tmp_path: Path):
    mem = Memory(db_path=tmp_path / "wpa.db")
    # Minimal games + snapshots so validate_db works; card WPA unit-tested directly.
    turns = []
    played = {}
    for g in range(25):
        gid = f"g{g}"
        turns.append({
            "game_id": gid, "turn": 2, "my_player_index": 0, "turn_player_index": 0,
            "turn_wpa": 0.20 if g < 15 else -0.05, "split": "test",
        })
        cards = ["vi-destructive"] if g < 20 else ["vi-destructive", "gust"]
        played[(gid, 2, 0)] = cards
    # Baseline includes all own-turns.
    cards = wpa_report.card_associated_wpa(turns, played, min_plays=10, seed=0)
    vi = next(c for c in cards if c["card_def_id"] == "vi-destructive")
    gust = next(c for c in cards if c["card_def_id"] == "gust")
    assert vi["plays"] == 25
    assert vi["low_sample"] is False
    assert vi["ci95_lo"] is not None
    assert gust["plays"] == 5
    assert gust["low_sample"] is True
    assert gust["multi_card_turn_share"] == 1.0
    assert 0.0 < vi["multi_card_turn_share"] < 1.0


def test_validate_db_readiness(tmp_path: Path):
    mem = Memory(db_path=tmp_path / "ready.db")
    mem.record_game_outcome(
        game_id="g1", outcome="win", my_score=8, opp_score=2, turns_played=5,
        first_player_index=0, winner_index=0, p0_score=8, p1_score=2,
    )
    mem.record_turn_snapshot(
        game_id="g1", turn=1, my_player_index=0, turn_player_index=0,
        scalars={"my_score": 1, "opp_score": 0, "my_energy": 2, "board_might_diff": 3,
                 "cards_in_hand": 4, "cards_in_hand_opp": 3, "bf_control_net": 1,
                 "my_rune_count": 4, "my_ready_rune_count": 2},
        brief_state={"my_player_index": 0},
    )
    with mem._connect() as conn:
        checks = wpa_report.validate_db_readiness(conn)
    assert checks["ready_for_wpa"] is True
    assert checks["games_with_winner_index"] == 1
    assert checks["turn_snapshot_rows"] == 1
