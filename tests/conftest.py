import os
import sys
from pathlib import Path

# Dummy settings so modules that read env vars at import time can be imported offline.
os.environ.setdefault("TAVILY_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")
os.environ.setdefault("GROQ_MODEL", "test-model")
os.environ.setdefault("GROQ_BASE_URL", "http://localhost/v1")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
