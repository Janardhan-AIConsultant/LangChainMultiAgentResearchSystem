# Nexus Research — LangChain Multi-Agent Research System

A team of four AI agents that researches a topic end to end: it searches the web, reads the best source, writes a structured report, and then critiques and scores it. It ships with a Streamlit UI that shows each agent's progress live.

## Screenshot

![Nexus Research UI](docs/ui-screenshot.png)

## Pipeline

1. **Search Agent** — finds relevant sources with Tavily web search.
2. **Reader Agent** — scrapes the best page (BeautifulSoup / trafilatura / readability).
3. **Writer** — drafts a structured report from the gathered material.
4. **Critic** — reviews the report and gives a score with feedback.

The LLM is served through Groq's OpenAI-compatible API.

## Application flow

```mermaid
flowchart TD
    U([👤 User enters a research topic]) --> UI["🖥️ Streamlit UI<br/>src/app.py"]
    UI -->|run_research_pipeline| P["⚙️ Pipeline<br/>src/pipelines/pipelines.py"]

    P --> S["🔎 1. Search Agent"]
    S <-->|web_search| T1[("Tavily Search API")]
    S -->|search results| R["📖 2. Reader Agent"]
    R <-->|scrape_url| T2[("Best source page<br/>BeautifulSoup / trafilatura")]
    R -->|scraped content| W["✍️ 3. Writer chain"]
    S -.->|search results| W
    W -->|structured report| C["🧐 4. Critic chain"]
    C -->|score + feedback| OUT

    LLM{{"🧠 Groq LLM<br/>OpenAI-compatible API"}}
    S -.- LLM
    R -.- LLM
    W -.- LLM
    C -.- LLM

    RETRY["🔁 Auto-retry on 413 / 429<br/>rate limits (up to 5×)"]
    P -.- RETRY

    OUT(["📄 Report + critic score"]) --> UI
    UI --> H[("🗂️ Sidebar history")]

    P -. live step updates .-> UI

    classDef agent fill:#7c5cff,stroke:#4c3bb0,color:#fff;
    classDef ext fill:#22d3ee,stroke:#0e7490,color:#06222a;
    classDef io fill:#f472b6,stroke:#9d2c6b,color:#2a0716;
    class S,R,W,C agent;
    class T1,T2,LLM ext;
    class U,OUT,H io;
```

| Step | Component | Input | Output |
|------|-----------|-------|--------|
| 1 | Search Agent | Topic | Search results (links + snippets) |
| 2 | Reader Agent | Search results | Scraped content of the best page |
| 3 | Writer | Search results + scraped content | Structured report |
| 4 | Critic | Report | Score and feedback |

Each step reports `running` / `done` back to the UI, which is what drives the live progress cards.

## Project structure

```
├── main.py                  # CLI entry point (runs one topic)
├── requirements.txt
├── .streamlit/config.toml   # Forces the dark theme
└── src/
    ├── app.py               # Streamlit UI
    ├── .env                 # API keys and model settings (not committed)
    ├── agents/agents.py     # LLM setup, search and reader agents
    ├── pipelines/pipelines.py  # run_research_pipeline (with retry logic)
    └── tools/tools.py       # web_search (Tavily) and scrape_url
```

## Setup

```bash
conda create -n langagent python=3.11 -y
conda activate langagent
pip install -r requirements.txt
```

Alternatively, use a plain virtual environment:

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration

Create `src/.env` (it is git-ignored, so keys are never committed):

```env
TAVILY_API_KEY=your-tavily-key
GROQ_API_KEY=your-groq-key
GROQ_MODEL=your-groq-model-name
GROQ_BASE_URL=https://api.groq.com/openai/v1
GROQ_TEMPERATURE=0
# Optional (defaults to 900)
GROQ_MAX_TOKENS=900
```

## Run

**Web UI (recommended)** — from the project root:

```bash
streamlit run src/app.py
```

Then open http://localhost:8501. Enter a topic and watch the four agents work; past runs appear in the sidebar history.

**Command line:**

```bash
python main.py
```

Edit the `topic` variable in `main.py` to change what gets researched.

## Notes

- Logs are printed to the terminal where Streamlit is running.
- `__pycache__/`, `venv/` and `.env` are listed in `.gitignore`.
- Optionally set `PYTHONDONTWRITEBYTECODE=1` to stop Python from creating `__pycache__` folders.
