import os
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

# ensure repo root on sys.path for imports
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")


@pytest.fixture
def client():
    from app.main import app
    client = TestClient(app)
    yield client
