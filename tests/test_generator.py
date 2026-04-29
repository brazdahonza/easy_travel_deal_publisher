from app.post_generator import generate_patreon_post, generate_twitter_post


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

