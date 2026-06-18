"""Semantic caching layer for LLM queries and DB results.

Implements:
- Exact match cache (identical queries)
- Semantic similarity cache (embedding-based near-matches)
- Plan cache (reuses execution plans)
- Result cache (reuses query results)

Academic research shows: exact + semantic caching achieves 1.5-4.4x latency reduction.
"""
import hashlib
import time
import json
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from src.utils import logger


@dataclass
class CacheEntry:
    """A single cache entry."""
    key: str
    value: Any
    timestamp: float
    access_count: int = 0
    ttl: int = 3600  # seconds

    def is_expired(self) -> bool:
        return time.time() - self.timestamp > self.ttl

    def touch(self):
        self.access_count += 1


class ExactCache:
    """Exact-match cache with TTL."""

    def __init__(self, ttl: int = 3600, max_size: int = 1000):
        self.ttl = ttl
        self.max_size = max_size
        self._cache: Dict[str, CacheEntry] = {}

    def get(self, key: str) -> Optional[Any]:
        entry = self._cache.get(key)
        if not entry:
            return None

        if entry.is_expired():
            del self._cache[key]
            return None

        entry.touch()
        logger.debug(f"Exact cache HIT: {key[:50]}...")
        return entry.value

    def set(self, key: str, value: Any) -> None:
        # Evict oldest if at capacity
        if len(self._cache) >= self.max_size:
            oldest = min(self._cache.keys(), key=lambda k: self._cache[k].timestamp)
            del self._cache[oldest]

        self._cache[key] = CacheEntry(
            key=key,
            value=value,
            timestamp=time.time(),
            ttl=self.ttl,
        )
        logger.debug(f"Exact cache SET: {key[:50]}...")

    def invalidate(self, pattern: Optional[str] = None) -> None:
        if pattern:
            to_remove = [k for k in self._cache if pattern in k]
            for k in to_remove:
                del self._cache[k]
        else:
            self._cache.clear()

    def stats(self) -> Dict:
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "hit_rate": self._calculate_hit_rate(),
        }

    def _calculate_hit_rate(self) -> float:
        if not self._cache:
            return 0.0
        total_accesses = sum(e.access_count for e in self._cache.values())
        return total_accesses / max(total_accesses + len(self._cache), 1)


class SemanticCache:
    """Embedding-based semantic similarity cache.

    Uses simple keyword overlap as a lightweight semantic similarity measure.
    Production would use sentence-transformers (BGE-M3) embeddings.
    """

    def __init__(self, similarity_threshold: float = 0.85, ttl: int = 3600):
        self.similarity_threshold = similarity_threshold
        self.ttl = ttl
        self._entries: List[Dict] = []  # [{"query": str, "embedding": np.array, "value": Any, "timestamp": float}]

    def _embed(self, text: str) -> np.ndarray:
        """Create a simple embedding from keyword frequencies.

        Production: Replace with sentence-transformers.encode()
        """
        # Simple bag-of-words embedding
        words = set(text.lower().split())
        # Create a hash-based vector
        vector = np.zeros(256)
        for word in words:
            idx = hash(word) % 256
            vector[idx] += 1
        # Normalize
        norm = np.linalg.norm(vector)
        return vector / norm if norm > 0 else vector

    def _similarity(self, emb1: np.ndarray, emb2: np.ndarray) -> float:
        """Cosine similarity between embeddings."""
        dot = np.dot(emb1, emb2)
        return float(dot)

    def get(self, query: str) -> Tuple[Optional[Any], float]:
        """Get cached result if semantically similar query exists.

        Returns:
            (value, similarity_score) or (None, 0.0)
        """
        query_emb = self._embed(query)
        best_match = None
        best_score = 0.0

        for entry in self._entries:
            if time.time() - entry["timestamp"] > self.ttl:
                continue

            score = self._similarity(query_emb, entry["embedding"])
            if score > best_score and score >= self.similarity_threshold:
                best_score = score
                best_match = entry

        if best_match:
            best_match["access_count"] = best_match.get("access_count", 0) + 1
            logger.info(f"Semantic cache HIT (score={best_score:.3f}): {query[:50]}...")
            return best_match["value"], best_score

        return None, 0.0

    def set(self, query: str, value: Any) -> None:
        """Cache a query-result pair."""
        self._entries.append({
            "query": query,
            "embedding": self._embed(query),
            "value": value,
            "timestamp": time.time(),
            "access_count": 0,
        })

        # Clean expired entries periodically
        if len(self._entries) > 100:
            self._entries = [
                e for e in self._entries
                if time.time() - e["timestamp"] <= self.ttl
            ]

        logger.debug(f"Semantic cache SET: {query[:50]}...")

    def invalidate(self) -> None:
        self._entries.clear()


class QueryCacheManager:
    """Unified cache manager for all caching layers."""

    def __init__(self):
        self.exact = ExactCache(ttl=300)       # 5 min for exact queries
        self.semantic = SemanticCache(ttl=600)  # 10 min for semantic matches
        self.plan = ExactCache(ttl=1800)        # 30 min for execution plans
        self.result = ExactCache(ttl=300)       # 5 min for query results

    def get_cached_response(self, user_query: str, route: str) -> Optional[Dict]:
        """Try to get cached response for a query.

        Check order: exact → semantic → None
        """
        cache_key = f"{route}:{self._hash_query(user_query)}"

        # Try exact match
        exact_result = self.exact.get(cache_key)
        if exact_result:
            logger.info(f"Exact cache hit for query: {user_query[:50]}...")
            return exact_result

        # Try semantic match
        semantic_result, score = self.semantic.get(user_query)
        if semantic_result:
            logger.info(f"Semantic cache hit (score={score:.3f}) for query: {user_query[:50]}...")
            return semantic_result

        return None

    def cache_response(self, user_query: str, route: str, response: Dict) -> None:
        """Cache a query response."""
        cache_key = f"{route}:{self._hash_query(user_query)}"
        self.exact.set(cache_key, response)
        self.semantic.set(user_query, response)
        logger.info(f"Cached response for: {user_query[:50]}...")

    def get_cached_plan(self, query_hash: str) -> Optional[str]:
        """Get cached execution plan."""
        return self.plan.get(query_hash)

    def cache_plan(self, query_hash: str, plan: str) -> None:
        """Cache execution plan."""
        self.plan.set(query_hash, plan)

    def get_cached_result(self, sql_hash: str) -> Optional[Any]:
        """Get cached query result."""
        return self.result.get(sql_hash)

    def cache_result(self, sql_hash: str, result: Any) -> None:
        """Cache query result."""
        self.result.set(sql_hash, result)

    def invalidate_all(self) -> None:
        """Invalidate all caches."""
        self.exact.invalidate()
        self.semantic.invalidate()
        self.plan.invalidate()
        self.result.invalidate()
        logger.info("All caches invalidated")

    def stats(self) -> Dict:
        return {
            "exact": self.exact.stats(),
            "semantic": {"size": len(self.semantic._entries)},
            "plan": self.plan.stats(),
            "result": self.result.stats(),
        }

    @staticmethod
    def _hash_query(query: str) -> str:
        """Create a hash of normalized query."""
        normalized = " ".join(query.lower().split())
        return hashlib.md5(normalized.encode()).hexdigest()[:16]
