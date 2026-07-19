import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Awaitable, TypeVar, Optional

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    expected_exception: tuple[type[Exception], ...] = (Exception,)

    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failures: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0, init=False)
    _successes_in_half_open: int = field(default=0, init=False)

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.time() - self._last_failure_time >= self.recovery_timeout:
                logger.info("Circuit breaker transitioning to HALF_OPEN")
                self._state = CircuitState.HALF_OPEN
                self._successes_in_half_open = 0
        return self._state

    async def call(self, func: Callable[..., Awaitable[T]], *args, **kwargs) -> T:
        if self.state == CircuitState.OPEN:
            raise CircuitOpenError("Circuit breaker is OPEN")

        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        if self._state == CircuitState.HALF_OPEN:
            self._successes_in_half_open += 1
            if self._successes_in_half_open >= 2:
                logger.info("Circuit breaker CLOSED after successful recovery")
                self._state = CircuitState.CLOSED
                self._failures = 0
        elif self._state == CircuitState.CLOSED:
            self._failures = 0

    def _on_failure(self):
        self._failures += 1
        self._last_failure_time = time.time()
        if self._state == CircuitState.HALF_OPEN:
            logger.warning("Circuit breaker OPEN again after failure in HALF_OPEN")
            self._state = CircuitState.OPEN
        elif self._failures >= self.failure_threshold:
            logger.warning(f"Circuit breaker OPEN after {self._failures} failures")
            self._state = CircuitState.OPEN

    def reset(self):
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._last_failure_time = 0


class CircuitOpenError(Exception):
    pass


class CircuitBreakerRegistry:
    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}

    def get(self, name: str, **kwargs) -> CircuitBreaker:
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(**kwargs)
        return self._breakers[name]

    def get_all_states(self) -> dict[str, str]:
        return {name: cb.state.value for name, cb in self._breakers.items()}

    def reset_all(self):
        for cb in self._breakers.values():
            cb.reset()


breaker_registry = CircuitBreakerRegistry()