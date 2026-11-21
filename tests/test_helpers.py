import pytest

from src.helpers import extract_urls, fmt_seconds, host_of, parse_score, score_color


@pytest.mark.parametrize("text,expected", [
    ("Score: 8/10", 8.0),
    ("Score: **7.5**/10", 7.5),
    ("score:  9 / 10", 9.0),
    ("no score here", None),
    ("", None),
    (None, None),
])
def test_parse_score(text, expected):
    assert parse_score(text) == expected


def test_extract_urls_dedupes_and_strips_punctuation():
    urls = extract_urls(
        "See https://a.com/x, and (https://b.org/y).",
        "again https://a.com/x; plus http://c.net",
    )
    assert urls == ["https://a.com/x", "https://b.org/y", "http://c.net"]


def test_extract_urls_ignores_non_http_schemes():
    assert extract_urls("javascript:alert(1) ftp://x.com file:///etc/passwd") == []


def test_extract_urls_handles_none():
    assert extract_urls(None, "") == []


def test_host_of():
    assert host_of("https://www.example.com/path?q=1") == "example.com"
    assert host_of("http://sub.example.com") == "sub.example.com"
    assert host_of("not a url") == "not a url"


@pytest.mark.parametrize("score,color", [
    (10, "var(--ok)"), (8, "var(--ok)"),
    (7.9, "var(--warn)"), (6, "var(--warn)"),
    (5.9, "var(--err)"), (0, "var(--err)"),
])
def test_score_color(score, color):
    assert score_color(score) == color


def test_fmt_seconds():
    assert fmt_seconds(45) == "45s"
    assert fmt_seconds(125) == "2m 5s"
