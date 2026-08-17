"""Pure control-lease domain logic."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class ControlError(Exception):
    """Base class for errors safe to map to an API response."""


class ConflictError(ControlError):
    """The requested action conflicts with the current controller."""


class ValidationError(ControlError):
    """External input failed validation."""


class ControlLease:
    """Coordinates one cooperative controller for a shared desktop."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        agent_ttl: float = 12.0,
        human_ttl: float = 30.0,
    ) -> None:
        self._clock = clock
        self._ttls = {"agent": agent_ttl, "human": human_ttl}
        self._owner = "none"
        self._owner_id: str | None = None
        self._expires_at = 0.0
        self._lock = threading.RLock()

    def _expire(self) -> None:
        if self._owner != "none" and self._clock() >= self._expires_at:
            self._owner = "none"
            self._owner_id = None
            self._expires_at = 0.0

    def _set_owner(self, actor: str, owner_id: str) -> dict[str, object]:
        if not isinstance(owner_id, str) or not 1 <= len(owner_id) <= 128:
            raise ValidationError("ownerId must contain 1 to 128 characters")
        self._owner = actor
        self._owner_id = owner_id
        self._expires_at = self._clock() + self._ttls[actor]
        return self.state()

    def state(self) -> dict[str, object]:
        with self._lock:
            self._expire()
            remaining = max(0.0, self._expires_at - self._clock())
            return {
                "owner": self._owner,
                "ownerId": self._owner_id,
                "expiresInMs": round(remaining * 1000),
            }

    def claim_human(self, owner_id: str) -> dict[str, object]:
        """A human claim always preempts an agent claim."""
        with self._lock:
            self._expire()
            return self._set_owner("human", owner_id)

    def claim_agent(self, owner_id: str) -> dict[str, object]:
        with self._lock:
            self._expire()
            if self._owner == "human":
                raise ConflictError("a human currently controls the desktop")
            if self._owner == "agent" and self._owner_id != owner_id:
                raise ConflictError("another agent currently controls the desktop")
            return self._set_owner("agent", owner_id)

    def heartbeat(self, actor: str, owner_id: str) -> dict[str, object]:
        with self._lock:
            self.assert_owner(actor, owner_id)
            self._expires_at = self._clock() + self._ttls[actor]
            return self.state()

    def release(self, actor: str, owner_id: str) -> dict[str, object]:
        with self._lock:
            self.assert_owner(actor, owner_id)
            self._owner = "none"
            self._owner_id = None
            self._expires_at = 0.0
            return self.state()

    def assert_owner(self, actor: str, owner_id: str) -> None:
        with self._lock:
            self._expire()
            if actor not in self._ttls:
                raise ValidationError("actor must be human or agent")
            if self._owner != actor or self._owner_id != owner_id:
                raise ConflictError(f"{actor} does not hold the control lease")

    def extend_if_owner(self, actor: str, owner_id: str) -> None:
        """Renew TTL for the current owner without expiring a still-matching lease."""
        with self._lock:
            if self._owner == actor and self._owner_id == owner_id:
                self._expires_at = self._clock() + self._ttls[actor]
                return
            self.assert_owner(actor, owner_id)
