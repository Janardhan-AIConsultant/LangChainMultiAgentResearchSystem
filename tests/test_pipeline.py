import httpx
import openai
import pytest

from src.pipelines import pipelines
from src.pipelines.pipelines import _with_retry, validate_topic


def _status_error(code, message="boom"):
    req = httpx.Request("POST", "http://x")
    resp = httpx.Response(code, request=req)
    return openai.APIStatusError(message, response=resp, body=None)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(pipelines.time, "sleep", lambda s: None)


def test_validate_topic():
    assert validate_topic("  hello  ") == "hello"
    with pytest.raises(ValueError):
        validate_topic("   ")
    with pytest.raises(ValueError):
        validate_topic(None)
    with pytest.raises(ValueError):
        validate_topic("x" * (pipelines.MAX_TOPIC_LENGTH + 1))


def test_retry_succeeds_after_rate_limit_and_notifies():
    calls, notes = [], []

    def fn(payload):
        calls.append(payload)
        if len(calls) < 3:
            raise _status_error(429)
        return "ok"

    assert _with_retry(fn, "p", on_wait=notes.append) == "ok"
    assert len(calls) == 3 and len(notes) == 2


def test_retry_gives_up_after_max_attempts():
    def fn(_):
        raise _status_error(429)
    with pytest.raises(openai.APIStatusError):
        _with_retry(fn, "p", retries=3)


def test_retry_does_not_retry_other_errors():
    calls = []

    def fn(_):
        calls.append(1)
        raise _status_error(500)

    with pytest.raises(openai.APIStatusError):
        _with_retry(fn, "p")
    assert len(calls) == 1


def test_retry_does_not_retry_unfixable_token_error():
    calls = []

    def fn(_):
        calls.append(1)
        raise _status_error(413, "expected output tokens exceed the limit")

    with pytest.raises(openai.APIStatusError):
        _with_retry(fn, "p")
    assert len(calls) == 1


def test_retry_recovers_from_connection_error():
    calls = []

    def fn(_):
        calls.append(1)
        if len(calls) == 1:
            raise openai.APIConnectionError(request=httpx.Request("POST", "http://x"))
        return "ok"

    assert _with_retry(fn, "p") == "ok"
    assert len(calls) == 2


class _FakeAgent:
    def __init__(self, text):
        self.text = text

    def invoke(self, payload):
        class Msg:
            content = self.text
        return {"messages": [Msg()]}


class _FakeChain:
    def __init__(self, text):
        self.text = text
        self.seen = None

    def invoke(self, payload):
        self.seen = payload
        return self.text


def test_full_pipeline_end_to_end_with_fakes(monkeypatch):
    writer, critic = _FakeChain("# Report\nSources: https://a.com"), _FakeChain("Score: 9/10")
    monkeypatch.setattr(pipelines, "build_search_agent", lambda: _FakeAgent("Title: T\nURL: https://a.com"))
    monkeypatch.setattr(pipelines, "build_reader_agent", lambda: _FakeAgent("page text"))
    monkeypatch.setattr(pipelines, "writer_chain", writer)
    monkeypatch.setattr(pipelines, "critic_chain", critic)

    events = []
    state = pipelines.run_research_pipeline("  my topic  ", on_step=lambda k, s, d: events.append((k, s)))

    assert state["search_results"].startswith("Title: T")
    assert state["scraped_content"] == "page text"
    assert state["report"].startswith("# Report")
    assert state["feedback"] == "Score: 9/10"
    assert writer.seen["topic"] == "my topic"
    assert "page text" in writer.seen["research"] and "https://a.com" in writer.seen["research"]
    assert critic.seen == {"report": state["report"]}
    assert events == [
        ("search", "running"), ("search", "done"),
        ("read", "running"), ("read", "done"),
        ("write", "running"), ("write", "done"),
        ("critic", "running"), ("critic", "done"),
    ]


def test_pipeline_rejects_empty_topic_before_calling_anything(monkeypatch):
    def boom():
        raise AssertionError("agent must not be built for an invalid topic")
    monkeypatch.setattr(pipelines, "build_search_agent", boom)
    with pytest.raises(ValueError):
        pipelines.run_research_pipeline("   ")
