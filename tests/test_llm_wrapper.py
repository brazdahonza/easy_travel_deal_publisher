import pytest

pytest.importorskip("anthropic")

from app.llm import AnthropicWrapper


def test_anthropic_wrapper_init(monkeypatch):
    class FakeClient:
        def __init__(self, key=None):
            pass

        class completions:
            @staticmethod
            def create(model=None, prompt=None, max_tokens=None):
                class R:
                    text = "<selection><ids>a,b</ids><justification>ok</justification></selection>"

                return R()

    monkeypatch.setitem(__import__("sys").modules, "anthropic", type("m", (), {"Client": FakeClient}))
    w = AnthropicWrapper(api_key="x")
    res = w.select([{"id":"a"}])
    assert "raw" in res
