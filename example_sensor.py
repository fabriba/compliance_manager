
"""Platform for sensor integration."""
from __future__ import annotations
import random
from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
)

from homeassistant.helpers.restore_state import RestoreEntity
from datetime import timedelta
from homeassistant.helpers.event import async_track_point_in_time

from homeassistant.util import dt as dt_util


######### ExampleSensor #############
class ExampleSensor(BinarySensorEntity, RestoreEntity):
    """Sensor that changes state exactly every 3-6 seconds."""

    _attr_should_poll = False  # Manual timing control

    def __init__(self, name: str) -> None:
        self._attr_name = name
        self._attr_unique_id = f"sample_compliance_{self._attr_name.lower().replace(' ', '_')}"
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        """Start the cycle as soon as the sensor is ready."""
        self._schedule_next_toggle()

    def _schedule_next_toggle(self) -> None:
        """Schedule the next state change between 3 and 6 seconds."""
        wait_time = random.randint(3, 6)
        next_run = dt_util.now() + timedelta(seconds=wait_time)

        # Request HA for a wake-up call in the future
        async_track_point_in_time(self.hass, self._async_handle_toggle, next_run)

    async def _async_handle_toggle(self, _now) -> None:
        """Execute the toggle and reschedule."""
        rand = random.random()

        if rand < 0.0833:
            # 8.33% probability: State ON
            self._attr_is_on = True
            self._attr_available = True
        elif rand < 0.1666:
            # 8.33% probability: State UNAVAILABLE
            self._attr_is_on = False  # Irrelevant if unavailable
            self._attr_available = False
        elif rand < 0.25:
            # 8.33% probability: State UNKNOWN
            self._attr_is_on = None  # Represents 'unknown' for a binary_sensor
            self._attr_available = True
        else:
            # 75% probability: State OK (OFF)
            self._attr_is_on = False
            self._attr_available = True

        self.async_write_ha_state()  # Notify the UI and ComplianceManager of the change
        self._schedule_next_toggle()  # Restart the cycle
