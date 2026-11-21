# API Reference

Developer reference for the modules in `src/`. For setup and usage see the [README](../README.md).

**Audience:** developers extending or debugging the pipeline.

## Contents

- [Data flow](#data-flow)
- [`src.pipelines.pipelines`](#srcpipelinespipelines)
- [`src.agents.agents`](#srcagentsagents)
- [`src.tools.tools`](#srctoolstools)
- [`src.app` (Streamlit UI helpers)](#srcapp-streamlit-ui-helpers)
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

The pipeline returns a single `state` dictionary holding every intermediate result.

---

## `src.pipelines.pipelines`

### `run_research_pipeline(topic, on_step=None) -> dict`

Runs the four steps in order: search, read, write, critic.

| Parameter | Type | Description |
|-----------|------|-------------|
| `topic` | `str` | The subject to research. |
| `on_step` | `Callable[[str, str, str \| None], None]`, optional | Progress callback, called as `on_step(key, status, data)`. |

**Callback arguments**

| Argument | Values |
|----------|--------|
| `key` | `"search"`, `"read"`, `"write"`, `"critic"` |
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

- The Reader Agent receives only the **first 800 characters** of `search_results` when choosing a URL.
- The pipeline prints each step's output to stdout, which is what ends up in the Streamlit terminal logs.
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

### `_with_retry(fn, payload, retries=5)`

Internal helper. Calls `fn(payload)` and retries when the Groq API returns HTTP **413** or **429**, waiting `20 * attempt` seconds between attempts (20s, 40s, 60s, 80s). It re-raises immediately for any other status code, when the error says expected output tokens exceed the limit (waiting cannot fix that), or on the last attempt.

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

Output is whitespace-collapsed and truncated to **2500 characters**. On failure it returns an error string instead of raising:

| Situation | Returned text |
|-----------|---------------|
| Timeout | `Request timed out while scraping the URL.` |
| HTTP error | `HTTP error occurred: ...` |
| Nothing extractable | `Could not extract meaningful content from the page.` |
| Any other exception | `Could not scrape URL: ...` |

---

## `src.app` (Streamlit UI helpers)

`src/app.py` runs on import (it is a Streamlit script), so these helpers are documented for maintainers rather than for reuse.

| Function | Purpose |
|----------|---------|
| `steps_html(states)` | Renders the four step cards as HTML from a `{key: state}` map. |
| `extract_urls(*texts)` | Returns de-duplicated URLs found in the given texts, in order. |
| `parse_score(feedback)` | Extracts the numeric score from `Score: X/10`; returns `None` if absent. |
| `host_of(url)` | Returns the host without `www.`, used for source labels. |
| `score_color(score)` | CSS color: green at 8 or above, amber at 6 or above, red below. |
| `fmt_seconds(sec)` | Formats a duration, `"45s"` or `"2m 5s"`. |
| `run_pipeline(topic, steps_slot, status_slot)` | Runs the pipeline with live UI updates; returns `(state, seconds)`. On error it marks the running step as failed and re-raises. |

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
| Search results per query | 3 | `web_search` |
| Snippet length | 250 characters | `web_search` |
| Scraped text length | 2500 characters | `scrape_url` |
| Search text passed to Reader | 800 characters | `run_research_pipeline` |
| Output tokens per request | 900 (configurable) | `GROQ_MAX_TOKENS` |
| Retries on 413 / 429 | 5 attempts, 20s step backoff | `_with_retry` |

The 900-token output cap is tuned to Groq's free-tier tokens-per-minute limit, so long reports may be cut short. Raise `GROQ_MAX_TOKENS` if your plan allows it.
