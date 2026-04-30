from app.deal_selector import duration_bucket, deal_hash


def test_duration_bucket():
    assert duration_bucket(3) == "weekend"
    assert duration_bucket(7) == "week"
    assert duration_bucket(12) == "twoweeks"
    assert duration_bucket(1) == "short"


def test_deal_hash_consistent():
    h1 = deal_hash("Bangkok", "Praha", "week")
    h2 = deal_hash("Bangkok", "Praha", "week")
    assert h1 == h2
