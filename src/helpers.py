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
