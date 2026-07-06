"""
LangSmith + LLM Configuration — V2 with Key Rotation.

Provides:
- LangSmith tracing setup
- get_llm() factory with automatic round-robin across 3 Groq API keys
- Automatic fallback on 429 rate limit errors
"""

import os
import time
import logging
import threading
from langchain_groq import ChatGroq

logger = logging.getLogger(__name__)


def setup_langsmith():
    """Configure LangSmith tracing. Safe to call multiple times."""
    api_key = os.environ.get("LANGCHAIN_API_KEY", "")
    if api_key:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ.setdefault("LANGCHAIN_PROJECT", "Tadwera-RAG-LangGraph")
        logger.info("[LangGraph] LangSmith tracing ENABLED")
    else:
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        logger.info("[LangGraph] LangSmith tracing DISABLED")


# ═══════════════════════════════════════════════════════════
# Groq Key Round-Robin Pool
# ═══════════════════════════════════════════════════════════

class GroqKeyPool:
    """
    Thread-safe round-robin pool for Groq API keys.
    
    On each call to get_key():
      - Returns the next key in rotation
      - If a key hits 429, mark_exhausted() skips it for cooldown_seconds
    
    Keys rotate: KEY_1 → KEY_2 → KEY_3 → KEY_1 → ...
    If all keys exhausted, returns the least-recently-exhausted one.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._keys = []
        self._index = 0
        self._exhausted: dict[str, float] = {}  # key → timestamp when exhausted
        self._cooldown = 60  # seconds to wait before retrying exhausted key
        self._loaded = False

    def _load_keys(self):
        """Load all Groq keys from environment (lazy, once)."""
        if self._loaded:
            return

        key_vars = ["GROQ_API_KEY_RAG", "GROQ_AGENT_API_KEY", "GROQ_API_KEY"]
        for var in key_vars:
            key = os.environ.get(var, "").strip('"').strip("'").strip()
            if key and key not in self._keys:
                self._keys.append(key)
                logger.info(f"[GroqPool] Loaded key from {var}: ...{key[-8:]}")

        if not self._keys:
            logger.error("[GroqPool] No Groq API keys found!")

        self._loaded = True
        logger.info(f"[GroqPool] {len(self._keys)} keys ready for rotation")

    def get_key(self) -> str:
        """Get the next available API key (round-robin with exhaustion check)."""
        with self._lock:
            self._load_keys()
            if not self._keys:
                return ""

            now = time.time()
            n = len(self._keys)

            # Try each key in round-robin order
            for _ in range(n):
                key = self._keys[self._index % n]
                self._index += 1

                exhausted_at = self._exhausted.get(key, 0)
                if now - exhausted_at > self._cooldown:
                    # Key is available
                    if key in self._exhausted:
                        del self._exhausted[key]
                        logger.info(f"[GroqPool] Key ...{key[-8:]} recovered from cooldown")
                    logger.info(f"[GroqPool] Using key ...{key[-8:]}")
                    return key

            # All exhausted — use the one that was exhausted longest ago
            oldest_key = min(self._exhausted, key=self._exhausted.get)
            logger.warning(f"[GroqPool] All keys exhausted! Forcing ...{oldest_key[-8:]}")
            return oldest_key

    def mark_exhausted(self, key: str):
        """Mark a key as rate-limited (skip for cooldown period)."""
        with self._lock:
            self._exhausted[key] = time.time()
            available = len(self._keys) - len(self._exhausted)
            logger.warning(f"[GroqPool] Key ...{key[-8:]} exhausted (429). {available}/{len(self._keys)} keys available")


# ── Global pool ──
_pool = GroqKeyPool()


def get_llm(temperature: float = 0.1):
    """
    Factory for Groq-hosted Llama-3.3-70b with automatic key rotation.
    
    Returns: (ChatGroq instance, api_key string)
    The api_key is returned so callers can mark_key_exhausted(key) on 429.
    """
    api_key = _pool.get_key()
    llm = ChatGroq(
        model="llama-3.3-70b-versatile",
        temperature=temperature,
        api_key=api_key,
    )
    return llm, api_key


def mark_key_exhausted(key: str):
    """Mark a key as rate-limited after a 429 error."""
    _pool.mark_exhausted(key)

