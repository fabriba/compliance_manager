from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Any
import homeassistant.util.dt as dt_util
from homeassistant.helpers.event import async_track_point_in_time
from datetime import datetime



@dataclass
class RegistryEntry:
    """Combines an entity tracking ID with its expiry and timer handle."""
    entity_id: str
    expiry: datetime
    hass: Any = field(repr=False)
    callback: Callable = field(repr=False)
    unsub: Callable | None = field(default=None, init=False, repr=False)

    def __post_init__(self):
        """Automatically starts the timer as soon as the object is created."""
        if not self.is_expired:
            self.add_timer()

    @classmethod
    def create_from_iso(cls, entity_id: str, iso_str: str, hass: Any, callback: Callable):
        """Helper to create an entry from an ISO string (useful for restored state)."""
        dt_obj = dt_util.parse_datetime(iso_str) or dt_util.now()
        return cls(entity_id=entity_id, expiry=dt_obj, hass=hass, callback=callback)

    @property
    def expiry_iso(self) -> str:
        """Returns the expiry time as an ISO formatted string."""
        return self.expiry.isoformat()

    @property
    def is_expired(self) -> bool:
        return self.expiry <= dt_util.now()

    def add_timer(self):
        """Starts/restarts the Home Assistant timer."""
        self.cancel()
        self.unsub = async_track_point_in_time(
            self.hass,
            self.callback,
            self.expiry
        )

    def cancel(self):
        """Safely stop the Home Assistant timer."""
        if self.unsub:
            self.unsub()
            self.unsub = None

    def __del__(self):
        """Ensures the timer is cancelled when the object is removed from memory."""
        self.cancel()

class ComplianceTimerMixin:
    """Helper class to manage creation and restoration of timers."""

    def _create_timer(self, eid: str, expiry: datetime) -> RegistryEntry:
        """Creates a new timer with the standard entity callback."""
        return RegistryEntry(
            eid,
            expiry,
            self.hass,
            self._update_event_handler
        )

    def _restore_timer(self, eid: str, iso_str: str) -> RegistryEntry:
        """Restores a timer from an ISO string, used during state restoration."""
        return RegistryEntry.create_from_iso(
            eid,
            iso_str,
            self.hass,
            self._update_event_handler
        )