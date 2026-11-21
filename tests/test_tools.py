import socket

import pytest

from src.tools import tools
from src.tools.tools import UnsafeURLError, _assert_public_url, scrape_url


def _fake_resolver(ip):
    def fake(host, port, proto=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
    return fake


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "ftp://example.com/x",
    "javascript:alert(1)",
    "http:///nohost",
])
def test_rejects_bad_scheme_or_host(url):
    with pytest.raises(UnsafeURLError):
        _assert_public_url(url)


@pytest.mark.parametrize("ip", [
    "127.0.0.1", "10.0.0.5", "192.168.1.10", "172.16.0.1", "169.254.169.254", "::1",
])
def test_rejects_non_public_addresses(monkeypatch, ip):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_resolver(ip))
    with pytest.raises(UnsafeURLError):
        _assert_public_url("http://internal.example/")


def test_allows_public_address_and_returns_the_validated_ip(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_resolver("93.184.216.34"))
    assert _assert_public_url("https://example.com/") == "93.184.216.34"


def test_http_get_connects_to_pinned_ip_with_original_host_header(monkeypatch):
    seen = {}

    class FakeSession:
        trust_env = True

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def mount(self, prefix, adapter):
            seen["adapter_host"] = adapter._hostname

        def get(self, url, **kwargs):
            seen["url"], seen["kwargs"] = url, kwargs
            return "resp"

    monkeypatch.setattr(tools.requests, "Session", FakeSession)
    assert tools._http_get("https://example.com:8443/p?q=1", "93.184.216.34", {"A": "b"}) == "resp"
    assert seen["url"] == "https://93.184.216.34:8443/p?q=1"
    assert seen["kwargs"]["headers"] == {"A": "b", "Host": "example.com:8443"}
    assert seen["kwargs"]["allow_redirects"] is False
    assert seen["adapter_host"] == "example.com"


def test_http_get_brackets_ipv6(monkeypatch):
    urls = []

    class FakeSession:
        trust_env = True

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def mount(self, *a):
            pass

        def get(self, url, **kwargs):
            urls.append(url)

    monkeypatch.setattr(tools.requests, "Session", FakeSession)
    tools._http_get("https://example.com/", "2606:2800:220:1::1", {})
    assert urls == ["https://[2606:2800:220:1::1]/"]


def test_unresolvable_host_is_rejected(monkeypatch):
    def boom(*a, **k):
        raise socket.gaierror("nope")
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    with pytest.raises(UnsafeURLError):
        _assert_public_url("https://does-not-exist.invalid/")


def test_redirect_to_internal_address_is_blocked(monkeypatch):
    """A public URL that redirects to a private one must be refused."""
    def resolver(host, port, proto=0):
        ip = "93.184.216.34" if host == "public.example" else "10.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
    monkeypatch.setattr(socket, "getaddrinfo", resolver)

    class Resp:
        is_redirect = True
        is_permanent_redirect = False
        headers = {"Location": "http://internal.example/secret"}

        def close(self):
            pass

    monkeypatch.setattr(tools, "_http_get", lambda *a, **k: Resp())
    with pytest.raises(UnsafeURLError):
        tools._safe_get("https://public.example/", {})


def test_scrape_url_returns_blocked_message_instead_of_raising():
    out = scrape_url.invoke({"url": "file:///etc/passwd"})
    assert out.startswith("Blocked URL")


def test_web_search_handles_empty_and_failing_search(monkeypatch):
    monkeypatch.setattr(tools.tavily, "search", lambda **k: {"results": []})
    assert tools.web_search.invoke({"query": "x"}) == "No search results found."

    def fail(**k):
        raise RuntimeError("down")
    monkeypatch.setattr(tools.tavily, "search", fail)
    assert tools.web_search.invoke({"query": "x"}).startswith("Search failed")


def test_web_search_formats_results(monkeypatch):
    monkeypatch.setattr(tools.tavily, "search", lambda **k: {"results": [
        {"title": "T", "url": "https://a.com", "content": "c" * 500}]})
    out = tools.web_search.invoke({"query": "x"})
    assert "Title: T" in out and "URL: https://a.com" in out
    assert "c" * 250 in out and "c" * 251 not in out


class _FakeResponse:
    def __init__(self, chunks, content_type="text/html; charset=utf-8"):
        self._chunks = chunks
        self.headers = {"Content-Type": content_type}
        self.encoding = "utf-8"
        self.closed = False

    def iter_content(self, chunk_size=0):
        yield from self._chunks

    def close(self):
        self.closed = True


