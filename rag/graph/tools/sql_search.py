"""
SQLSearchTool — LangChain BaseTool wrapper around rag.sql_generator.

Wrapping as a Tool gives us automatic LangSmith tracing per invocation,
including the generated SQL and row counts.
"""

import logging
from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


class SQLSearchTool(BaseTool):
    name: str = "sql_search"
    description: str = (
        "Text-to-SQL search: converts Egyptian Arabic query into PostgreSQL, "
        "validates safety, executes on Neon, returns structured results."
    )

    def _run(self, query: str) -> dict:
        from rag.sql_generator import sql_search
        try:
            results, generated_sql = sql_search(query)
            logger.info(f"[Tool/SQL] Generated SQL: {generated_sql[:80]}...")
            logger.info(f"[Tool/SQL] Found {len(results)} rows")
            return {"results": results, "generated_sql": generated_sql}
        except Exception as e:
            logger.error(f"[Tool/SQL] Failed: {e}")
            return {"results": [], "generated_sql": ""}
