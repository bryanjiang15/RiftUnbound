from __future__ import annotations

import asyncio

from ai_agent import agent as agent_module
from ai_agent.memory import Memory


class _Usage:
    def __init__(self, prompt: int, completion: int) -> None:
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = prompt + completion


class _Response:
    def __init__(self, usage=None) -> None:
        self.usage = usage


class _Completions:
    def __init__(self, responses) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        return self._responses.pop(0)


class _Chat:
    def __init__(self, responses) -> None:
        self.completions = _Completions(responses)


class _Client:
    def __init__(self, responses) -> None:
        self.chat = _Chat(responses)


def test_record_token_usage_splits_by_stage():
    metrics: dict = {}
    agent_module._record_token_usage(metrics, "planner", _Response(_Usage(100, 20)))
    agent_module._record_token_usage(metrics, "actor", _Response(_Usage(40, 10)))
    agent_module._record_token_usage(metrics, "actor", _Response(_Usage(5, 5)))

    assert metrics["total_tokens"] == 180
    assert metrics["prompt_tokens"] == 145
    assert metrics["completion_tokens"] == 35

    assert metrics["planner_model_calls"] == 1
    assert metrics["planner_total_tokens"] == 120
    assert metrics["planner_prompt_tokens"] == 100

    assert metrics["actor_model_calls"] == 2
    assert metrics["actor_total_tokens"] == 60
    assert metrics["actor_completion_tokens"] == 15


def test_record_token_usage_tolerates_missing_usage():
    metrics: dict = {}
    agent_module._record_token_usage(metrics, "actor", _Response(usage=None))
    # The call is still counted even when usage is unavailable (test doubles).
    assert metrics["actor_model_calls"] == 1
    assert metrics.get("total_tokens", 0) == 0


def test_record_token_usage_noop_without_metrics():
    # Must not raise when no metrics dict is threaded through.
    agent_module._record_token_usage(None, "actor", _Response(_Usage(10, 1)))


def test_chat_create_records_usage_for_stage():
    client = _Client([_Response(_Usage(70, 30))])
    metrics: dict = {}
    asyncio.run(
        agent_module._chat_create(client, metrics=metrics, stage="planner", model="m")
    )
    assert metrics["planner_total_tokens"] == 100
    assert metrics["planner_model_calls"] == 1
    assert metrics["total_tokens"] == 100


def test_record_decision_metrics_persists_and_aggregates(tmp_path):
    mem = Memory(db_path=tmp_path / "mem.db")
    metrics = {
        "model_calls": 2,
        "total_tokens": 300,
        "prompt_tokens": 240,
        "completion_tokens": 60,
        "planner_model_calls": 1,
        "planner_total_tokens": 120,
        "planner_prompt_tokens": 100,
        "planner_completion_tokens": 20,
        "actor_model_calls": 1,
        "actor_total_tokens": 180,
        "actor_prompt_tokens": 140,
        "actor_completion_tokens": 40,
    }
    mem.record_decision_metrics(
        game_id="g1",
        turn=1,
        decision_index=0,
        decision_type="main_phase",
        metrics=metrics,
    )

    summary = mem.summarize_game_eval("g1")
    assert summary["total_tokens_total"] == 300
    assert summary["planner_total_tokens_total"] == 120
    assert summary["actor_total_tokens_total"] == 180

    report = mem.eval_report()
    tokens = report["server_side"]["tokens"]
    assert tokens["total"] == 300
    assert tokens["planner"]["total"] == 120
    assert tokens["actor"]["total"] == 180
    assert tokens["planner"]["model_calls"] == 1
    assert tokens["actor"]["model_calls"] == 1


def test_migration_adds_token_columns_to_existing_db(tmp_path):
    import sqlite3

    db = tmp_path / "old.db"
    # Simulate a pre-token-tracking schema.
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE decision_eval_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL,
            turn INTEGER NOT NULL,
            decision_index INTEGER NOT NULL,
            decision_type TEXT NOT NULL,
            model_calls INTEGER NOT NULL DEFAULT 0,
            tool_rounds INTEGER NOT NULL DEFAULT 0,
            parse_retries INTEGER NOT NULL DEFAULT 0,
            legality_retries INTEGER NOT NULL DEFAULT 0,
            fell_back_to_pass INTEGER NOT NULL DEFAULT 0,
            latency_ms INTEGER NOT NULL DEFAULT 0,
            timestamp TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()

    # Opening through Memory should migrate the schema in place.
    mem = Memory(db_path=db)
    mem.record_decision_metrics(
        game_id="g1",
        turn=1,
        decision_index=0,
        decision_type="main_phase",
        metrics={"total_tokens": 50, "planner_total_tokens": 50},
    )
    report = mem.eval_report()
    assert report["server_side"]["tokens"]["total"] == 50
