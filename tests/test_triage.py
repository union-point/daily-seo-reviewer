from types import SimpleNamespace

import pytest

from seo_reviewer.config import Config
from seo_reviewer.triage import ProbeReply, probe_model


def install_client(monkeypatch, reply=None, status="completed", error=None):
    calls = []

    class FakeClient:
        def __init__(self, **kwargs):
            calls.append(kwargs)
            self.responses = self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def parse(self, **kwargs):
            calls.append(kwargs)
            if error:
                raise error
            return SimpleNamespace(
                status=status, output_parsed=reply,
                model="gpt-6.1-terra", id="response-test",
                usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15),
            )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key-never-store")
    monkeypatch.setattr("seo_reviewer.triage.OpenAI", FakeClient)
    return calls


def test_model_probe_validates_schema_and_evidence(monkeypatch):
    calls = install_client(monkeypatch, ProbeReply(result="ok", evidence_ids=["integration-probe"]))
    result = probe_model(Config())
    assert result.status == "passed"
    assert result.usage["total_tokens"] == 15
    assert calls[0] == {"timeout": 30.0, "max_retries": 1}
    assert calls[1]["reasoning"] == {"effort": "low"}
    assert calls[1]["store"] is False
    assert calls[1]["text_format"] is ProbeReply
    assert "test-key-never-store" not in result.model_dump_json()


@pytest.mark.parametrize("reply,status", [
    (None, "completed"),
    (ProbeReply(result="ok", evidence_ids=["invented"]), "completed"),
    (ProbeReply(result="ok", evidence_ids=["integration-probe"]), "incomplete"),
])
def test_refusal_incomplete_output_and_invalid_references_fail(monkeypatch, reply, status):
    install_client(monkeypatch, reply, status)
    assert probe_model(Config()).status == "failed"


def test_api_failure_does_not_expose_error_content(monkeypatch):
    install_client(monkeypatch, error=ValueError("private upstream error"))
    result = probe_model(Config())
    assert result.status == "failed"
    assert "private" not in result.model_dump_json()


def test_absent_key_is_an_incomplete_gate(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert probe_model(Config()).status == "skipped"
