"""
Node 1: Router & Entity Extractor — V2.

Zero LLM tokens. Classifies intent + extracts entities.
"""

import logging
from rag.graph.state import AgentState

logger = logging.getLogger(__name__)


def router_node(state: AgentState) -> dict:
    """Classify intent and extract entities. Routes the graph."""
    from rag.intent_router import classify_intent, extract_entities

    query = state["query"]
    intent = classify_intent(query)
    entities = extract_entities(query) if not intent["response"] else {}

    logger.info(f"[Node/Router] intent={intent['intent']} entities={entities}")

    if intent["response"]:
        next_step = "instant_response"
    elif intent["intent"] == "follow_up":
        next_step = "followup"
    else:
        next_step = "retrieval"

    return {
        "intent": intent["intent"],
        "intent_response": intent.get("response"),
        "entities": entities,
        "next_step": next_step,
        "retry_count": 0,
        "metadata": {"intent": intent["intent"]},
    }
