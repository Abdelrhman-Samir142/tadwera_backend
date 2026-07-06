"""
InstantResponseNode — handles greeting / faq / chitchat.

Zero LLM tokens. Packages the pre-built response into final_response.
"""

from rag.graph.state import AgentState


def instant_response_node(state: AgentState) -> dict:
    """Package the pre-built intent response as the final answer."""
    summary = state.get("intent_response") or ""
    if summary:
        import re
        for old in ["4sale", "4 sale", "four-sale", "four sale", "4-sale", "فور سيل", "فور سيلز", "فور سأل"]:
            summary = re.sub(re.escape(old), "تدويرة", summary, flags=re.IGNORECASE)

    return {
        "final_response": {
            "summary": summary,
            "items": [],
            "suggested_action": "view_listing",
        },
        "products_data": [],
    }
