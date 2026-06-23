from __future__ import annotations

import asyncio

import pytest

from ai_agent import agent as agent_module


class _Boom(Exception):
    """Stand-in transient error for the retry wrapper test."""


class _ScriptedCompletions:
    def __init__(self, behaviors):
        self._behaviors = list(behaviors)
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        item = self._behaviors.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _ScriptedChat:
    def __init__(self, behaviors):
        self.completions = _ScriptedCompletions(behaviors)


class _ScriptedClient:
    def __init__(self, behaviors):
        self.chat = _ScriptedChat(behaviors)


def test_chat_create_retries_transient_then_succeeds(monkeypatch):
    monkeypatch.setattr(agent_module, "TRANSIENT_API_ERRORS", (_Boom,))
    monkeypatch.setattr(agent_module, "MAX_TRANSIENT_RETRIES", 3)

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(agent_module.asyncio, "sleep", _no_sleep)

    sentinel = object()
    client = _ScriptedClient([_Boom("429"), _Boom("429"), sentinel])
    metrics: dict = {}

    result = asyncio.run(agent_module._chat_create(client, metrics=metrics, model="m"))

    assert result is sentinel
    assert client.chat.completions.calls == 3
    assert metrics["transient_retries"] == 2


def test_chat_create_raises_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr(agent_module, "TRANSIENT_API_ERRORS", (_Boom,))
    monkeypatch.setattr(agent_module, "MAX_TRANSIENT_RETRIES", 2)

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(agent_module.asyncio, "sleep", _no_sleep)

    client = _ScriptedClient([_Boom("429"), _Boom("429"), _Boom("429")])

    with pytest.raises(_Boom):
        asyncio.run(agent_module._chat_create(client, model="m"))

    # initial attempt + 2 retries
    assert client.chat.completions.calls == 3
