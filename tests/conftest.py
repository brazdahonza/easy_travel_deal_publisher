import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    """Force INGEST_API_KEY on for every test so auth checks behave consistently."""
    monkeypatch.setattr("app.config.settings.INGEST_API_KEY", "test-key")


@pytest.fixture
def client():
    from app.main import app
    from app.session import state as session_state

    session_state.clear_session()
    with TestClient(app) as c:
        yield c
    session_state.clear_session()


@pytest.fixture
def auth_headers():
    return {"X-API-Key": "test-key"}
