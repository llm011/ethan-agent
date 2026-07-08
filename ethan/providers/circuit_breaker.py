"""Provider-level circuit breaker with exponential backoff.

States:
  CLOSED    — normal operation, all requests pass through
  OPEN      — provider is down, requests are rejected until backoff expires
  HALF_OPEN — one probe request allowed; success → CLOSED, failure → OPEN (doubled backoff)

Backoff schedule: 5 min → 10 min → 20 min → 40 min → 60 min (capped)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

_FAILURE_THRESHOLD = 3   # consecutive failures before opening
_BACKOFF_BASE = 300.0    # 5 minutes
_BACKOFF_MAX = 3600.0    # 1 hour


class ProviderState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class _ProviderHealth:
    state: ProviderState = ProviderState.CLOSED
    failures: int = 0
    next_retry: float = 0.0          # monotonic time
    backoff: float = _BACKOFF_BASE   # current backoff duration (seconds)
    probe_issued: bool = False       # HALF_OPEN: only one probe allowed at a time


class CircuitBreaker:
    """Process-global circuit breaker; one instance per provider key."""

    def __init__(self) -> None:
        self._providers: dict[str, _ProviderHealth] = {}

    def _get(self, key: str) -> _ProviderHealth:
        if key not in self._providers:
            self._providers[key] = _ProviderHealth()
        return self._providers[key]

    def is_available(self, key: str) -> bool:
        h = self._get(key)
        if h.state == ProviderState.OPEN:
            if time.monotonic() >= h.next_retry:
                h.state = ProviderState.HALF_OPEN
                h.probe_issued = False
                logger.info("circuit_breaker: %s → HALF_OPEN (probing)", key)
            else:
                return False
        if h.state == ProviderState.HALF_OPEN:
            if h.probe_issued:
                return False   # another probe is already in flight
            h.probe_issued = True
            return True
        return True  # CLOSED

    def record_success(self, key: str) -> None:
        h = self._get(key)
        if h.state != ProviderState.CLOSED:
            logger.info("circuit_breaker: %s → CLOSED (recovered)", key)
        h.state = ProviderState.CLOSED
        h.failures = 0
        h.backoff = _BACKOFF_BASE
        h.probe_issued = False

    def record_failure(self, key: str) -> None:
        h = self._get(key)
        h.failures += 1
        if h.state == ProviderState.HALF_OPEN or h.failures >= _FAILURE_THRESHOLD:
            h.next_retry = time.monotonic() + h.backoff
            h.backoff = min(h.backoff * 2, _BACKOFF_MAX)
            logger.warning(
                "circuit_breaker: %s → OPEN (failures=%d, retry_in=%.0fs)",
                key, h.failures, h.next_retry - time.monotonic(),
            )
            h.state = ProviderState.OPEN
            h.probe_issued = False

    def status(self) -> dict[str, dict]:
        now = time.monotonic()
        return {
            k: {
                "state": v.state.value,
                "failures": v.failures,
                "retry_in_seconds": round(max(0.0, v.next_retry - now), 1),
            }
            for k, v in self._providers.items()
        }

    def reset(self, key: str) -> None:
        """Manually reset a provider to CLOSED (e.g. after config change)."""
        if key in self._providers:
            del self._providers[key]


_breaker = CircuitBreaker()


def get_circuit_breaker() -> CircuitBreaker:
    return _breaker
