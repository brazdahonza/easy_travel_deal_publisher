import pytest

pytest.importorskip("playwright")

from app.publishers.patreon import PatreonPublisher


def test_init_loads_session_from_store(monkeypatch):
    fake_session = {"cookies": [{"name": "x", "value": "y"}], "email": "a@b"}
    monkeypatch.setattr("app.publishers.patreon.session_store.load", lambda: fake_session)
    pub = PatreonPublisher()
    assert pub.session == fake_session


def test_init_handles_empty_store(monkeypatch):
    monkeypatch.setattr("app.publishers.patreon.session_store.load", lambda: None)
    pub = PatreonPublisher()
    assert pub.session is None


def test_get_image_path_returns_none_for_unknown(monkeypatch):
    monkeypatch.setattr("app.publishers.patreon.session_store.load", lambda: None)
    pub = PatreonPublisher()
    # Real assets/ directory is small enough; an obviously bogus name should miss.
    assert pub._get_image_path("Definitely-Not-A-Real-City-Name-12345") is None


def test_get_image_path_finds_real_asset(monkeypatch):
    """Verify fuzzy matching finds at least one image when destination is in the asset set."""
    import pathlib
    monkeypatch.setattr("app.publishers.patreon.session_store.load", lambda: None)
    pub = PatreonPublisher()

    asset_dir = pathlib.Path(__file__).resolve().parents[1] / "assets" / "patreon"
    pngs = list(asset_dir.glob("*.png")) if asset_dir.exists() else []
    if not pngs:
        pytest.skip("No assets/patreon/*.png present in this checkout")
    # Take the first variant from the first available file as a guaranteed match.
    sample = pngs[0].stem.split(" - ")[0].strip()
    assert pub._get_image_path(sample) is not None
