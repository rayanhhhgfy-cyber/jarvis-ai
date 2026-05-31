# ====================================================================
# JARVIS OMEGA — Event Bus
# ====================================================================
"""
Internal publish-subscribe event bus for decoupled communication
between backend components. Supports async handlers and wildcards.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable, Coroutine, Dict, List, Optional

from shared.constants import EventType
from shared.logger import get_logger

log = get_logger("event_bus")


class EventBus:
    """
    Async publish-subscribe event bus.

    Components subscribe to event types and receive payloads
    when those events are published. Supports wildcard subscriptions.
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._history: List[Dict[str, Any]] = []
        self._max_history = 1000
        self._lock = asyncio.Lock()

    def subscribe(
        self,
        event_type: str | EventType,
        handler: Callable[..., Coroutine],
    ) -> None:
        """Subscribe a handler to an event type."""
        key = event_type.value if isinstance(event_type, EventType) else event_type
        self._subscribers[key].append(handler)
        log.debug("event_subscribed", event_type=key, handler=handler.__name__)

    def unsubscribe(
        self,
        event_type: str | EventType,
        handler: Callable,
    ) -> None:
        """Remove a handler subscription."""
        key = event_type.value if isinstance(event_type, EventType) else event_type
        if key in self._subscribers:
            self._subscribers[key] = [h for h in self._subscribers[key] if h != handler]

    async def publish(
        self,
        event_type: str | EventType,
        payload: Optional[Dict[str, Any]] = None,
        source: str = "system",
    ) -> None:
        """Publish an event to all subscribers."""
        key = event_type.value if isinstance(event_type, EventType) else event_type
        payload = payload or {}

        event = {
            "type": key,
            "payload": payload,
            "source": source,
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Store in history
        async with self._lock:
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

        # Notify specific subscribers
        handlers = self._subscribers.get(key, [])
        # Also notify wildcard subscribers
        handlers += self._subscribers.get("*", [])

        if handlers:
            log.debug("event_published", event_type=key, handler_count=len(handlers))

        tasks = []
        for handler in handlers:
            try:
                tasks.append(asyncio.create_task(handler(event)))
            except Exception as e:
                log.error("event_handler_error", event_type=key, handler=handler.__name__, error=str(e))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def get_history(
        self,
        event_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get recent event history, optionally filtered by type."""
        if event_type:
            filtered = [e for e in self._history if e["type"] == event_type]
        else:
            filtered = self._history
        return filtered[-limit:]

    @property
    def subscriber_count(self) -> int:
        return sum(len(v) for v in self._subscribers.values())


# Global event bus instance
event_bus = EventBus()
