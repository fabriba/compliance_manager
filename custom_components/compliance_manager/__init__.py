"""The Compliance Manager integration."""
from __future__ import annotations
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.reload import async_setup_reload_service
from homeassistant.helpers import entity_registry as er, discovery

from .const import DOMAIN, PLATFORMS
from .services import async_register_services # Importa la nuova funzione

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """ Initializes the Compliance Manager component.
        Sets up the standard reload service and, if TESTMODE is enabled,
        dynamically loads the switch platform for the lab environment.
        It also registers the 'cleanup_test_lab' service to purge lab-related
        entities from the Home Assistant registry
    """
    cmp_mgr_cfg = get_cmp_mgr_cfg(config)

    # 1. Register Standard "reload" service for the main platforms
    await async_setup_reload_service(hass, DOMAIN, PLATFORMS)

    # 2. Register custom services (snooze, cleanup, ...)
    await async_register_services(hass)

    test_mode = cmp_mgr_cfg.get("test_mode", False)
    # 3. Fix: Explicitly load/reload the switch platform if TESTMODE is on
    if test_mode:
        # This launches async_setup_platform from the switch.py file
        hass.async_create_task(
            discovery.async_load_platform(hass, "switch", DOMAIN, {}, config)
        )

    return True

def get_cmp_mgr_cfg(global_config):
    """
    Extracts and merges configurations matching DOMAIN from all PLATFORMS.
    """
    compl_mgr_config = {}

    for platform in PLATFORMS:
        # standardizing to list to handle single-entry dicts
        p_configs = global_config.get(platform, [])
        if isinstance(p_configs, dict):
            p_configs = [p_configs]

        for p_conf in p_configs:
            if p_conf.get("platform") == DOMAIN:
                # Warning: .update() overwrites duplicate keys across different entries
                compl_mgr_config.update(p_conf)

    return compl_mgr_config