from unittest.mock import MagicMock

from app.post_generator import generate_patreon_post, generate_twitter_post


# ── LLM path tests ────────────────────────────────────────────────────────────

def test_patreon_post_calls_llm_when_api_key_configured(monkeypatch):
    """generate_patreon_post must call AnthropicWrapper.generate_post when key is set."""
    llm_title = "🔥 BANGKOK 8 dní za 8 500 Kč! (-45 %) ✈️ (Zpáteční letenky)"
    llm_body = "Přistál jsem na skvělém dealu.\n· Termín: 1. 6. – 8. 6. 2026 📅"
    llm_response = f"{llm_title}\n{llm_body}"

    monkeypatch.setattr("app.config.settings.ANTHROPIC_API_KEY", "fake-key")

    mock_instance = MagicMock()
    mock_instance.generate_post.return_value = llm_response
    monkeypatch.setattr("app.llm.AnthropicWrapper", MagicMock(return_value=mock_instance))

    deal = {"destination": "Bangkok", "departure_city": "Praha", "price": 8500}
    title, body = generate_patreon_post(deal)

    mock_instance.generate_post.assert_called_once()
    assert title == llm_title
    assert body == llm_body


def test_twitter_post_calls_llm_when_api_key_configured(monkeypatch):
    """generate_twitter_post must call AnthropicWrapper.generate_post when key is set."""
    llm_text = "Praha → Bangkok za 8 500 Kč. Přímý let, 7 nocí. ✈️ 🐿️\nhttps://t.co/x"

    monkeypatch.setattr("app.config.settings.ANTHROPIC_API_KEY", "fake-key")

    mock_instance = MagicMock()
    mock_instance.generate_post.return_value = llm_text
    monkeypatch.setattr("app.llm.AnthropicWrapper", MagicMock(return_value=mock_instance))

    deal = {"destination": "Bangkok", "departure_city": "Praha", "price": 8500, "ticket_url": "https://t.co/x"}
    text = generate_twitter_post(deal)

    mock_instance.generate_post.assert_called_once()
    assert text == llm_text


def test_patreon_post_falls_back_on_llm_exception(monkeypatch):
    """When LLM raises, generate_patreon_post must fall back to placeholder text."""
    monkeypatch.setattr("app.config.settings.ANTHROPIC_API_KEY", "fake-key")

    mock_instance = MagicMock()
    mock_instance.generate_post.side_effect = RuntimeError("API error")
    monkeypatch.setattr("app.llm.AnthropicWrapper", MagicMock(return_value=mock_instance))

    deal = {"destination": "Bangkok", "departure_city": "Praha", "price": 8500}
    title, body = generate_patreon_post(deal)

    assert "Bangkok" in title
    assert "Bangkok" in body


# ── Fallback path tests ───────────────────────────────────────────────────────

def test_patreon_post_returns_tuple():
    """Test that generate_patreon_post returns (title, body) tuple"""
    deal = {"destination": "Bangkok", "departure_city": "Praha", "price": 8500, "ticket_url": "https://t.co/x"}
    result = generate_patreon_post(deal)
    
    assert isinstance(result, tuple)
    assert len(result) == 2
    title, body = result
    
    # Title should contain destination and price
    assert "Bangkok" in title
    assert "8500" in title
    
    # Body should contain destination and offer info
    assert "Bangkok" in body
    assert "8500" in body


def test_patreon_post_includes_dates():
    """Test that dates are included in post body when provided"""
    deal = {
        "destination": "Paris",
        "departure_city": "Praha",
        "price": 5000,
        "date_from": "2026-05-01",
        "date_to": "2026-05-10",
        "ticket_url": "https://t.co/x"
    }
    title, body = generate_patreon_post(deal)
    
    assert "2026-05-01" in body
    assert "2026-05-10" in body


def test_patreon_post_includes_discount():
    """Test that discount percentage is included when provided"""
    deal = {
        "destination": "Barcelona",
        "departure_city": "Praha",
        "price": 4000,
        "discount_pct": 25,
        "ticket_url": "https://t.co/x"
    }
    title, body = generate_patreon_post(deal)
    
    assert "25%" in body or "25" in body


def test_patreon_post_without_url():
    """Test post generation when ticket_url is missing"""
    deal = {
        "destination": "Rome",
        "departure_city": "Praha",
        "price": 3500
    }
    title, body = generate_patreon_post(deal)
    
    assert "Rome" in title
    assert "Roma" in body or "Rome" in body  # Either should work


def test_twitter_post_length():
    deal = {"destination": "Bangkok", "departure_city": "Praha", "price": 8500, "ticket_url": "https://t.co/x"}
    text = generate_twitter_post(deal)
    assert len(text) <= 280
    assert "Bangkok" in text
    assert "8500" in text

