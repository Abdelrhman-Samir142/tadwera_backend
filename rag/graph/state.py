"""
AgentState — V2 Architecture.

Streamlined state for the 5-node pipeline:
  Router → [Vector + SQL] (parallel) → RRF Fusion → Synthesis+Guardrails
"""

import operator
from typing import TypedDict, Annotated, Optional, Literal, List
from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════
# Graph State — V2
# ═══════════════════════════════════════════════════════════

class AgentState(TypedDict):
    # ── User Input ──
    messages: Annotated[list, operator.add]
    query: str

    # ── Node 1: Router Output ──
    intent: str                        # greeting | faq | chitchat | search | follow_up
    intent_response: Optional[str]     # Pre-built response for non-search intents
    next_step: str                     # routing key
    entities: dict                     # {product, price_min, price_max, location, category}

    # ── Node 2 & 3: Retrieval ──
    vector_results: list[dict]         # Semantic search results (re-ranked)
    sql_results: list[dict]            # SQL results (with seller JOINs)
    generated_sql: str
    vector_count: int
    sql_count: int

    # ── Node 4: RRF Fusion ──
    fused_results: list[dict]          # RRF-ranked merged results

    # ── Node 5: Synthesis ──
    final_response: Optional[dict]     # {summary, items, suggested_action}
    products_data: list[dict]          # Frontend-ready product cards

    # ── Control Flow ──
    retry_count: int
    metadata: dict


# ═══════════════════════════════════════════════════════════
# Pydantic Structured Output Schemas
# ═══════════════════════════════════════════════════════════

class ProductItem(BaseModel):
    """Single product in the response."""
    id: int = Field(description="Product ID")
    reason: str = Field(description="سبب اختيار المنتج ده بالعامية")


class SynthesisOutput(BaseModel):
    """Enforced output schema for the Synthesis LLM."""
    summary: str = Field(
        description="ملخص بالعامية المصرية — مختصر ومفيد (3-5 جمل)"
    )
    items: List[int] = Field(
        description="قائمة IDs المنتجات المطابقة فقط — فارغة لو مفيش"
    )
    suggested_action: Literal[
        "view_listing", "place_bid", "compare_prices", "set_agent"
    ] = Field(
        description="الإجراء المقترح للمستخدم"
    )
