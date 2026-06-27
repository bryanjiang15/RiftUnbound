from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import pytest

from ai_agent import texel_tune as tt


# ── Helpers ──────────────────────────────────────────────────────────────────


def _profile() -> dict:
    """Minimal profile mirroring the new schema-3 default (one of each tunable
    weight group). keyword_weights is kept to two entries to keep tests focused."""
    return {
        "schema_version": "3.0",
        "win_game": 1000.0,
        "state_weights": {
            "score_diff": 10.0,
            "win_proximity": 12.0,
            "hold_income": 3.0,
            "battlefield_control": 5.0,
            "battlefield_might_margin": 0.4,
            "control_fragility": 1.5,
            "unit_might_on_board": 0.15,
            "ready_unit_might": 0.3,
            "idle_base_might": -0.1,
            "damage_fragility": 1.0,
            "cards_in_hand": 0.3,
            "rune_development": 0.3,
            "reactive_potential": 1.0,
            "unusable_runes": -0.15,
        },
        "action_weights": {
            "card_played": 1.0,
            "unit_moved": 0.2,
            "card_discarded": -0.5,
            "enemy_unit_killed": 1.5,
            "own_unit_lost": -1.5,
            "battlefield_conquered": 4.0,
            "point_scored": 8.0,
            "card_drawn": 0.4,
            "power_used": -0.05,
        },
        "keyword_weights": {"assault": 0.4, "tank": 0.6},
        "situational_weights": {},
        "battlefield_weights": {"battlefield-a": 1.5, "battlefield-b": 1.0},
        "end_of_turn": {"hand_size_target": 3, "hand_size_weight": 0.3, "rune_weight": 0.2},
    }


def _features(score_diff=0, might=0, game_over=False, bf_control=None, keyword_net=None):
    base = {
        "ai_index": 0,
        "game_over": game_over,
        "score_diff": score_diff,
        "win_proximity": 0.0,
        "hold_income": 0,
        "control_fragility": 0.0,
        "unit_might_diff": might,
        "ready_unit_might_diff": 0,
        "idle_base_might_diff": 0,
        "damage_fragility": 0.0,
        "cards_in_hand_net": 0.0,
        "rune_development_diff": 0,
        "reactive_potential": 0,
        "unusable_runes": 0,
        "cards_played": 0,
        "units_moved": 0,
        "cards_discarded": 0,
        "enemy_units_killed": 0,
        "own_units_lost": 0,
        "battlefields_conquered": 0,
        "points_scored": 0,
        "cards_drawn": 0,
        "power_used": 0,
        "bf_control_net": bf_control or {},
        "bf_might_margin": {},
        "keyword_net": keyword_net or {},
    }
    return base


