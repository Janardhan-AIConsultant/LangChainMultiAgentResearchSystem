# API Reference

Developer reference for the modules in `src/`. For setup and usage see the [README](../README.md).

**Audience:** developers extending or debugging the pipeline.

## Contents

- [Data flow](#data-flow)
- [`src.pipelines.pipelines`](#srcpipelinespipelines)
- [`src.agents.agents`](#srcagentsagents)
- [`src.tools.tools`](#srctoolstools)
- [`src.helpers`](#srchelpers)
- [`src.app` (Streamlit UI)](#srcapp-streamlit-ui)
- [Configuration](#configuration)
- [Limits and error handling](#limits-and-error-handling)

---

## Data flow

```
topic ──► Search Agent ──► search_results ──► Reader Agent ──► scraped_content
                                  │                                  │
                                  └──────────────┬───────────────────┘
                                                 ▼
                                          Writer chain ──► report ──► Critic chain ──► feedback
```

The pipeline returns a single `state` dictionary holding every intermediate result. The topic is validated first (see `validate_topic`), and every LLM call is wrapped in `_with_retry`.

For a one-page visual of the flow and its guards, see the [application flow infographic](application-flow.png).

---

## `src.pipelines.pipelines`

### `run_research_pipeline(topic, on_step=None) -> dict`

Runs the four steps in order: search, read, write, critic.

| Parameter | Type | Description |
|-----------|------|-------------|
| `topic` | `str` | The subject to research. |
| `on_step` | `Callable[[str, str, str \| None], None]`, optional | Progress callback, called as `on_step(key, status, data)`. |

Raises `ValueError` if the topic is empty or longer than 300 characters.

**Callback arguments**

| Argument | Values |
|----------|--------|
| `key` | `"search"`, `"read"`, `"write"`, `"critic"`, or `"notice"` (a retry wait; `status="running"`, `data` is the message) |
| `status` | `"running"` when the step starts, `"done"` when it finishes |
| `data` | `None` for `running`; the step's text output for `done` |

**Returns** a `dict` with these keys:

| Key | Type | Produced by |
|-----|------|-------------|
| `search_results` | `str` | Search Agent (titles, URLs, snippets) |
| `scraped_content` | `str` | Reader Agent (cleaned page text) |
| `report` | `str` | Writer chain |
| `feedback` | `str` | Critic chain (`Score: X/10`, strengths, improvements, verdict) |

**Notes**

- The Reader Agent receives the full `search_results` text (at most 3 results of about 300 characters each) when choosing a URL.
- Progress is written with the standard `logging` module (INFO per step, DEBUG for full step output, WARNING on retries).
- Exceptions from a step propagate to the caller; the callback is not called with an error status. The UI marks the running step as failed itself.

**Example**

```python
from src.pipelines.pipelines import run_research_pipeline

state = run_research_pipeline(
    "The impact of AI on the job market in 2026",
    on_step=lambda key, status, data: print(key, status),
)
print(state["report"])
print(state["feedback"])
```

### `validate_topic(topic) -> str`

Returns the stripped topic; raises `ValueError` if it is empty or over 300 characters.

### `_with_retry(fn, payload, retries=5, on_wait=None)`

Internal helper. Calls `fn(payload)` and retries in two cases:

| Error | Wait before retry |
|-------|-------------------|
| Groq API returns HTTP **413** or **429** | `20 * attempt` seconds (20s, 40s, 60s, 80s) |
| Connection error or timeout (`openai.APIConnectionError`) | fixed 20s |

`on_wait(message)` is called before each wait so the UI can explain the pause. It re-raises immediately for any other status code, when the error says expected output tokens exceed the limit (waiting cannot fix that), and on the last attempt.

---

## `src.agents.agents`

Importing this module loads `src/.env` and creates the shared LLM client, so `GROQ_MODEL`, `GROQ_API_KEY` and `GROQ_BASE_URL` must be set or the import raises `KeyError`.

### `llm`

A `ChatOpenAI` client pointed at Groq's OpenAI-compatible endpoint, shared by all four steps. See [Configuration](#configuration) for the environment variables that control it.

### `build_search_agent()`

Returns a LangChain agent (`create_agent`) with the `web_search` tool.

### `build_reader_agent()`

Returns a LangChain agent with the `scrape_url` tool.

Both builders return a new agent on every call. Invoke them with `{"messages": [("user", "...")]}` and read the answer from `result["messages"][-1].content`.

### `writer_chain`

`ChatPromptTemplate | llm | StrOutputParser`. Input keys: `topic`, `research`. Output: a report string structured as Introduction, Key Findings (at least 3), Conclusion, Sources.

### `critic_chain`

`ChatPromptTemplate | llm | StrOutputParser`. Input key: `report`. Output follows a fixed format:

```
Score: X/10

Strengths:
- ...

Areas to Improve:
- ...

One line verdict:
...
```

The UI parses the score from the `Score: X/10` line, so keep that line format if you edit the prompt.

---

## `src.tools.tools`

Importing this module loads `src/.env` and creates a Tavily client from `TAVILY_API_KEY`.

### `web_search(query: str) -> str`

LangChain tool. Searches Tavily for up to **3** results and returns them separated by `----`, each as:

```
Title: ...
URL: ...
Snippet: ...   (first 250 characters)
```

### `scrape_url(url: str) -> str`

LangChain tool. Fetches the page (15 second timeout, browser-like headers) and extracts readable text using three strategies in order, returning the first that yields more than 200 characters:

1. **trafilatura**, best for articles and blogs.
2. **readability + BeautifulSoup**, with script, style, nav, footer, header, aside and form tags removed.
3. **Raw BeautifulSoup** extraction of the whole page, with the same tags removed.

Output is whitespace-collapsed and truncated to **2500 characters**. Only text content types (`text/*`, `application/xhtml*`) are accepted, and at most **2 MB** of a page is downloaded.

**URL safety:** because the URL is chosen by an LLM from untrusted search content, only `http` and `https` URLs whose host resolves to public IP addresses are fetched. Localhost, private networks and link-local/metadata addresses are refused. Redirects are followed manually (up to 5) and every hop is re-checked. The connection goes to the validated IP address (the original hostname is sent as the `Host` header and used for TLS SNI and certificate verification), which prevents DNS-rebinding bypasses. Proxy environment variables are not used for scraping.

On failure it returns an error string instead of raising:

| Situation | Returned text |
|-----------|---------------|
| Non-public or non-http(s) URL, unsupported content type, too many redirects | `Blocked URL: ...` |
| Timeout | `Request timed out while scraping the URL.` |
| HTTP error | `HTTP error occurred: <status> for <url>` |
| TLS certificate problem | `TLS certificate verification failed for this site.` |
| Connection failure | `Could not connect to the site.` |
| Nothing extractable | `Could not extract meaningful content from the page.` |
| Any other exception | `Could not scrape URL: ...` (logged with a traceback) |

### Internal helpers (scraping)

| Name | Purpose |
|------|---------|
| `UnsafeURLError` | Raised (and turned into `Blocked URL: ...`) when a URL fails a safety check. |
| `_assert_public_url(url) -> str` | Checks scheme and host, resolves the host once, requires every address to be public, and returns the validated IP. |
| `_PinnedHostAdapter` | `requests` adapter that sets TLS SNI and certificate checking to the original hostname while connecting to the pinned IP. |
| `_http_get(url, ip, headers)` | One streamed GET to the validated IP with the original `Host` header; no redirects, no proxy environment variables. |
| `_safe_get(url, headers)` | Follows up to 5 redirects manually, running `_assert_public_url` and `_http_get` for every hop. |
| `_read_html(response)` | Rejects non-text content types, reads at most 2 MB, closes the connection and decodes the body. |
| `_visible_text(html)` | Removes script, style, nav, footer, header, aside and form tags and collapses whitespace. |

---

## `src.helpers`

Pure functions used by the UI (no Streamlit imports, covered by unit tests).

| Function | Purpose |
|----------|---------|
| `extract_urls(*texts)` | Returns de-duplicated `http(s)` URLs found in the given texts, in order. |
| `parse_score(feedback)` | Extracts the numeric score from `Score: X/10` (also `Score: **X**/10`); returns `None` if absent. |
| `host_of(url)` | Returns the host without `www.`, used for source labels. |
| `score_color(score)` | CSS color: green at 8 or above, amber at 6 or above, red below. |
| `fmt_seconds(sec)` | Formats a duration, `"45s"` or `"2m 5s"`. |

---

## `src.app` (Streamlit UI)

`src/app.py` runs on import (it is a Streamlit script), so it is documented for maintainers rather than for reuse.

- `steps_html(states)` renders the four step cards.
- `run_pipeline(topic, steps_slot, status_slot)` runs the pipeline with live UI updates and returns `(state, seconds)`. On error it marks the running step as failed and re-raises. Retry waits arrive through the `"notice"` callback key and are shown as a warning.
- Errors are logged with a traceback. The UI shows a hint for rate limits (`openai.APIStatusError` 413/429) and for authentication or missing-setting errors (`openai.AuthenticationError`, `KeyError`).
- The topic input is capped at 300 characters.

UI state is kept in `st.session_state`: `topic`, `result` and `history`. History lives only for the browser session and is lost on refresh.

---

## Configuration

Set in `src/.env`:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GROQ_API_KEY` | yes | none | Groq API key. |
| `GROQ_MODEL` | yes | none | Model name passed to the API. |
| `GROQ_BASE_URL` | yes | none | OpenAI-compatible endpoint URL. |
| `GROQ_TEMPERATURE` | no | `0` | Sampling temperature. |
| `GROQ_MAX_TOKENS` | no | `900` | Max output tokens per request. |
| `TAVILY_API_KEY` | yes | none | Tavily search key. |

Never commit `src/.env`; it is git-ignored.

---

## Limits and error handling

| Limit | Value | Where |
|-------|-------|-------|
| Topic length | 300 characters | `validate_topic`, UI input |
| Search results per query | 3 | `web_search` |
| Snippet length | 250 characters | `web_search` |
| Page download size | 2 MB | `_read_html` |
| Scraped text length | 2500 characters | `scrape_url` |
| Page request timeout | 15 seconds | `_http_get` |
| Redirects followed | 5, each re-checked | `_safe_get` |
| Output tokens per request | 900 (configurable) | `GROQ_MAX_TOKENS` |
| Retries (413 / 429 / connection errors) | 5 attempts, 20s step backoff (fixed 20s for connection errors) | `_with_retry` |

The 900-token output cap is tuned to Groq's free-tier tokens-per-minute limit, so long reports may be cut short. Raise `GROQ_MAX_TOKENS` if your plan allows it.
