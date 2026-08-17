"""Small process-local limiter for authentication endpoints."""
import math
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Hashable


class LoginRateLimiter:
    def __init__(
        self, max_attempts: int = 5, window_seconds: int = 300,
        lockout_seconds: int = 300,
    ):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.lockout_seconds = lockout_seconds
        self._failures: Dict[Hashable, Deque[float]] = defaultdict(deque)
        self._blocked_until: Dict[Hashable, float] = {}
        self._lock = threading.Lock()

    def retry_after(self, key: Hashable) -> int:
        now = time.monotonic()
        with self._lock:
            blocked = self._blocked_until.get(key, 0.0)
            if blocked > now:
                return max(1, math.ceil(blocked - now))
            self._blocked_until.pop(key, None)
            failures = self._failures.get(key)
            if failures is not None:
                self._purge(failures, now)
                if not failures:
                    self._failures.pop(key, None)
            return 0

    def record_failure(self, key: Hashable) -> None:
        now = time.monotonic()
        with self._lock:
            failures = self._failures[key]
            self._purge(failures, now)
            failures.append(now)
            if len(failures) >= self.max_attempts:
                self._blocked_until[key] = now + self.lockout_seconds

    def reset(self, key: Hashable) -> None:
        with self._lock:
            self._failures.pop(key, None)
            self._blocked_until.pop(key, None)

    def _purge(self, failures: Deque[float], now: float) -> None:
        cutoff = now - self.window_seconds
        while failures and failures[0] <= cutoff:
            failures.popleft()


class RequestRateLimiter:
    """Thread-safe sliding-window limiter for bounded public operations."""

    def __init__(self, maximum: int = 5, window_seconds: int = 3600):
        self.maximum = max(1, int(maximum))
        self.window_seconds = max(1, int(window_seconds))
        self._requests: Dict[Hashable, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def consume(self, key: Hashable) -> int:
        """Record one request and return zero, or seconds until retry."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            requests = self._requests[key]
            while requests and requests[0] <= cutoff:
                requests.popleft()
            if len(requests) >= self.maximum:
                return max(1, math.ceil(requests[0] + self.window_seconds - now))
            requests.append(now)
            return 0
