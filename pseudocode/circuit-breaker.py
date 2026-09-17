"""
PayScale HTTPE - Circuit Breaker Engine
File: pseudocode/circuit-breaker.py
Evaluates: Cascading failure prevention, state transitions (CLOSED, OPEN, HALF_OPEN)
"""

import time
import threading
from typing import Callable, Any

class CircuitBreakerOpenException(Exception):
    pass

class CircuitBreaker:
    STATE_CLOSED = "CLOSED"
    STATE_OPEN = "OPEN"
    STATE_HALF_OPEN = "HALF_OPEN"

    def __init__(self, name: str, failure_threshold: int = 3, recovery_timeout_sec: float = 15.0, half_open_max_probes: int = 2):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_sec = recovery_timeout_sec
        self.half_open_max_probes = half_open_max_probes

        self.state = self.STATE_CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_state_change = time.time()
        self.lock = threading.Lock()

    def execute(self, action: Callable[..., Any], fallback: Callable[..., Any], *args, **kwargs) -> Any:
        """
        Executes protected action wrapped by circuit breaker logic.
        Routes to fallback on trip or downstream degradation.
        """
        with self.lock:
            current_time = time.time()

            # Transition: OPEN -> HALF_OPEN after timeout cooldown
            if self.state == self.STATE_OPEN:
                if current_time - self.last_state_change >= self.recovery_timeout_sec:
                    self.state = self.STATE_HALF_OPEN
                    self.last_state_change = current_time
                    self.success_count = 0
                    self.failure_count = 0
                else:
                    return fallback(*args, **kwargs)

        try:
            # Execute protected downstream call
            result = action(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure(e)
            return fallback(*args, **kwargs)

    def _on_success(self):
        with self.lock:
            if self.state == self.STATE_HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.half_open_max_probes:
                    # Service recovered -> transition to CLOSED
                    self.state = self.STATE_CLOSED
                    self.failure_count = 0
                    self.last_state_change = time.time()
            elif self.state == self.STATE_CLOSED:
                self.failure_count = 0

    def _on_failure(self, exception: Exception):
        with self.lock:
            self.failure_count += 1
            if self.state == self.STATE_HALF_OPEN or self.failure_count >= self.failure_threshold:
                # Trip breaker -> transition to OPEN
                self.state = self.STATE_OPEN
                self.last_state_change = time.time()