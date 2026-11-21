from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from src.tools.tools import web_search, scrape_url
import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic import SecretStr

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# Model Initialization
llm = ChatOpenAI(
    model=os.environ["GROQ_MODEL"],
    temperature=float(os.environ.get("GROQ_TEMPERATURE", 0)),
    # Groq free tier caps output tokens/minute (1000 for this model); keep each request under it.
    max_completion_tokens=int(os.environ.get("GROQ_MAX_TOKENS", 900)),
    api_key=SecretStr(os.environ["GROQ_API_KEY"]),
    base_url=os.environ["GROQ_BASE_URL"],
)


# 1st Agent : Search Agent
def build_search_agent():
    return create_agent(
        model= llm,
        tools=[web_search],
       
    )

# 2nd Agent : Reader Agent
def build_reader_agent():
    return create_agent(
        model= llm,
        tools=[scrape_url],

    )


#writer chain 

writer_prompt = ChatPromptTemplate.from_messages([
    ("system", "You are an expert research writer. Write clear, structured and insightful reports."),
    ("human", """Write a detailed research report on the topic below.

Topic: {topic}

Research Gathered:
{research}

Structure the report as:
- Introduction
- Key Findings (minimum 3 well-explained points)
- Conclusion
- Sources (list all URLs found in the research)

Be detailed, factual and professional."""),
])

writer_chain = writer_prompt | llm | StrOutputParser()




#critic_chain 

critic_prompt = ChatPromptTemplate.from_messages([
     ("system", "You are a sharp and constructive research critic. Be honest and specific."),
    ("human", """Review the research report below and evaluate it strictly.

Report:
{report}

Respond in this exact format:

Score: X/10

Strengths:
- ...
- ...

Areas to Improve:
- ...
- ...

One line verdict:
..."""),
])

critic_chain = critic_prompt | llm | StrOutputParser()
