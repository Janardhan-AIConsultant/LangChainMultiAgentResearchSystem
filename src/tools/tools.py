import ipaddress
import logging
import os
import re
import socket
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import trafilatura
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from langchain.tools import tool
from readability import Document
from requests.adapters import HTTPAdapter
from tavily import TavilyClient

logger = logging.getLogger(__name__)

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

@tool
def web_search(query: str) -> str:
    """Search the web for recent and reliable information on a topic . Returns Titles , URLs and snippets."""
    try:
        results = tavily.search(query=query, max_results=3)
    except Exception as e:
        logger.exception("Tavily search failed")
        return f"Search failed: {e}"

    out = [
        f"Title: {r['title']}\nURL: {r['url']}\nSnippet: {r['content'][:250]}\n"
        for r in results.get("results", [])
    ]
    if not out:
        return "No search results found."
    return "\n----\n".join(out)


MAX_REDIRECTS = 5
MAX_SCRAPE_CHARS = 2500
MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024  # never read more than 2 MB of a page
ALLOWED_CONTENT_TYPES = ("text/", "application/xhtml")
MIN_USEFUL_CHARS = 200
NOISE_TAGS = ["script", "style", "nav", "footer", "header", "aside", "form"]


def _visible_text(html: str) -> str:
    """Strip noise tags from HTML and return whitespace-collapsed text."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(NOISE_TAGS):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(separator=" ", strip=True))


class UnsafeURLError(ValueError):
    """Raised when a URL is not a public http(s) address."""


def _assert_public_url(url: str) -> str:
    """Allow only http(s) URLs whose host resolves exclusively to public IPs.

    The URL is chosen by an LLM from untrusted web content, so it must not be
    able to reach localhost, private networks or cloud metadata endpoints.
    Returns the validated IP address so the caller can connect to exactly that
    address (this closes the DNS-rebinding window between check and connect).
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError("Only http and https URLs can be scraped.")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL has no host.")

    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise UnsafeURLError(f"Could not resolve host: {host}") from None

    ips = [ipaddress.ip_address(info[4][0]) for info in infos]
    if not ips or not all(ip.is_global for ip in ips):  # private, loopback, link-local, ...
        raise UnsafeURLError("Refusing to scrape a non-public address.")
    return str(ips[0])


class _PinnedHostAdapter(HTTPAdapter):
    """Connect to a pre-validated IP while verifying TLS against the real hostname."""

    def __init__(self, hostname: str, **kwargs):
        """Remember the real hostname that TLS must be verified against."""
        self._hostname = hostname
        super().__init__(**kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        """Set the TLS server name and certificate check to the real host, not the pinned IP."""
        pool_kwargs["server_hostname"] = self._hostname  # SNI
        pool_kwargs["assert_hostname"] = self._hostname  # certificate check
        super().init_poolmanager(connections, maxsize, block, **pool_kwargs)


def _http_get(url: str, ip: str, headers: dict) -> requests.Response:
    """GET `url` by connecting to `ip` (already validated), streamed, no redirects."""
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL has no host.")
    netloc_ip = f"[{ip}]" if ":" in ip else ip
    if parsed.port:
        netloc_ip += f":{parsed.port}"
    pinned_url = parsed._replace(netloc=netloc_ip).geturl()
    host_header = host + (f":{parsed.port}" if parsed.port else "")

    with requests.Session() as session:
        session.trust_env = False  # ignore proxy env vars: we must reach the pinned IP directly
        session.mount("https://", _PinnedHostAdapter(host))
        return session.get(
            pinned_url,
            headers={**headers, "Host": host_header},
            timeout=15,
            allow_redirects=False,
            stream=True,
        )


def _safe_get(url: str, headers: dict) -> requests.Response:
    """GET a URL, validating the initial URL and every redirect hop."""
    for _ in range(MAX_REDIRECTS + 1):
        ip = _assert_public_url(url)
        response = _http_get(url, ip, headers)
        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location")
            if not location:
                return response
            response.close()
            url = urljoin(url, location)
            continue
        return response
    raise UnsafeURLError("Too many redirects.")


def _read_html(response: requests.Response) -> str:
    """Return the page body as text, refusing non-text types and capping the size."""
    content_type = response.headers.get("Content-Type", "").lower()
    if content_type and not content_type.startswith(ALLOWED_CONTENT_TYPES):
        raise UnsafeURLError(f"Unsupported content type: {content_type.split(';')[0]}")

    body = bytearray()
    try:
        for chunk in response.iter_content(chunk_size=64 * 1024):
            body.extend(chunk)
            if len(body) >= MAX_DOWNLOAD_BYTES:
                break  # enough to extract the article; avoid huge downloads
    finally:
        response.close()
    return bytes(body[:MAX_DOWNLOAD_BYTES]).decode(response.encoding or "utf-8", errors="replace")


@tool
def scrape_url(url: str) -> str:
    """
    Scrape and extract clean readable content from a URL.
    Uses multiple extraction strategies for better reliability.
    """

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/",
    }

    try:
        # ── Fetch page (public http/https only, redirects re-checked) ──
        response = _safe_get(url, headers)

        response.raise_for_status()

        html = _read_html(response)

        # Strategy 1 -> trafilatura (best for articles/blogs)
        extracted = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False
        )
        if extracted and len(extracted.strip()) > MIN_USEFUL_CHARS:
            return re.sub(r"\s+", " ", extracted)[:MAX_SCRAPE_CHARS]

        # Strategy 2 -> readability main-content extraction
        text = _visible_text(Document(html).summary())
        if len(text) > MIN_USEFUL_CHARS:
            return text[:MAX_SCRAPE_CHARS]

        # Strategy 3 -> fallback: whole page text
        text = _visible_text(html)
        if text:
            return text[:MAX_SCRAPE_CHARS]

        return "Could not extract meaningful content from the page."

    except UnsafeURLError as e:
        return f"Blocked URL: {e}"

    except requests.exceptions.Timeout:
        return "Request timed out while scraping the URL."

    except requests.exceptions.SSLError:
        return "TLS certificate verification failed for this site."

    except requests.exceptions.ConnectionError:
        return "Could not connect to the site."

    except requests.exceptions.HTTPError as e:
        # Report the original URL, not the pinned-IP URL requests saw.
        status = e.response.status_code if e.response is not None else "unknown"
        return f"HTTP error occurred: {status} for {url}"

    except Exception as e:
        logger.exception("Unexpected error scraping %s", url)
        return f"Could not scrape URL: {str(e)}"
