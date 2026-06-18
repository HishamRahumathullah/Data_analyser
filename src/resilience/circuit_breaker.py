"""Resilience patterns: Circuit Breaker, Bulkhead, Fallback.

Prevents cascade failures when:
- LLM API is down or slow
- Database is overloaded
- External services fail

Tracks: error rate, response time buckets, token consumption, validation failures.
States: CLOSED (normal) → OPEN (failing) → HALF-OPEN (testing recovery)
"""
import time
import threading
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps

from src.utils import logger


class CircuitState(Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreaker:
    """Circuit breaker for a single service (LLM, DB, etc.)."""
    name: str
    failure_threshold: int = 5          # Failures before opening
    recovery_timeout: int = 30          # Seconds before half-open
    half_open_max_calls: int = 3        # Test calls in half-open
    success_threshold: int = 2          # Successes to close

    # State
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float = 0.0
    half_open_calls: int = 0

    # Metrics
    total_calls: int = 0
    total_failures: int = 0
    total_successes: int = 0
    response_times: List[float] = field(default_factory=list)

    _lock: threading.Lock = field(default_factory=threading.Lock)

    def can_execute(self) -> bool:
        """Check if request should be allowed."""
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return True

            if self.state == CircuitState.OPEN:
                if time.time() - self.last_failure_time >= self.recovery_timeout:
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_calls = 0
                    logger.info(f"Circuit {self.name}: OPEN → HALF_OPEN")
                    return True
                return False

            if self.state == CircuitState.HALF_OPEN:
                if self.half_open_calls < self.half_open_max_calls:
                    self.half_open_calls += 1
                    return True
                return False

            return True

    def record_success(self, response_time_ms: float) -> None:
        """Record a successful call."""
        with self._lock:
            self.total_calls += 1
            self.total_successes += 1
            self.response_times.append(response_time_ms)
            self.response_times = self.response_times[-100:]  # Keep last 100

            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.success_threshold:
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
                    self.success_count = 0
                    logger.info(f"Circuit {self.name}: HALF_OPEN → CLOSED")
            else:
                self.failure_count = 0

    def record_failure(self, error_type: str) -> None:
        """Record a failed call."""
        with self._lock:
            self.total_calls += 1
            self.total_failures += 1
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.OPEN
                self.half_open_calls = 0
                logger.warning(f"Circuit {self.name}: HALF_OPEN → OPEN ({error_type})")
            elif self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
                logger.warning(f"Circuit {self.name}: CLOSED → OPEN ({self.failure_count} failures)")

    def get_stats(self) -> Dict:
        """Get circuit breaker statistics."""
        with self._lock:
            avg_response_time = sum(self.response_times) / len(self.response_times) if self.response_times else 0
            error_rate = self.total_failures / max(self.total_calls, 1)

            return {
                "name": self.name,
                "state": self.state.value,
                "failure_count": self.failure_count,
                "total_calls": self.total_calls,
                "total_failures": self.total_failures,
                "error_rate": error_rate,
                "avg_response_time_ms": avg_response_time,
                "p95_response_time_ms": self._percentile(self.response_times, 0.95) if self.response_times else 0,
            }

    @staticmethod
    def _percentile(values: List[float], p: float) -> float:
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        idx = int(len(sorted_vals) * p)
        return sorted_vals[min(idx, len(sorted_vals) - 1)]


class Bulkhead:
    """Bulkhead pattern — limits concurrent operations per service."""

    def __init__(self, name: str, max_concurrent: int = 10, max_queue: int = 20):
        self.name = name
        self.max_concurrent = max_concurrent
        self.max_queue = max_queue
        self._semaphore = threading.Semaphore(max_concurrent)
        self._queue_size = 0
        self._lock = threading.Lock()

    def acquire(self, timeout: float = 30.0) -> bool:
        """Acquire a slot. Returns False if queue is full."""
        with self._lock:
            if self._queue_size >= self.max_queue:
                logger.warning(f"Bulkhead {self.name}: queue full")
                return False
            self._queue_size += 1

        acquired = self._semaphore.acquire(timeout=timeout)
        if not acquired:
            with self._lock:
                self._queue_size -= 1
        return acquired

    def release(self):
        """Release a slot."""
        self._semaphore.release()
        with self._lock:
            self._queue_size = max(0, self._queue_size - 1)

    def __enter__(self):
        if not self.acquire():
            raise BulkheadFullError(f"Bulkhead {self.name} is full")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


class FallbackManager:
    """Manages fallback strategies for service failures."""

    FALLBACKS: Dict[str, Callable] = {}

    @classmethod
    def register(cls, service: str, fallback: Callable):
        """Register a fallback function for a service."""
        cls.FALLBACKS[service] = fallback

    @classmethod
    def execute(cls, service: str, *args, **kwargs) -> Any:
        """Execute fallback for a service."""
        fallback = cls.FALLBACKS.get(service)
        if fallback:
            logger.info(f"Executing fallback for {service}")
            return fallback(*args, **kwargs)
        raise NoFallbackError(f"No fallback registered for {service}")


class ResilienceManager:
    """Central manager for all resilience components."""

    def __init__(self):
        self.circuits: Dict[str, CircuitBreaker] = {}
        self.bulkheads: Dict[str, Bulkhead] = {}

    def get_circuit(self, service: str) -> CircuitBreaker:
        """Get or create circuit breaker for a service."""
        if service not in self.circuits:
            self.circuits[service] = CircuitBreaker(name=service)
        return self.circuits[service]

    def get_bulkhead(self, service: str) -> Bulkhead:
        """Get or create bulkhead for a service."""
        if service not in self.bulkheads:
            self.bulkheads[service] = Bulkhead(name=service)
        return self.bulkheads[service]

    def get_all_stats(self) -> Dict:
        """Get stats for all resilience components."""
        return {
            "circuits": {name: cb.get_stats() for name, cb in self.circuits.items()},
            "bulkheads": {
                name: {"max_concurrent": bh.max_concurrent, "queue_size": bh._queue_size}
                for name, bh in self.bulkheads.items()
            },
        }


# Decorator for circuit breaker + bulkhead
def resilient(service: str, fallback: Optional[str] = None):
    """Decorator that adds circuit breaker and bulkhead protection."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            resilience = ResilienceManager()
            circuit = resilience.get_circuit(service)
            bulkhead = resilience.get_bulkhead(service)

            # Check circuit breaker
            if not circuit.can_execute():
                if fallback:
                    return FallbackManager.execute(fallback, *args, **kwargs)
                raise CircuitOpenError(f"Circuit {service} is OPEN")

            # Acquire bulkhead slot
            if not bulkhead.acquire(timeout=30.0):
                if fallback:
                    return FallbackManager.execute(fallback, *args, **kwargs)
                raise BulkheadFullError(f"Bulkhead {service} is full")

            try:
                start = time.time()
                result = func(*args, **kwargs)
                response_time = (time.time() - start) * 1000
                circuit.record_success(response_time)
                return result
            except Exception as e:
                circuit.record_failure(type(e).__name__)
                if fallback:
                    return FallbackManager.execute(fallback, *args, **kwargs)
                raise
            finally:
                bulkhead.release()

        return wrapper
    return decorator


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open."""
    pass

class BulkheadFullError(Exception):
    """Raised when bulkhead is full."""
    pass

class NoFallbackError(Exception):
    """Raised when no fallback is available."""
    pass
