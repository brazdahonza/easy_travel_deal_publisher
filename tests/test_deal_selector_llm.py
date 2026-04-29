from app.deal_selector import build_anthropic_prompt, parse_anthropic_response, select_with_llm


def test_parse_anthropic_response():
    txt = "<selection><ids>deal1, deal2</ids><justification>Vybrano z duvodu nize</justification></selection>"
    res = parse_anthropic_response(txt)
    assert res["selected"] == ["deal1", "deal2"]
    assert "Vybrano" in res["justification"]


def test_select_with_llm_fallback():
    deals = [
        {"id": "d1", "destination": "A", "departure_city": "P", "is_nearby": True},
        {"id": "d2", "destination": "B", "departure_city": "P", "is_nearby": False},
    ]
    res = select_with_llm(deals)
    assert len(res["selected"]) == 2
