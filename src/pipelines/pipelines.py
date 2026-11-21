import logging
import time

import openai

from src.agents.agents import build_reader_agent, build_search_agent, critic_chain, writer_chain

logger = logging.getLogger(__name__)

MAX_TOPIC_LENGTH = 300
RETRY_BACKOFF_SECONDS = 20


def _with_retry(fn, payload, retries=5, on_wait=None):
    """Call fn(payload); on Groq rate/size-per-minute errors (413/429) wait and retry.

    on_wait(message) is an optional callback invoked before each wait so the UI
    can tell the user why the run is paused.
    """
    for attempt in range(retries):
        try:
            return fn(payload)
        except openai.APIConnectionError as e:  # network blip or timeout
            if attempt == retries - 1:
                raise
            wait = RETRY_BACKOFF_SECONDS
            message = f"Connection problem ({type(e).__name__}) - waiting {wait}s, retry {attempt + 1}/{retries - 1}"
            logger.warning(message)
            if on_wait:
                on_wait(message)
            time.sleep(wait)
        except openai.APIStatusError as e:
            unfixable = "expected output tokens exceed" in str(e)  # waiting won't help
            if e.status_code not in (413, 429) or unfixable or attempt == retries - 1:
                raise
            wait = RETRY_BACKOFF_SECONDS * (attempt + 1)
            message = f"Rate limit hit - waiting {wait}s, retry {attempt + 1}/{retries - 1}"
            logger.warning(message)
            if on_wait:
                on_wait(message)
            time.sleep(wait)


def validate_topic(topic: str) -> str:
    """Return the stripped topic, or raise ValueError if it is empty or too long."""
    clean = (topic or "").strip()
    if not clean:
        raise ValueError("Topic must not be empty.")
    if len(clean) > MAX_TOPIC_LENGTH:
        raise ValueError(f"Topic is too long (max {MAX_TOPIC_LENGTH} characters).")
    return clean


def run_research_pipeline(topic: str, on_step=None) -> dict:
    """Run search -> read -> write -> critic.

    on_step(key, status, data) is an optional progress callback used by the UI;
    key is one of search/read/write/critic, status is "running" or "done".
    key "notice" (status "running", data = message) reports a retry wait.
    """
    topic = validate_topic(topic)

    def emit(key, status, data=None):
        if on_step:
            on_step(key, status, data)

    def notify(message):
        emit("notice", "running", message)

    state = {}

    # step 1 - search agent
    logger.info("step 1/4 - search agent working (topic=%r)", topic)
    emit("search", "running")

    search_agent = build_search_agent()
    search_result = _with_retry(search_agent.invoke, {
        "messages": [("user", f"Find recent, reliable and detailed information about: {topic}")]},
        on_wait=notify)
    state["search_results"] = search_result["messages"][-1].content

    logger.debug("search results:\n%s", state["search_results"])
    emit("search", "done", state["search_results"])

    # step 2 - reader agent
    logger.info("step 2/4 - reader agent scraping top resources")
    emit("read", "running")

    reader_agent = build_reader_agent()
    reader_result = _with_retry(reader_agent.invoke, {
        "messages": [("user",
            f"Based on the following search results about '{topic}', "
            f"pick the most relevant URL and scrape it for deeper content.\n\n"
            f"Search Results:\n{state['search_results']}"
        )]
    }, on_wait=notify)

    state["scraped_content"] = reader_result["messages"][-1].content

    logger.debug("scraped content:\n%s", state["scraped_content"])
    emit("read", "done", state["scraped_content"])

    # step 3 - writer chain
    logger.info("step 3/4 - writer drafting the report")
    emit("write", "running")

    research_combined = (
        f"SEARCH RESULTS : \n {state['search_results']} \n\n"
        f"DETAILED SCRAPED CONTENT : \n {state['scraped_content']}"
    )

    state["report"] = _with_retry(writer_chain.invoke, {
        "topic": topic,
        "research": research_combined
    }, on_wait=notify)

    logger.debug("final report:\n%s", state["report"])
    emit("write", "done", state["report"])

    # step 4 - critic chain
    logger.info("step 4/4 - critic reviewing the report")
    emit("critic", "running")

    state["feedback"] = _with_retry(critic_chain.invoke, {
        "report": state["report"]
    }, on_wait=notify)

    logger.debug("critic feedback:\n%s", state["feedback"])
    emit("critic", "done", state["feedback"])

    logger.info("pipeline finished")
    return state
