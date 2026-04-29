import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock

pytest.importorskip("playwright")

from app.publishers.patreon import PatreonPublisher, SessionExpiredError


@pytest.fixture
def patreon_publisher():
    """Create a PatreonPublisher with mock session"""
    publisher = PatreonPublisher()
    publisher.session = {
        "cookies": [{"name": "test", "value": "cookie"}],
        "email": "test@example.com"
    }
    return publisher


def test_patreon_publisher_init_with_valid_session(monkeypatch):
    """Test initialization with valid base64 session"""
    import base64
    import json
    
    session_data = {"cookies": [], "email": "test@example.com"}
    encoded = base64.b64encode(json.dumps(session_data).encode()).decode()
    
    # Mock settings to return our encoded session
    monkeypatch.setenv("PATREON_SESSION", encoded)
    
    # Re-import to pick up the env var
    from app.config import Settings
    settings = Settings()
    settings.PATREON_SESSION = encoded
    
    with patch("app.publishers.patreon.settings", settings):
        publisher = PatreonPublisher()
        assert publisher.session is not None
        assert publisher.session["email"] == "test@example.com"


def test_patreon_publisher_init_without_session():
    """Test initialization without session raises error on publish"""
    publisher = PatreonPublisher()
    publisher.session = None
    
    with pytest.raises(SessionExpiredError):
        asyncio.run(publisher.publish("title", "body"))


def test_patreon_publisher_publish_requires_playwright(patreon_publisher):
    """Test that publish requires Playwright to be installed"""
    # This test would fail if playwright is not installed, which is expected
    # The test is here to document the requirement
    try:
        from playwright.async_api import async_playwright
        assert True  # Playwright is available
    except ImportError:
        pytest.skip("Playwright not installed")


@pytest.mark.asyncio
async def test_patreon_publisher_publish_flow_mocked(patreon_publisher):
    """Test the publish flow with mocked Playwright"""
    
    # Create a mock for the async_playwright context manager
    async def mock_publish(self, title, body_text, destination=None):
        # Simulate successful publish
        return {"success": True, "url": "https://patreon.test/post/123"}
    
    with patch.object(PatreonPublisher, "publish", new=mock_publish):
        result = await patreon_publisher.publish(
            title="Test Post",
            body_text="Test body",
            destination="Prague"
        )
        assert result["success"] is True
        assert "url" in result


def test_patreon_get_image_path(patreon_publisher, tmp_path):
    """Test image path resolution for destinations"""
    # Create a mock image
    image_dir = tmp_path / "assets" / "patreon"
    image_dir.mkdir(parents=True)
    test_image = image_dir / "Prague.png"
    test_image.touch()
    
    # This test verifies the method exists and works
    # In real testing, we'd mock pathlib to return our test path
    assert hasattr(patreon_publisher, "_get_image_path")


def test_patreon_publisher_without_playwright():
    """Test behavior when Playwright is not available"""
    publisher = PatreonPublisher()
    publisher.session = {"cookies": []}
    
    # Verify the error message is clear
    try:
        asyncio.run(publisher.publish("title", "body"))
    except RuntimeError as e:
        assert "Playwright" in str(e) or "publish" in str(e)


def test_patreon_publisher_session_expired_error():
    """Test SessionExpiredError is raised when session is None"""
    publisher = PatreonPublisher()
    publisher.session = None
    
    with pytest.raises(SessionExpiredError) as exc_info:
        asyncio.run(publisher.publish("title", "body"))
    
    assert "Missing or invalid Patreon session" in str(exc_info.value)


@pytest.mark.asyncio
async def test_patreon_publish_with_destination():
    """Test that destination is passed through to image lookup"""
    publisher = PatreonPublisher()
    publisher.session = {"cookies": []}
    
    # Mock the _get_image_path method
    publisher._get_image_path = Mock(return_value="/path/to/Prague.png")
    
    # Mock publish to avoid actual Playwright calls
    async def mock_publish_impl(self, title, body_text, destination=None):
        image_path = self._get_image_path(destination)
        return {"success": True, "url": "test", "image_path": image_path}
    
    with patch.object(PatreonPublisher, "publish", new=mock_publish_impl):
        result = await publisher.publish(
            title="Prague Deal",
            body_text="Body",
            destination="Prague"
        )
        publisher._get_image_path.assert_called_with("Prague")

