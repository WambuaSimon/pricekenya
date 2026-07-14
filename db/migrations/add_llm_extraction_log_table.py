"""One-shot migration: create the `llmextractionlog` table if it doesn't exist.

Backs Phase 0 (Gemini fallback) — every LLM call is logged for cache dedup
+ per-category daily cap enforcement.

Same idempotent pattern as add_click_table.

Usage:
    python -m db.migrations.add_llm_extraction_log_table
"""

from __future__ import annotations

from sqlalchemy import inspect

from db.models import LlmExtractionLog  # noqa: F401 — register with metadata
from db.session import engine


def run() -> None:
    insp = inspect(engine)
    if insp.has_table("llmextractionlog"):
        print("llmextractionlog table already exists — noop")
        return
    LlmExtractionLog.__table__.create(bind=engine)
    print(f"created llmextractionlog table ({engine.dialect.name})")


if __name__ == "__main__":
    run()
