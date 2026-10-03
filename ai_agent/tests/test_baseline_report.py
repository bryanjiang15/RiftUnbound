"""
Unit tests for baseline_report.py

Tests the metric extraction and aggregation logic using a fixture database.
"""
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from ai_agent.baseline_report import (
    compute_commit_rate,
    compute_fallback_rate,
    compute_hash_diverge_rate,
    generate_baseline_summary,
    generate_markdown_summary,
)


@pytest.fixture
def fixture_db(tmp_path):
    """Create a temporary SQLite database with fixture data."""
    db_path = tmp_path / "test_baseline.db"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    # Create reasoner_decisions table (minimal schema for testing)
    cur.execute("""
        CREATE TABLE reasoner_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL,
            turn INTEGER NOT NULL,
            decision_index INTEGER,
            root_state_hash TEXT,
            terminal_kind TEXT,
            committed INTEGER,
            chosen_line_id TEXT,
            chosen_line_complete INTEGER,
            fallback_reason TEXT,
            investigation_exemption TEXT,
            selected_source_lineage_json TEXT,
            tool_mix_json TEXT,
            reasoner_latency_ms INTEGER,
            engine_latency_ms INTEGER,
            model_calls INTEGER,
            timestamp TEXT NOT NULL
        )
    """)
    
    # Insert fixture data:
    # - 10 eligible reasoner turns
    # - 8 commits (terminal_kind='line', committed=1)
    # - 2 fallbacks (terminal_kind='base_search_fallback')
    # - 2 exemptions (not counted in eligible)
    
    fixture_data = [
        # Game 1: 5 turns, 4 commits, 1 fallback
        ("game-1", 1, 0, "hash1", "line", 1, "line-1", 1, None, None, '["scout"]', '{"search_for": 2}', 2400, 3),
        ("game-1", 2, 1, "hash2", "line", 1, "line-2", 1, None, None, '["deepen"]', '{"deepen": 1}', 3100, 2),
        ("game-1", 3, 2, "hash3", "line", 1, "line-3", 1, None, None, '["scout"]', '{"search_for": 1}', 2200, 2),
        ("game-1", 4, 3, "hash4", "base_search_fallback", 0, None, 0, "fallback: budget exhausted", None, None, None, 1800, 1),
        ("game-1", 5, 4, "hash5", "line", 1, "line-4", 1, None, None, '["scout"]', '{"search_for": 1}', 2500, 2),
        
        # Game 2: 5 turns, 4 commits, 1 fallback
        ("game-2", 1, 0, "hash6", "line", 1, "line-5", 1, None, None, '["scout"]', '{"search_for": 2}', 2700, 3),
        ("game-2", 2, 1, "hash7", "line", 1, "line-6", 1, None, None, '["deepen"]', '{"deepen": 1, "simulate_move": 3}', 4200, 4),
        ("game-2", 3, 2, "hash8", "line", 1, "line-7", 1, None, None, '["scout"]', '{"search_for": 1}', 2100, 2),
        ("game-2", 4, 3, "hash9", "base_search_fallback", 0, None, 0, "fallback: transient API failure", None, None, None, 1500, 1),
        ("game-2", 5, 4, "hash10", "line", 1, "line-8", 1, None, None, '["scout"]', '{"search_for": 1}', 2300, 2),
        
        # Exemptions (not counted in eligible turns)
        ("game-1", 6, 5, None, None, 0, None, 0, None, "forced_single_move", None, None, None, None),
        ("game-2", 6, 5, None, None, 0, None, 0, None, "mulligan", None, None, None, None),
    ]
    
    for row in fixture_data:
        game_id, turn, dec_idx, root_hash, term_kind, committed, line_id, complete, fb_reason, exemption, source_json, tool_json, latency, model_calls = row
        cur.execute("""
            INSERT INTO reasoner_decisions
            (game_id, turn, decision_index, root_state_hash, terminal_kind, 
             committed, chosen_line_id, chosen_line_complete, fallback_reason,
             investigation_exemption, selected_source_lineage_json, tool_mix_json,
             reasoner_latency_ms, engine_latency_ms, model_calls, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """, (game_id, turn, dec_idx, root_hash, term_kind, committed, line_id,
              complete, fb_reason, exemption, source_json, tool_json, latency, latency, model_calls))
    
    conn.commit()
    conn.close()
    return str(db_path)


