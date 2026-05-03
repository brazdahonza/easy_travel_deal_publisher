import pytest

pytest.importorskip("sqlalchemy")

from app.database import Base, ENGINE
from app import session_store


@pytest.fixture(autouse=True)
def create_tables():
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=ENGINE)
    yield


def test_save_and_load_roundtrip():
    cookies = [{"name": "session_id", "value": "abc", "domain": ".patreon.com", "path": "/"}]
    session_store.save(cookies, email="user@example.com")
    loaded = session_store.load()
    assert loaded is not None
    assert loaded["email"] == "user@example.com"
    assert loaded["cookies"][0]["name"] == "session_id"


def test_save_overwrites_existing_row():
    session_store.save([{"name": "a", "value": "1"}], email="x@y")
    session_store.save([{"name": "b", "value": "2"}], email="x@y")
    loaded = session_store.load()
    assert loaded["cookies"][0]["name"] == "b"


def test_bootstrap_seeds_from_env(monkeypatch):
    import base64, json
    blob = base64.b64encode(json.dumps({
        "cookies": [{"name": "boot", "value": "1"}],
        "email": "boot@x",
        "timestamp": "2026-01-01",
    }).encode()).decode()

    # Wipe any prior rows from earlier tests.
    from app.database import SessionLocal
    from app.models import PatreonSession
    db = SessionLocal()
    try:
        db.query(PatreonSession).delete()
        db.commit()
    finally:
        db.close()

    fake_settings = type("S", (), {"PATREON_SESSION": blob})()
    monkeypatch.setattr("app.session_store.settings", fake_settings, raising=False)
    # session_store imports settings lazily inside the function — patch at the module
    # level it uses.
    import app.config
    monkeypatch.setattr(app.config, "settings", fake_settings)

    session_store.bootstrap_from_env_if_empty()
    loaded = session_store.load()
    assert loaded is not None
    assert loaded["cookies"][0]["name"] == "boot"


def test_bootstrap_skips_when_table_populated(monkeypatch):
    session_store.save([{"name": "existing", "value": "v"}], email="keep@x")

    fake_settings = type("S", (), {"PATREON_SESSION": "ignored"})()
    import app.config
    monkeypatch.setattr(app.config, "settings", fake_settings)

    session_store.bootstrap_from_env_if_empty()
    loaded = session_store.load()
    assert loaded["cookies"][0]["name"] == "existing"
