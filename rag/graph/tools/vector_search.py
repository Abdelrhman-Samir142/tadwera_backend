"""
VectorSearchTool — LangChain BaseTool wrapper around rag.vector_search.

Wrapping as a Tool gives us automatic LangSmith tracing per invocation.
"""

import logging
from langchain_core.tools import BaseTool
from pydantic import Field

logger = logging.getLogger(__name__)


class VectorSearchTool(BaseTool):
    name: str = "vector_search"
    description: str = (
        "Semantic search using Gemini embeddings + cosine similarity. "
        "Returns products ranked by semantic relevance to the query."
    )
    top_k: int = Field(default=4)

    def _run(self, query: str) -> list[dict]:
        from rag.vector_search import vector_search
        try:
            results = vector_search(query, self.top_k)
            logger.info(f"[Tool/Vector] Found {len(results)} results")
            return results
        except Exception as e:
            logger.error(f"[Tool/Vector] Failed: {e}")
            return []
