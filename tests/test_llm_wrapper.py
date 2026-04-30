import pytest

pytest.importorskip("anthropic")

from app.llm import AnthropicWrapper


def test_anthropic_wrapper_init(monkeypatch):
    _xml = "<selection><ids>a,b</ids><justification>ok</justification></selection>"

    class FakeContent:
        text = _xml

    class FakeUsage:
        input_tokens = 10
        output_tokens = 5

    class FakeResponse:
        content = [FakeContent()]
        usage = FakeUsage()

    class FakeMessages:
        def create(self, **kwargs):
            return FakeResponse()

    class FakeClient:
        def __init__(self, api_key=None, **kwargs):
            self.messages = FakeMessages()

    monkeypatch.setitem(__import__("sys").modules, "anthropic", type("m", (), {"Anthropic": FakeClient}))
    w = AnthropicWrapper(api_key="x")
    res = w.select([{"id": "a"}])
    assert "raw" in res