def _make_db(tmp_path, rows):
    """rows: list of (features_dict, outcome). Creates a minimal search_decisions."""
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        CREATE TABLE search_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT, turn INTEGER, decision_index INTEGER,
            mode TEXT, my_player_index INTEGER, selector_source TEXT,
            origin TEXT, went_first INTEGER, game_outcome TEXT,
            weight_version_id INTEGER,
            chosen_features_json TEXT, timestamp TEXT
        )
        """
    )
    now = datetime.now(timezone.utc).isoformat()
    for i, (feats, outcome) in enumerate(rows):
        conn.execute(
            "INSERT INTO search_decisions (game_id, turn, decision_index, mode, "
            "my_player_index, selector_source, origin, went_first, game_outcome, "
            "chosen_features_json, timestamp) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("g", 2, i, "main", 0, "argmax", "self_play", 1, outcome,
             json.dumps(feats), now),
        )
    conn.commit()
    conn.close()
    return db


# ── Term extraction ──────────────────────────────────────────────────────────


def test_extract_terms_maps_all_tunable_weights():
    prof = _profile()
    feats = _features(score_diff=3, might=5, keyword_net={"assault": 2, "tank": -1})
    terms = tt.extract_terms(feats, prof)
    assert terms[("state_weights", "score_diff")] == 3.0
    assert terms[("state_weights", "unit_might_on_board")] == 5.0
    assert terms[("keyword_weights", "assault")] == 2.0
    assert terms[("keyword_weights", "tank")] == -1.0
    # Every ordered key is extractable.
    for key in tt.ordered_weight_keys(prof):
        assert key in terms


def test_battlefield_control_value_signed_by_controller():
    prof = _profile()
    # ai_index 0 controls battlefield-a (w 1.5); opp controls battlefield-b (w 1.0).
    feats = _features(bf_control={"battlefield-a": 1, "battlefield-b": -1})
    val = tt._battlefield_control_value(feats, prof["battlefield_weights"])
    assert val == pytest.approx(1.5 - 1.0)


# ── Dataset loading ──────────────────────────────────────────────────────────


def test_load_dataset_labels_and_excludes_terminal(tmp_path):
    prof = _profile()
    rows = [
        (_features(score_diff=5), "win"),
        (_features(score_diff=-5), "loss"),
        (_features(score_diff=0), "draw"),
        (_features(score_diff=9, game_over=True), "win"),  # terminal -> excluded
    ]
    db = _make_db(tmp_path, rows)
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    ds = tt.load_dataset(conn, profile=prof, filters={})
    conn.close()
    assert ds["skipped_terminal"] == 1
    assert ds["y"] == [1.0, 0.0, 0.5]
    assert len(ds["X"]) == 3


def test_load_dataset_respects_filters(tmp_path):
    prof = _profile()
    rows = [(_features(score_diff=5), "win"), (_features(score_diff=-5), "loss")]
    db = _make_db(tmp_path, rows)
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    ds = tt.load_dataset(conn, profile=prof, filters={"outcome": "win"})
    conn.close()
    assert ds["y"] == [1.0]


# ── Logistic fit ─────────────────────────────────────────────────────────────


def test_fit_recovers_positive_sign_for_separable_feature():
    """A feature that cleanly separates win/loss must get a positive raw weight."""
    prof = _profile()
    keys = tt.ordered_weight_keys(prof)
    sd_idx = keys.index(("state_weights", "score_diff"))
    X, y = [], []
    for v in range(-6, 7):
        row = [0.0] * len(keys)
        row[sd_idx] = float(v)
        X.append(row)
        y.append(1.0 if v > 0 else 0.0)
    fit = tt.fit_logistic(X, y, k=1.0, l2=0.01, lr=0.5, epochs=3000)
    raw = tt.raw_weights(fit, keys)
    assert raw[("state_weights", "score_diff")] > 0.0


def test_fit_detects_sign_flip_against_profile():
    """Profile says idle_base_might is negative; data says more of it -> wins."""
    prof = _profile()
    keys = tt.ordered_weight_keys(prof)
    idx = keys.index(("state_weights", "idle_base_might"))
    X, y = [], []
    for v in range(-6, 7):
        row = [0.0] * len(keys)
        row[idx] = float(v)
        X.append(row)
        y.append(1.0 if v > 0 else 0.0)  # positive value correlates with winning
    fit = tt.fit_logistic(X, y, k=1.0, l2=0.01, lr=0.5, epochs=3000)
    raw = tt.raw_weights(fit, keys)
    diag = tt.diagnose(prof, raw, keys)
    flipped = next(d for d in diag if d["key"] == "idle_base_might")
    assert flipped["new"] > 0.0  # flipped from the profile's -0.1
    assert flipped["status"] == "sign-flip"


def test_zero_variance_feature_returns_no_signal():
    """A constant feature column carries no signal: raw weight None, kept as-is."""
    prof = _profile()
    keys = tt.ordered_weight_keys(prof)
    sd_idx = keys.index(("state_weights", "score_diff"))
    mt_idx = keys.index(("state_weights", "unit_might_on_board"))
    X, y = [], []
    for v in range(-6, 7):
        row = [0.0] * len(keys)
        row[sd_idx] = float(v)   # varies
        row[mt_idx] = 3.0        # constant -> zero variance
        X.append(row)
        y.append(1.0 if v > 0 else 0.0)
    fit = tt.fit_logistic(X, y, k=1.0, l2=0.01, lr=0.5, epochs=2000)
    raw = tt.raw_weights(fit, keys)
    assert raw[("state_weights", "unit_might_on_board")] is None
    diag = tt.diagnose(prof, raw, keys)
    might = next(d for d in diag if d["key"] == "unit_might_on_board")
    assert might["status"] == "no-signal"
    assert might["new"] == prof["state_weights"]["unit_might_on_board"]


def test_ridge_keeps_duplicated_features_finite_and_split():
    """Two identical (perfectly correlated) features stay finite under ridge and
    neither blows up — the key reason ridge is required (doc §2.1)."""
    prof = _profile()
    keys = tt.ordered_weight_keys(prof)
    a = keys.index(("state_weights", "score_diff"))
    b = keys.index(("state_weights", "cards_in_hand"))
    X, y = [], []
    for v in range(-6, 7):
        row = [0.0] * len(keys)
        row[a] = float(v)
        row[b] = float(v)  # duplicate of a
        X.append(row)
        y.append(1.0 if v > 0 else 0.0)
    fit = tt.fit_logistic(X, y, k=1.0, l2=1.0, lr=0.5, epochs=2000)
    raw = tt.raw_weights(fit, keys)
    wa = raw[("state_weights", "score_diff")]
    wb = raw[("state_weights", "cards_in_hand")]
    assert wa is not None and wb is not None
    assert abs(wa) < 100 and abs(wb) < 100   # ridge prevents explosion
    assert wa > 0 and wb > 0                 # signal shared, both positive


# ── Candidate profile output ─────────────────────────────────────────────────


def test_build_candidate_preserves_fixed_sections_and_updates_weights():
    prof = _profile()
    keys = tt.ordered_weight_keys(prof)
    new_raw = {k: None for k in keys}
    new_raw[("state_weights", "score_diff")] = 12.3456
    new_raw[("action_weights", "point_scored")] = None  # kept
    cand = tt.build_candidate_profile(prof, new_raw)
    assert cand["state_weights"]["score_diff"] == 12.3456
    # Untouched / None weights keep the original value.
    assert cand["action_weights"]["point_scored"] == 8.0
    # Fixed sections preserved verbatim.
    assert cand["win_game"] == 1000.0
    assert cand["battlefield_weights"] == prof["battlefield_weights"]
    assert cand["end_of_turn"] == prof["end_of_turn"]
