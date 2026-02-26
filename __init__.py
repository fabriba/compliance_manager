"""The Compliance Manager integration."""
from __future__ import annotations
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.reload import async_setup_reload_service
from homeassistant.helpers import entity_registry as er, discovery

from .const import DOMAIN, PLATFORMS, TESTMODE

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Compliance Manager component."""

    # 1. Standard reload service for the main platforms
    await async_setup_reload_service(hass, DOMAIN, PLATFORMS)

    # 2. Fix: Explicitly load/reload the switch platform if TESTMODE is on
    if TESTMODE:
        # This ensures that even on reload, the switch platform is triggered
        hass.async_create_task(
            discovery.async_load_platform(hass, "switch", DOMAIN, {}, config)
        )

        async def handle_cleanup_test_lab(call):
            """Remove all lab entities from the registry."""
            ent_reg = er.async_get(hass)

            # Using the unique_id prefix which is the most reliable way
            target_prefix = "compliance_lab_"

            to_remove = [
                entry.entity_id
                for entry in ent_reg.entities.values()
                if entry.platform == DOMAIN and
                   entry.unique_id and
                   entry.unique_id.startswith(target_prefix)
            ]

            _LOGGER.warning("Cleaning up %s lab entities", len(to_remove))
            for eid in to_remove:
                ent_reg.async_remove(eid)

        hass.services.async_register(DOMAIN, "cleanup_test_lab", handle_cleanup_test_lab)

    return True
