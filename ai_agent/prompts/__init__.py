"""Central store of static AI prompt text.

Every static (placeholder-free) prompt used by the agent lives as a Markdown
file in this folder. Python modules load them by name with :func:`load_prompt`
instead of embedding prose, so the wording is edited in one place.

Prompts that need runtime substitution (board state, tool context, card ids)
are assembled in code and are intentionally NOT stored here.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """Return the text of ``<name>.md`` from this folder (trimmed).

    Results are cached; the same prompt file is read from disk only once.
    """
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


__all__ = ["load_prompt"]