@pytest.fixture
def fixture_log(tmp_path):
    """Create a temporary log file with hash divergence events."""
    log_path = tmp_path / "agent_search.log"
    log_content = """
[INFO] Turn 2: Reasoner committed line-2
[HASH_DIVERGE] root_state_hash mismatch at step -1: expected=abc123 actual=def456
[INFO] Turn 3: Base search fallback
[HASH_DIVERGE] expected_pre_hash mismatch at step 2: expected=ghi789 actual=jkl012
[INFO] Turn 4: Reasoner committed line-4
    """
    log_path.write_text(log_content)
    return str(log_path)


def test_compute_commit_rate(fixture_db):
    """Test commit rate calculation."""
    result = compute_commit_rate(fixture_db)
    
    assert result["eligible_turns"] == 10  # 12 total - 2 exemptions
    assert result["commit_count"] == 8  # 8 committed lines
    assert result["commit_rate"] == 0.8  # 8/10
    
    # Check source breakdown
    sources = result["line_source_breakdown"]
    assert sources["scout"] == 6  # 6 scout lines
    assert sources["deepen"] == 2  # 2 deepen lines


def test_compute_fallback_rate(fixture_db):
    """Test fallback rate calculation."""
    result = compute_fallback_rate(fixture_db)
    
    assert result["fallback_count"] == 2  # 2 fallbacks
    assert result["fallback_rate"] == 0.2  # 2/10
    
    # Check breakdown
    breakdown = result["breakdown"]
    assert breakdown["budget_exhausted"] == 1
    assert breakdown["api_failure_after_retries"] == 1


def test_compute_hash_diverge_rate(fixture_db, fixture_log):
    """Test hash divergence rate calculation from logs."""
    result = compute_hash_diverge_rate(fixture_db, fixture_log)
    
    assert result["committed_lines_attempted"] == 8
    assert result["diverge_count"] == 2  # 2 divergences in log
    assert result["diverge_rate"] == 0.25  # 2/8
    
    # Check breakdown
    breakdown = result["breakdown"]
    assert breakdown["root_mismatch_pre_step_0"] == 1
    assert breakdown["pre_hash_mismatch_mid_line"] == 1


def test_generate_baseline_summary(fixture_db, fixture_log):
    """Test full baseline summary generation."""
    summary = generate_baseline_summary(
        db_path=fixture_db,
        log_path=fixture_log,
        git_sha="abc123def456",
        model="gpt-4o-test",
    )
    
    # Check required fields
    assert "run_date" in summary
    assert summary["git_sha"] == "abc123def456"
    assert summary["model"] == "gpt-4o-test"
    assert summary["games_completed"] == 2
    assert summary["eligible_reasoner_turns"] == 10
    assert summary["commit_count"] == 8
    assert summary["commit_rate"] == 0.8
    assert summary["fallback_count"] == 2
    assert summary["fallback_rate"] == 0.2
    assert summary["hash_diverge_count"] == 2
    assert summary["hash_diverge_rate"] == 0.25
    assert summary["hash_diverge_rate_denominator"] == 8
    
    # Check exemptions
    exemptions = summary["exemptions"]
    assert exemptions["forced_single_move"] == 1
    assert exemptions["mulligan"] == 1


def test_generate_markdown_summary(fixture_db, fixture_log):
    """Test markdown summary generation."""
    summary = generate_baseline_summary(
        db_path=fixture_db,
        log_path=fixture_log,
        git_sha="abc123def456",
        model="gpt-4o-test",
    )
    
    markdown = generate_markdown_summary(summary)
    
    # Check key sections are present
    assert "# Reasoner Multi-Game Baseline" in markdown
    assert "Commit Rate:" in markdown
    assert "Fallback Rate:" in markdown
    assert "Hash Diverge Rate:" in markdown
    assert "80.0%" in markdown  # 0.8 commit rate
    assert "20.0%" in markdown  # 0.2 fallback rate
    assert "25.0%" in markdown  # 0.25 diverge rate


def test_empty_database(tmp_path):
    """Test handling of empty database."""
    db_path = tmp_path / "empty.db"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE reasoner_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL,
            turn INTEGER NOT NULL,
            terminal_kind TEXT,
            committed INTEGER,
            fallback_reason TEXT,
            investigation_exemption TEXT,
            selected_source_lineage_json TEXT,
            tool_mix_json TEXT,
            reasoner_latency_ms INTEGER,
            engine_latency_ms INTEGER,
            timestamp TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()
    
    commit = compute_commit_rate(str(db_path))
    assert commit["eligible_turns"] == 0
    assert commit["commit_count"] == 0
    assert commit["commit_rate"] == 0.0
    
    fallback = compute_fallback_rate(str(db_path))
    assert fallback["fallback_count"] == 0
    assert fallback["fallback_rate"] == 0.0