def test_read_html_rejects_binary_content_types():
    with pytest.raises(UnsafeURLError):
        tools._read_html(_FakeResponse([b"%PDF"], "application/pdf"))


def test_read_html_caps_download_size():
    chunk = b"a" * (512 * 1024)
    resp = _FakeResponse([chunk] * 100)  # would be 50 MB
    text = tools._read_html(resp)
    assert len(text) <= tools.MAX_DOWNLOAD_BYTES
    assert resp.closed


def test_scrape_url_extracts_article_text(monkeypatch):
    article = "<html><body><article><p>" + ("Hello world. " * 60) + "</p></article></body></html>"

    class Resp(_FakeResponse):
        def raise_for_status(self):
            pass

    monkeypatch.setattr(tools, "_safe_get", lambda url, headers: Resp([article.encode()]))
    out = scrape_url.invoke({"url": "https://example.com"})
    assert out.startswith("Hello world.")
    assert len(out) <= tools.MAX_SCRAPE_CHARS


def test_scrape_url_reports_blocked_content_type(monkeypatch):
    class Resp(_FakeResponse):
        def raise_for_status(self):
            pass

    monkeypatch.setattr(tools, "_safe_get", lambda url, headers: Resp([b"x"], "application/zip"))
    assert scrape_url.invoke({"url": "https://example.com"}).startswith("Blocked URL")


class _OkResp(_FakeResponse):
    def raise_for_status(self):
        pass


def _serve(monkeypatch, html):
    monkeypatch.setattr(tools, "_safe_get", lambda url, headers: _OkResp([html.encode()]))


def test_scrape_falls_back_to_readability_then_plain_text(monkeypatch):
    # trafilatura finds no article, readability finds <200 chars, plain-text fallback is used.
    _serve(monkeypatch, "<html><body><nav>menu</nav><div>short page</div></body></html>")
    monkeypatch.setattr(tools.trafilatura, "extract", lambda *a, **k: None)
    assert scrape_url.invoke({"url": "https://example.com"}) == "short page"


def test_scrape_uses_readability_when_trafilatura_fails(monkeypatch):
    body = "<html><body><div><p>" + ("Readable sentence. " * 30) + "</p></div></body></html>"
    _serve(monkeypatch, body)
    monkeypatch.setattr(tools.trafilatura, "extract", lambda *a, **k: None)
    assert scrape_url.invoke({"url": "https://example.com"}).startswith("Readable sentence.")


def test_scrape_empty_page_reports_nothing_extracted(monkeypatch):
    _serve(monkeypatch, "<html><body><script>x()</script></body></html>")
    monkeypatch.setattr(tools.trafilatura, "extract", lambda *a, **k: None)
    assert "Could not extract" in scrape_url.invoke({"url": "https://example.com"})


@pytest.mark.parametrize("exc,expected", [
    (tools.requests.exceptions.Timeout(), "timed out"),
    (tools.requests.exceptions.HTTPError("404"), "HTTP error"),
    (tools.requests.exceptions.SSLError("bad cert"), "certificate"),
    (tools.requests.exceptions.ConnectionError("down"), "Could not connect"),
    (RuntimeError("weird"), "Could not scrape URL"),
])
def test_scrape_maps_failures_to_messages(monkeypatch, exc, expected):
    def boom(url, headers):
        raise exc
    monkeypatch.setattr(tools, "_safe_get", boom)
    assert expected in scrape_url.invoke({"url": "https://example.com"})


def test_safe_get_follows_safe_redirects_and_limits_hops(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_resolver("93.184.216.34"))

    class Redirect:
        is_redirect = True
        is_permanent_redirect = False
        headers = {"Location": "/next"}

        def close(self):
            pass

    class Final:
        is_redirect = False
        is_permanent_redirect = False
        headers = {}

    seq = iter([Redirect(), Final()])
    monkeypatch.setattr(tools, "_http_get", lambda *a, **k: next(seq))
    assert isinstance(tools._safe_get("https://a.example/", {}), Final)

    monkeypatch.setattr(tools, "_http_get", lambda *a, **k: Redirect())
    with pytest.raises(UnsafeURLError):
        tools._safe_get("https://a.example/", {})  # redirect loop
