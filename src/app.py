"""Streamlit UI for the LangChain multi-agent research system.

Run from the project root:
    streamlit run src/app.py
"""
import html
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# Make `src.*` importable no matter where streamlit is launched from.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import logging

import openai
import streamlit as st

from src.helpers import (
    extract_urls,
    fmt_seconds,
    host_of,
    parse_score,
    running_step,
    score_color,
    strip_markdown_images,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("nexus")

st.set_page_config(
    page_title="Nexus Research",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ───────────────────────────── Theme / CSS ─────────────────────────────
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
  --bg: #07080f;
  --panel: rgba(255,255,255,0.045);
  --panel-b: rgba(255,255,255,0.09);
  --text: #e7e9f3;
  --muted: #8b90a7;
  --a1: #7c5cff;
  --a2: #22d3ee;
  --a3: #f472b6;
  --ok: #34d399;
  --warn: #fbbf24;
  --err: #f87171;
}

html, body, [class*="css"], .stApp { font-family: 'Inter', sans-serif; color: var(--text); }
.stApp {
  background:
    radial-gradient(900px 500px at 12% -8%, rgba(124,92,255,.22), transparent 60%),
    radial-gradient(800px 480px at 95% 0%, rgba(34,211,238,.14), transparent 60%),
    radial-gradient(700px 500px at 50% 110%, rgba(244,114,182,.10), transparent 60%),
    var(--bg);
}
#MainMenu, footer, header[data-testid="stHeader"] { visibility: hidden; height: 0; }
.block-container { padding-top: 2.2rem; padding-bottom: 4rem; max-width: 1180px; }

/* ── Hero ── */
.hero { text-align: center; padding: 1.2rem 0 1.6rem; }
.badge {
  display: inline-flex; align-items: center; gap: .5rem;
  padding: .35rem .85rem; border-radius: 999px; font-size: .78rem; font-weight: 600;
  color: #c9c3ff; background: rgba(124,92,255,.12); border: 1px solid rgba(124,92,255,.35);
  letter-spacing: .02em;
}
.badge .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--ok);
  box-shadow: 0 0 10px var(--ok); animation: pulse 2s infinite; }
