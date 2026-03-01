"""Test Lab for Compliance Manager.
        these switches are only created IF TESTMODE is on in const.py
        while TESTMODE is on, an

        action can be performed:
            action: compliance_manager.cleanup_test_lab
            data: {}
"""
from __future__ import annotations

import logging
from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers import entity_registry as er
from .schema import SWITCH_PLATFORM_SCHEMA as PLATFORM_SCHEMA
_ = PLATFORM_SCHEMA # this is just so it's not greyed out, and I am not tempted to delete the line

from .const import LAB_PREFIX


_LOGGER = logging.getLogger(__name__)

# Centralizing the prefix to ensure it matches __init__.py exactly


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """
    Initializes the Test Lab switch environment.
    If TESTMODE is active, it generates the requested number of
    triplet-switches (Main, Unav, Unkn) and registers them in the
    system for developer testing.
    """
    cmp_mgr_cfg = config
    test_mode = cmp_mgr_cfg.get("test_mode", False)
    num_groups = cmp_mgr_cfg.get("test_groups_to_create", 0)

    """Set up the lab switches."""
    if not test_mode or num_groups == 0:
        return

    ent_reg = er.async_get(hass)
    entities = []
    # Inside async_setup_platform in switch.py

    for i in range(1, num_groups + 1):
        unav_id = f"{LAB_PREFIX}{i}_unav"
        unkn_id = f"{LAB_PREFIX}{i}_unkn"
        main_id = f"{LAB_PREFIX}{i}"



        # We append all entities. HA will handle the merging based on unique_id.
        entities.append(ModifierSwitch(unav_id, f"Force Unav (G{i})"))
        entities.append(ModifierSwitch(unkn_id, f"Force Unkn (G{i})"))

        # We pass the full entity_id strings to the main LabSwitch
        entities.append(LabSwitch(i, f"switch.{unav_id}", f"switch.{unkn_id}"))

    if entities:
        async_add_entities(entities)

class ModifierSwitch(SwitchEntity, RestoreEntity):
    """Simple switch to toggle lab conditions (Unavailable/Unknown)."""
    def __init__(self, custom_id: str, name: str) -> None:
        """  Initializes an override switch (Unavailable or Unknown).
        These helper entities are used by the LabSwitch to simulate
        hardware communication failures or undefined entity states
        during integration testing.
        """
        self.entity_id = f"switch.{custom_id}"
        self._attr_name = name
        # Unique ID must be truly unique, using the entity_id string is safe
        # FIXED: Removed the double prefixing here
        self._attr_unique_id = custom_id
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        """Restores the toggle state from the database upon startup."""
        await super().async_added_to_hass()
        if last_state := await self.async_get_last_state():
            self._attr_is_on = (last_state.state == "on")

    async def async_turn_on(self, **kwargs) -> None:
        """Sets the override switch to ON and updates its state."""
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Sets the override switch to OFF and updates its state."""
        self._attr_is_on = False
        self.async_write_ha_state()

class LabSwitch(SwitchEntity, RestoreEntity):
    """The main switch being monitored by ComplianceManager."""

    def __init__(self, index: int, sw_unav: str, sw_unkn: str) -> None:
        """  Initializes a primary test switch.
        Links the main switch to its two modifier entities, allowing
        it to dynamically change its own availability or state
        based on the override toggles.
        """
        # Matches the startswith check in __init__.py
        uid = f"{LAB_PREFIX}{index}"
        self.entity_id = f"switch.{uid}"
        self._attr_name = f"Tester Switch {index}"
        # FIXED: Removed the double prefixing here
        self._attr_unique_id = uid
        self._sw_unav = sw_unav
        self._sw_unkn = sw_unkn
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        """  Sets up the lab switch in Home Assistant.
        Restores previous state and subscribes to state change events
        from its linked 'unav' and 'unkn' modifier switches to
        dynamically update its own status.
        """
        await super().async_added_to_hass()
        if last_state := await self.async_get_last_state():
            self._attr_is_on = (last_state.state == "on")

        self.async_on_remove(
            async_track_state_change_event(self.hass, [self._sw_unav, self._sw_unkn], self._update_availability)
        )
        await self._update_availability()

    async def _update_availability(self, event=None) -> None:
        """  Calculates the effective availability of the test switch.
        Checks the status of linked modifier switches to force
        'unavailable' or 'unknown' states, or restores normal
        operation if no overrides are active.
        """
        s_unav = self.hass.states.get(self._sw_unav)
        s_unkn = self.hass.states.get(self._sw_unkn)

        if s_unav and s_unav.state == "on":
            self._attr_available = False
        elif s_unkn and s_unkn.state == "on":
            self._attr_available = True
            self._attr_is_on = None
        else:
            self._attr_available = True
            if self._attr_is_on is None:
                if last_state := await self.async_get_last_state():
                    self._attr_is_on = (last_state.state == "on")

        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        """Turns the lab switch ON."""
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turns the lab switch OFF."""
        self._attr_is_on = False
        self.async_write_ha_state()
