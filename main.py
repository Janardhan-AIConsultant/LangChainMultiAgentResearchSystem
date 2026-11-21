import logging
import sys

from src.pipelines.pipelines import run_research_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

if __name__ == "__main__":
    topic = sys.argv[1] if len(sys.argv) > 1 else "The impact of AI on the job market in 2026"
    result = run_research_pipeline(topic)
    print("\n=== REPORT ===\n", result["report"])
    print("\n=== CRITIC ===\n", result["feedback"])