.hero h1 {
  font-size: clamp(2.3rem, 5vw, 3.8rem); font-weight: 800; line-height: 1.05;
  letter-spacing: -.035em; margin: 1rem 0 .7rem;
  background: linear-gradient(100deg, #fff 10%, #b4a5ff 45%, #67e8f9 80%);
  -webkit-background-clip: text; background-clip: text; color: transparent;
}
.hero p { color: var(--muted); font-size: 1.05rem; max-width: 640px; margin: 0 auto; line-height: 1.6; }

/* ── Inputs ── */
.stTextArea textarea, .stTextInput input {
  background: rgba(255,255,255,.04) !important; color: var(--text) !important;
  border: 1px solid var(--panel-b) !important; border-radius: 16px !important;
  font-size: 1.05rem !important; padding: 1rem 1.1rem !important;
  transition: border-color .2s, box-shadow .2s;
}
.stTextArea textarea:focus, .stTextInput input:focus {
  border-color: var(--a1) !important; box-shadow: 0 0 0 4px rgba(124,92,255,.18) !important;
}
.stTextArea label, .stTextInput label { display: none; }

/* ── Buttons ── */
.stButton > button, .stDownloadButton > button {
  border-radius: 14px; font-weight: 600; border: 1px solid var(--panel-b);
  background: var(--panel); color: var(--text); transition: all .2s ease; padding: .55rem 1.1rem;
}
.stButton > button:hover, .stDownloadButton > button:hover {
  border-color: var(--a1); transform: translateY(-1px); color: #fff;
  box-shadow: 0 8px 24px -10px rgba(124,92,255,.7);
}
.stButton > button[kind="primary"] {
  border: none; color: #fff; padding: .8rem 1.4rem; font-size: 1rem;
  background: linear-gradient(100deg, var(--a1), #5b8cff 55%, var(--a2));
  box-shadow: 0 10px 30px -10px rgba(124,92,255,.8);
}
.stButton > button[kind="primary"]:hover { filter: brightness(1.1); transform: translateY(-2px); }

/* ── Pipeline stepper ── */
.steps { display: grid; grid-template-columns: repeat(4, 1fr); gap: .9rem; margin: 1.4rem 0 .6rem; }
@media (max-width: 800px) { .steps { grid-template-columns: repeat(2, 1fr); } }
.step {
  position: relative; padding: 1.1rem 1.1rem 1rem; border-radius: 18px;
  background: var(--panel); border: 1px solid var(--panel-b);
  backdrop-filter: blur(14px); transition: all .35s ease; overflow: hidden;
}
.step .ico { font-size: 1.5rem; margin-bottom: .55rem; }
.step .ttl { font-weight: 700; font-size: .98rem; }
.step .sub { color: var(--muted); font-size: .8rem; margin-top: .2rem; line-height: 1.4; }
.step .state { position: absolute; top: .9rem; right: .95rem; font-size: .68rem; font-weight: 700;
  letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
.step.running { border-color: rgba(124,92,255,.7); background: rgba(124,92,255,.10);
  box-shadow: 0 0 0 1px rgba(124,92,255,.25), 0 18px 40px -18px rgba(124,92,255,.8); }
.step.running .state { color: #b4a5ff; }
.step.running::after {
  content: ""; position: absolute; left: 0; bottom: 0; height: 3px; width: 40%;
  background: linear-gradient(90deg, transparent, var(--a2), transparent);
  animation: sweep 1.3s linear infinite;
}
.step.done { border-color: rgba(52,211,153,.45); background: rgba(52,211,153,.06); }
.step.done .state { color: var(--ok); }
.step.error { border-color: rgba(248,113,113,.6); background: rgba(248,113,113,.07); }
.step.error .state { color: var(--err); }

/* ── Cards ── */
.card {
  padding: 1.4rem 1.5rem; border-radius: 20px; background: var(--panel);
  border: 1px solid var(--panel-b); backdrop-filter: blur(14px);
}
.stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: .9rem; margin: 1.2rem 0; }
@media (max-width: 800px) { .stats { grid-template-columns: repeat(2, 1fr); } }
.stat { padding: 1rem 1.2rem; border-radius: 16px; background: var(--panel); border: 1px solid var(--panel-b); }
.stat .k { color: var(--muted); font-size: .72rem; text-transform: uppercase; letter-spacing: .09em; font-weight: 600; }
.stat .v { font-size: 1.7rem; font-weight: 800; letter-spacing: -.02em; margin-top: .15rem; }
.grad { background: linear-gradient(100deg, var(--a1), var(--a2)); -webkit-background-clip: text;
  background-clip: text; color: transparent; }

.score-wrap { display: flex; align-items: center; gap: 1.4rem; }
.ring {
  --p: 0; width: 92px; height: 92px; border-radius: 50%; flex: none; display: grid; place-items: center;
  background: conic-gradient(var(--c, var(--ok)) calc(var(--p) * 1%), rgba(255,255,255,.08) 0);
}
.ring > span {
  width: 74px; height: 74px; border-radius: 50%; display: grid; place-items: center;
  background: #0d0f1a; font-weight: 800; font-size: 1.35rem;
}

.src { display: flex; align-items: center; gap: .8rem; padding: .8rem 1rem; margin-bottom: .55rem;
  border-radius: 14px; background: var(--panel); border: 1px solid var(--panel-b); transition: all .2s; }
.src:hover { border-color: var(--a1); transform: translateX(3px); }
.src .n { width: 26px; height: 26px; border-radius: 8px; display: grid; place-items: center; flex: none;
  background: rgba(124,92,255,.18); color: #c9c3ff; font-size: .75rem; font-weight: 700; }
.src a { color: var(--text); text-decoration: none; font-size: .9rem; word-break: break-all; }
.src a:hover { color: var(--a2); }
.src .host { color: var(--muted); font-size: .72rem; }

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] { gap: .4rem; border-bottom: 1px solid var(--panel-b); }
.stTabs [data-baseweb="tab"] { background: transparent; border-radius: 10px 10px 0 0; color: var(--muted); font-weight: 600; padding: .6rem 1.1rem; }
.stTabs [aria-selected="true"] { color: #fff !important; }
.stTabs [data-baseweb="tab-highlight"] { background: linear-gradient(90deg, var(--a1), var(--a2)); height: 3px; }

/* ── Report typography ── */
.report h1, .report h2, .report h3 { letter-spacing: -.02em; }
.report h2 { margin-top: 1.6rem; padding-bottom: .4rem; border-bottom: 1px solid var(--panel-b); }
.report p, .report li { line-height: 1.75; color: #d5d8e8; }
.report a { color: var(--a2); }

/* ── Sidebar ── */
section[data-testid="stSidebar"] { background: rgba(10,11,20,.85); border-right: 1px solid var(--panel-b); }
section[data-testid="stSidebar"], section[data-testid="stSidebar"] p, section[data-testid="stSidebar"] li,
section[data-testid="stSidebar"] span, section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2, section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] strong { color: var(--text) !important; }
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] *,
section[data-testid="stSidebar"] small { color: #b4b9d0 !important; opacity: 1 !important; }
section[data-testid="stSidebar"] { background: #0b0d18 !important; }
.side-title { font-size: .72rem; text-transform: uppercase; letter-spacing: .1em; color: var(--muted); font-weight: 700; margin: .4rem 0 .6rem; }
.hist { padding: .6rem .8rem; margin-bottom: .4rem; border-radius: 12px; background: var(--panel); border: 1px solid var(--panel-b); font-size: .85rem; }
.hist small { color: var(--muted); }

@keyframes sweep { 0% { left: -40%; } 100% { left: 100%; } }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: .35; } }
.fade { animation: fade .5s ease both; }
@keyframes fade { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# ───────────────────────────── Helpers ─────────────────────────────
STEPS = [
    ("search", "🔎", "Search Agent", "Scanning the web for sources"),
    ("read", "📖", "Reader Agent", "Scraping the best page"),
    ("write", "✍️", "Writer", "Drafting the full report"),
    ("critic", "🧐", "Critic", "Scoring & reviewing"),
]
STATE_LABEL = {"idle": "Queued", "running": "Working", "done": "Done", "error": "Failed"}

EXAMPLES = [
    "The impact of AI on the job market in 2026",
    "Solid-state batteries: where are we now?",
    "State of quantum computing for enterprises",
    "How is GLP-1 changing the food industry?",
]

def steps_html(states: dict) -> str:
    cards = []
    for key, icon, title, sub in STEPS:
        s = states.get(key, "idle")
        cards.append(
            f'<div class="step {s}"><span class="state">{STATE_LABEL[s]}</span>'
            f'<div class="ico">{icon}</div><div class="ttl">{title}</div>'
            f'<div class="sub">{sub}</div></div>'
        )
    return f'<div class="steps">{"".join(cards)}</div>'


def run_pipeline(topic: str, steps_slot, status_slot):
    """Run the pipeline, streaming step status into the UI. Returns (state, seconds)."""
    from src.pipelines.pipelines import run_research_pipeline

    states = {k: "idle" for k, *_ in STEPS}
    messages = {
        "search": "Searching the web…",
        "read": "Reading the most relevant source…",
        "write": "Writing your report…",
        "critic": "Critic is reviewing the draft…",
    }

    def on_step(key, status, data):
        if key == "notice":  # a retry wait: show it, then restore the step message
            if status == "running":
                status_slot.warning(data, icon="⏳")
            elif (current := running_step(states)) is not None:
                status_slot.info(messages[current], icon="⚡")
            return
        states[key] = status
        steps_slot.markdown(steps_html(states), unsafe_allow_html=True)
        if status == "running":
            status_slot.info(messages[key], icon="⚡")

    steps_slot.markdown(steps_html(states), unsafe_allow_html=True)
    t0 = time.time()
    try:
        state = run_research_pipeline(topic, on_step=on_step)
    except Exception as e:  # mark whichever step was running as failed
        for k, v in states.items():
            if v == "running":
                states[k] = "error"
        steps_slot.markdown(steps_html(states), unsafe_allow_html=True)
        raise e
    status_slot.empty()
    return state, time.time() - t0


# ───────────────────────────── Session state ─────────────────────────────
st.session_state.setdefault("topic", "")
st.session_state.setdefault("result", None)
st.session_state.setdefault("history", [])

# ───────────────────────────── Sidebar ─────────────────────────────
with st.sidebar:
    st.markdown("### 🔬 Nexus Research")
    st.caption("Multi-agent research, powered by LangChain.")
    st.markdown('<div class="side-title">Pipeline</div>', unsafe_allow_html=True)
    st.markdown(
        "1. **Search** — Tavily web search\n"
        "2. **Read** — scrape best source\n"
        "3. **Write** — structured report\n"
        "4. **Critic** — score & feedback"
    )
    st.markdown('<div class="side-title">History</div>', unsafe_allow_html=True)
    if not st.session_state.history:
        st.caption("Your past runs will appear here.")
    for i, h in enumerate(reversed(st.session_state.history)):
        idx = len(st.session_state.history) - 1 - i
        st.markdown(
            f'<div class="hist">{html.escape(h["topic"][:60])}<br>'
            f'<small>{h["when"]} · {fmt_seconds(h["seconds"])}</small></div>',
            unsafe_allow_html=True,
        )
        if st.button("Open", key=f"open_{idx}", use_container_width=True):
            st.session_state.result = st.session_state.history[idx]
            st.session_state.topic = h["topic"]
            st.rerun()
    if st.session_state.history and st.button("Clear history", use_container_width=True):
        st.session_state.history = []
        st.session_state.result = None
        st.rerun()

# ───────────────────────────── Hero ─────────────────────────────
st.markdown(
    """
<div class="hero fade">
  <span class="badge"><span class="dot"></span> 4 AI agents online</span>
  <h1>Research anything.<br>In minutes.</h1>
  <p>Describe a topic. A team of agents searches the web, reads the best sources,
  writes a structured report and critiques it — live.</p>
</div>
""",
    unsafe_allow_html=True,
)

# ───────────────────────────── Input ─────────────────────────────
topic = st.text_area(
    "Research topic",
    key="topic",
    height=92,
    max_chars=300,
    placeholder="e.g. The impact of AI on the job market in 2026",
)

chip_cols = st.columns(len(EXAMPLES))
for col, ex in zip(chip_cols, EXAMPLES, strict=True):
    col.button(
        ex,
        key=f"ex_{ex}",
        use_container_width=True,
        on_click=lambda ex=ex: st.session_state.update(topic=ex),
    )

_, mid, _ = st.columns([1, 1.2, 1])
go = mid.button("🚀  Start research", type="primary", use_container_width=True)

# ───────────────────────────── Run ─────────────────────────────
if go:
    clean = (st.session_state.topic or "").strip()
    if not clean:
        st.warning("Enter a topic first.", icon="✏️")
    else:
        steps_slot = st.empty()
        status_slot = st.empty()
        try:
            state, secs = run_pipeline(clean, steps_slot, status_slot)
            record = {
                **state,
                "topic": clean,
                "seconds": secs,
                "when": datetime.now().strftime("%H:%M"),
            }
            st.session_state.result = record
            st.session_state.history.append(record)
            st.rerun()
        except Exception as e:
            logger.exception("Pipeline failed")
            msg = str(e)
            hint = ""
            if isinstance(e, (openai.AuthenticationError, KeyError)):
                hint = "\n\nCheck the API keys and model settings in `src/.env`."
            elif isinstance(e, openai.APIStatusError) and e.status_code in (413, 429):
                hint = (
                    "\n\n**Rate limit hit.** Your Groq tier limits tokens per minute — "
                    "wait a minute and retry, or lower `GROQ_MAX_TOKENS` / use a model with higher limits."
                )
            status_slot.error(f"Pipeline failed: {msg[:400]}{hint}", icon="🚫")

# ───────────────────────────── Results ─────────────────────────────
res = st.session_state.result
if res and not go:
    report_md = strip_markdown_images(res.get("report", ""))
    feedback_md = strip_markdown_images(res.get("feedback", ""))
    score = parse_score(res.get("feedback", ""))
    urls = extract_urls(report_md, res.get("search_results", ""), res.get("scraped_content", ""))
    words = len(res.get("report", "").split())

    st.markdown(steps_html({k: "done" for k, *_ in STEPS}), unsafe_allow_html=True)
    st.markdown(
        f"""
<div class="stats fade">
  <div class="stat"><div class="k">Quality score</div><div class="v grad">{f"{score:g}/10" if score is not None else "—"}</div></div>
  <div class="stat"><div class="k">Report length</div><div class="v">{words:,} <span style="font-size:.9rem;color:var(--muted)">words</span></div></div>
  <div class="stat"><div class="k">Sources</div><div class="v">{len(urls)}</div></div>
  <div class="stat"><div class="k">Run time</div><div class="v">{fmt_seconds(res.get("seconds", 0))}</div></div>
</div>
""",
        unsafe_allow_html=True,
    )

    st.markdown(f"#### {html.escape(res['topic'])}")
    tab_report, tab_critic, tab_sources, tab_raw = st.tabs(
        ["📄 Report", "🧐 Critic", "🔗 Sources", "🧪 Raw data"]
    )

    with tab_report:
        st.markdown('<div class="card report fade">', unsafe_allow_html=True)
        st.markdown(report_md)
        st.markdown("</div>", unsafe_allow_html=True)
        c1, c2, _ = st.columns([1, 1, 3])
        slug = re.sub(r"[^a-z0-9]+", "-", res["topic"].lower()).strip("-")[:50] or "report"
        c1.download_button("⬇ Markdown", report_md, f"{slug}.md", "text/markdown", use_container_width=True)
        full = f"# {res['topic']}\n\n{report_md}\n\n---\n## Critic review\n\n{feedback_md}"
        c2.download_button("⬇ With review", full, f"{slug}-full.md", "text/markdown", use_container_width=True)

    with tab_critic:
        if score is not None:
            st.markdown(
                f"""
<div class="card fade"><div class="score-wrap">
  <div class="ring" style="--p:{score * 10}; --c:{score_color(score)}"><span>{score:g}</span></div>
  <div><div style="font-weight:700;font-size:1.1rem">Editorial score</div>
  <div style="color:var(--muted);font-size:.9rem">out of 10, from the critic agent</div></div>
</div></div>
""",
                unsafe_allow_html=True,
            )
            st.write("")
        st.markdown('<div class="card report fade">', unsafe_allow_html=True)
        st.markdown(feedback_md)
        st.markdown("</div>", unsafe_allow_html=True)

    with tab_sources:
        if not urls:
            st.info("No URLs were found in the research output.")
        for i, u in enumerate(urls, 1):
            safe = html.escape(u, quote=True)
            st.markdown(
                f'<div class="src fade"><span class="n">{i}</span><div>'
                f'<a href="{safe}" target="_blank" rel="noopener noreferrer">{html.escape(u)}</a>'
                f'<div class="host">{html.escape(host_of(u))}</div></div></div>',
                unsafe_allow_html=True,
            )

    with tab_raw:
        with st.expander("Search results", expanded=False):
            st.text(res.get("search_results", ""))
        with st.expander("Scraped content", expanded=False):
            st.text(res.get("scraped_content", ""))

st.markdown(
    '<p style="text-align:center;color:var(--muted);font-size:.78rem;margin-top:3rem">'
    "Built with LangChain · LangGraph · Tavily · Groq</p>",
    unsafe_allow_html=True,
)
