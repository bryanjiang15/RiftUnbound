"""Load repo-root ``.env`` for eval runs (mirrors ``ai_agent.main``).

The FastAPI service calls ``load_dotenv()`` on startup. The eval CLI / adapters
call the reasoner in-process and would otherwise miss keys that only live in
``.env`` (not exported in the shell).
"""
from __future__ import annotations

from pathlib import Path

_LOADED = False
REPO_ROOT = Path(__file__).resolve().parents[2]


def ensure_dotenv() -> Path | None:
    """Load ``<repo>/.env`` once. Returns the path if it exists, else None."""
    global _LOADED
    env_path = REPO_ROOT / ".env"
    if _LOADED:
        return env_path if env_path.exists() else None
    _LOADED = True
    try:
        from dotenv import load_dotenv
    except ImportError:
        return env_path if env_path.exists() else None
    # override=False: explicit shell exports win over .env defaults.
    load_dotenv(env_path, override=False)
    return env_path if env_path.exists() else None
