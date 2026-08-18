from __future__ import annotations

import json
import sqlite3

from ai_agent import card_report as cr
from ai_agent import feature_report as fr


def _feature_db(rows: list[tuple[dict, str, int]]):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE search_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            origin TEXT, selector_source TEXT, mode TEXT,
            game_outcome TEXT, my_player_index INTEGER, went_first INTEGER,
            game_id TEXT, turn INTEGER, weight_version_id INTEGER,
            chosen_breakdown_json TEXT
        )
        """
    )
    for bd, outcome, wv in rows:
        conn.execute(
            "INSERT INTO search_decisions (origin, selector_source, mode, "
            "game_outcome, my_player_index, went_first, game_id, turn, "
            "weight_version_id, chosen_breakdown_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("self_play", "argmax", "main", outcome, 0, 1, "g", 3, wv, json.dumps(bd)),
        )
    conn.commit()
    return conn


def test_feature_report_groups_and_excludes_metadata():
    registry = {"score_diff": "state", "card_played": "action"}
    conn = _feature_db(
        [
            (
                {
                    "score_diff": 3.0,
                    "card_played": 0.2,
                    "total": 99.0,
                    "shaping_clamped": 0,
                    "win_game": 0.0,
                },
                "win",
                1,
            )
        ]
    )
    data = fr.gather(conn, filters={}, registry=registry)
    conn.close()
    assert data["total"] == 1
    assert "total" not in data["stats"]
    assert data["stats"]["score_diff"]["group"] == "state"
    assert data["stats"]["card_played"]["group"] == "action"
    assert data["stats"]["win_game"]["group"] == "terminal"


def test_feature_report_outcome_delta_and_mixed_versions():
    registry = {"score_diff": "state"}
    conn = _feature_db(
        [
            ({"score_diff": 6.0}, "win", 1),
            ({"score_diff": 0.0}, "loss", 2),
        ]
    )
    data = fr.gather(conn, filters={}, registry=registry)
    rows = {r["feature"]: r for r in fr._rows_from_stats(data)}
    assert data["mixed_weight_versions"] is True
    assert data["n_win"] == 1 and data["n_loss"] == 1
    assert rows["score_diff"]["delta"] == 6.0
    latest = fr.resolve_latest_weight_version(conn, {})
    assert latest == 2
    conn.close()


def test_feature_report_unregistered_when_registry_empty():
    conn = _feature_db([({"mystery_term": 1.5}, "win", 1)])
    data = fr.gather(conn, filters={}, registry={})
    conn.close()
    assert data["stats"]["mystery_term"]["group"] == "unregistered"


def _card_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE games (
            game_id TEXT PRIMARY KEY,
            outcome TEXT,
            winner_index INTEGER
        );
        CREATE TABLE card_events (
            game_id TEXT, turn INTEGER, my_player_index INTEGER,
            card_def_id TEXT, event TEXT, energy_spent INTEGER DEFAULT 0
        );
        CREATE TABLE search_decisions (
            game_id TEXT, origin TEXT
        );
        """
    )
    # Two-seat self-play: last writer stored outcome=win (seat 0), but seat 1 lost.
    conn.execute(
        "INSERT INTO games (game_id, outcome, winner_index) VALUES ('g1', 'win', 0)"
    )
    conn.execute("INSERT INTO search_decisions (game_id, origin) VALUES ('g1', 'self_play')")
    conn.execute("INSERT INTO search_decisions (game_id, origin) VALUES ('g2', 'vs_human')")
    conn.execute(
        "INSERT INTO games (game_id, outcome, winner_index) VALUES ('g2', 'loss', 1)"
    )
    # Seat 1 played falling-star in the self-play game they lost.
    conn.execute(
        "INSERT INTO card_events (game_id, turn, my_player_index, card_def_id, event) "
        "VALUES ('g1', 4, 1, 'falling-star', 'played')"
    )
    conn.execute(
        "INSERT INTO card_events (game_id, turn, my_player_index, card_def_id, event) "
        "VALUES ('g1', 4, 0, 'vi', 'played')"
    )
    conn.execute(
        "INSERT INTO card_events (game_id, turn, my_player_index, card_def_id, event) "
        "VALUES ('g2', 2, 0, 'falling-star', 'played')"
    )
    conn.commit()
    return conn


def test_card_report_win_rate_uses_winner_index_not_outcome():
    conn = _card_db()
    data = cr.gather(conn, filters={})
    by_id = {c["card_def_id"]: c for c in data["cards"]}
    # Seat 1 played falling-star and lost (winner_index 0). Old code used
    # games.outcome='win' and would have reported 100%.
    assert by_id["falling-star"]["win_rate_when_played"] == 0.0
    assert by_id["vi"]["win_rate_when_played"] == 1.0
    conn.close()


def test_card_report_origin_filter_excludes_other_games():
    conn = _card_db()
    data = cr.gather(conn, filters={"origin": "self_play"})
    by_id = {c["card_def_id"]: c for c in data["cards"]}
    assert data["games_total"] == 1
    assert "falling-star" in by_id
    assert by_id["falling-star"]["played"] == 1
    conn.close()
