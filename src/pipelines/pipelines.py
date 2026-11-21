from src.agents.agents import build_search_agent, build_reader_agent, writer_chain, critic_chain

import time
import openai

def _with_retry(fn, payload, retries=5):
    """Call fn(payload); on Groq rate/size-per-minute errors (413/429) wait and retry."""
    for attempt in range(retries):
        try:
            return fn(payload)
        except openai.APIStatusError as e:
            unfixable = "expected output tokens exceed" in str(e)  # waiting won't help
            if e.status_code not in (413, 429) or unfixable or attempt == retries - 1:
                raise
            wait = 20 * (attempt + 1)
            print(f"[rate limit hit - waiting {wait}s, retry {attempt + 1}/{retries - 1}]")
            time.sleep(wait)


def run_research_pipeline(topic : str, on_step=None) -> dict:
    """Run search -> read -> write -> critic.

    on_step(key, status, data) is an optional progress callback used by the UI;
    key is one of search/read/write/critic, status is "running" or "done".
    """

    def emit(key, status, data=None):
        if on_step:
            on_step(key, status, data)

    state = {}

    #search agent working
    print("\n"+"="*50)
    print("step 1 - search agent is working ...")
    print("="*50)
    emit("search", "running")

    search_agent = build_search_agent()
    search_result = _with_retry(search_agent.invoke, {
        "messages" : [("user", f"Find recent, reliable and detailed information about: {topic}")]})
    state["search_results"] = search_result['messages'][-1].content

    print("\n search result ",state['search_results'])
    emit("search", "done", state["search_results"])


    #step 2 - reader agent 
    print("\n"+"="*50)
    print("step 2 - Reader agent is scraping top resources ...")
    print("="*50)
    emit("read", "running")

    reader_agent = build_reader_agent()
    reader_result = _with_retry(reader_agent.invoke, {
        "messages": [("user",
            f"Based on the following search results about '{topic}', "
            f"pick the most relevant URL and scrape it for deeper content.\n\n"
            f"Search Results:\n{state['search_results'][:800]}"
        )]
    })

    state['scraped_content'] = reader_result['messages'][-1].content

    print("\nscraped content: \n", state['scraped_content'])
    emit("read", "done", state["scraped_content"])


    #step 3 - writer chain 

    print("\n"+"="*50)
    print("step 3 - Writer is drafting the report ...")
    print("="*50)
    emit("write", "running")

    research_combined = (
        f"SEARCH RESULTS : \n {state['search_results']} \n\n"
        f"DETAILED SCRAPED CONTENT : \n {state['scraped_content']}"
    )

    state["report"] = _with_retry(writer_chain.invoke, {
        "topic" : topic,
        "research" : research_combined
    })

    print("\n Final Report\n",state['report'])
    emit("write", "done", state["report"])


    #critic report 

    print("\n"+"="*50)
    print("step 4 - critic is reviewing the report ")
    print("="*50)
    emit("critic", "running")

    state["feedback"] = _with_retry(critic_chain.invoke, {
        "report":state['report']
    })

    print("\n critic report \n", state['feedback'])
    emit("critic", "done", state["feedback"])

    return state