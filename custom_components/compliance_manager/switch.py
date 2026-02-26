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

from .const import NUM_TEST_GROUPS, TESTMODE, LAB_PREFIX

_LOGGER = logging.getLogger(__name__)

# Centralizing the prefix to ensure it matches __init__.py exactly


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the lab switches."""
    if not TESTMODE:
        return

    ent_reg = er.async_get(hass)
    entities = []

    for i in range(1, NUM_TEST_GROUPS + 1):
        unav_id = f"{LAB_PREFIX}{i}_unav"
        unkn_id = f"{LAB_PREFIX}{i}_unkn"
        main_id = f"{LAB_PREFIX}{i}"

        # Logic to check if unique_id already exists to prevent log errors
        # 1. Create the Modifier Switches using the prefix
        if not ent_reg.async_get_entity_id("switch", "compliance_manager", unav_id):
            entities.append(ModifierSwitch(unav_id, f"Force Unav (G{i})"))

        if not ent_reg.async_get_entity_id("switch", "compliance_manager", unkn_id):
            entities.append(ModifierSwitch(unkn_id, f"Force Unkn (G{i})"))

        # 2. Create the Main Switch using the prefix
        if not ent_reg.async_get_entity_id("switch", "compliance_manager", main_id):
            entities.append(LabSwitch(i, f"switch.{unav_id}", f"switch.{unkn_id}"))

    if entities:
        async_add_entities(entities)

class ModifierSwitch(SwitchEntity, RestoreEntity):
    """Simple switch to toggle lab conditions (Unavailable/Unknown)."""
    def __init__(self, custom_id: str, name: str) -> None:
        self.entity_id = f"switch.{custom_id}"
        self._attr_name = name
        # Unique ID must be truly unique, using the entity_id string is safe
        # FIXED: Removed the double prefixing here
        self._attr_unique_id = custom_id
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if last_state := await self.async_get_last_state():
            self._attr_is_on = (last_state.state == "on")

    async def async_turn_on(self, **kwargs) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()

class LabSwitch(SwitchEntity, RestoreEntity):
    """The main switch being monitored by ComplianceManager."""

    def __init__(self, index: int, sw_unav: str, sw_unkn: str) -> None:
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
        await super().async_added_to_hass()
        if last_state := await self.async_get_last_state():
            self._attr_is_on = (last_state.state == "on")

        self.async_on_remove(
            async_track_state_change_event(self.hass, [self._sw_unav, self._sw_unkn], self._update_availability)
        )
        await self._update_availability()

    async def _update_availability(self, event=None) -> None:
        """Update availability and 'unknown' status based on modifiers."""
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
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()
