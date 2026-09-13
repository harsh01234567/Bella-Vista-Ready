"""
Shared fixtures for the backend test suite.

NOTE (handoff): these tests were written but never executed in the sandbox
that produced them - it has no network access, so `pip install -r
requirements.txt` (fastapi/pydantic/openai/etc) could not run and `import
main` could not be verified. Run `pip install -r requirements.txt -r
requirements-dev.txt` then `pytest` locally before trusting these.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Make sure imports and env vars are set before `main` (and its module-level
# FastAPI app / OPENAI_CLIENT / etc) are constructed.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("BELLA_VISTA_MODE", "demo")
os.environ.setdefault("OPENAI_API_KEY", "")

import main  # noqa: E402


@pytest.fixture()
def temp_db(monkeypatch, tmp_path):
    """Points main.DB_PATH at a throwaway sqlite file for the duration of a
    test, and initializes the schema against it, so tests never touch the
    real backend/bella_vista.db."""
    db_path = tmp_path / "test_bella_vista.db"
    monkeypatch.setattr(main, "DB_PATH", db_path)
    main.init_db()
    yield db_path
