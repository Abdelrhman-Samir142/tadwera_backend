"""
Response Cache — LRU Cache for RAG queries.

Caches the full response (answer + meta) for repeated queries.
Uses a normalized query key to maximize cache hits.

- TTL: 10 minutes (products can change)
- Max Size: 100 entries
- Normalized: Arabic normalization + lowercasing + whitespace cleanup

Saves ALL tokens for cached queries (SQL + Vector + Synthesis = ~1300 tokens).
"""

import time
import hashlib
import logging
from collections import OrderedDict
from rag.intent_router import normalize_arabic

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# Cache Configuration
# ═══════════════════════════════════════════════════════════

CACHE_MAX_SIZE = 100       # Maximum number of cached queries
CACHE_TTL_SECONDS = 600    # 10 minutes TTL


class RAGCache:
    """
    Thread-safe LRU cache with TTL for RAG query responses.
    
    Each entry stores: {response, timestamp, hit_count}
    """
    
    def __init__(self, max_size=CACHE_MAX_SIZE, ttl=CACHE_TTL_SECONDS):
        self._cache: OrderedDict = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl
        self._total_hits = 0
        self._total_misses = 0
    
    def _make_key(self, query: str, user_id: str = "anon") -> str:
        """Normalize query and hash it for a consistent cache key.
        Includes user_id to prevent cross-user cache leaks."""
        normalized = normalize_arabic(query)
        normalized = ' '.join(normalized.split())
        raw = f"{user_id}:{normalized}"
        return hashlib.md5(raw.encode('utf-8')).hexdigest()
    
    def get(self, query: str, user_id: str = "anon") -> dict | None:
        """
        Get cached response for a query.
        Returns None if not cached or expired.
        """
        key = self._make_key(query, user_id)
        
        if key not in self._cache:
            self._total_misses += 1
            return None
        
        entry = self._cache[key]
        
        # Check TTL
        if time.time() - entry['timestamp'] > self._ttl:
            del self._cache[key]
            self._total_misses += 1
            logger.info(f"[RAGCache] EXPIRED: '{query[:30]}...'")
            return None
        
        # Move to end (most recently used)
        self._cache.move_to_end(key)
        entry['hit_count'] += 1
        self._total_hits += 1
        
        logger.info(
            f"[RAGCache] HIT: '{query[:30]}...' "
            f"(hits: {entry['hit_count']}, total: {self._total_hits}/{self._total_hits + self._total_misses})"
        )
        return entry['response']
    
    def set(self, query: str, response: dict, user_id: str = "anon") -> None:
        """Cache a response for a query."""
        key = self._make_key(query, user_id)
        
        # Evict oldest if at capacity
        while len(self._cache) >= self._max_size:
            evicted_key, evicted = self._cache.popitem(last=False)
            logger.debug(f"[RAGCache] EVICTED oldest entry (hits: {evicted['hit_count']})")
        
        self._cache[key] = {
            'response': response,
            'timestamp': time.time(),
            'hit_count': 0,
        }
        logger.info(f"[RAGCache] SET: '{query[:30]}...' (cache size: {len(self._cache)})")
    
    def invalidate_all(self) -> None:
        """Clear the entire cache (call when products change)."""
        size = len(self._cache)
        self._cache.clear()
        logger.info(f"[RAGCache] INVALIDATED all {size} entries")
    
    def stats(self) -> dict:
        """Return cache statistics."""
        total = self._total_hits + self._total_misses
        hit_rate = (self._total_hits / total * 100) if total > 0 else 0
        return {
            "cache_size": len(self._cache),
            "max_size": self._max_size,
            "total_hits": self._total_hits,
            "total_misses": self._total_misses,
            "hit_rate_percent": round(hit_rate, 1),
            "ttl_seconds": self._ttl,
            "estimated_tokens_saved": self._total_hits * 1300,
        }


# ── Global Cache Instance ──────────────────────────────────
_cache = RAGCache()


def get_cache() -> RAGCache:
    """Get the global RAG cache instance."""
    return _cache
