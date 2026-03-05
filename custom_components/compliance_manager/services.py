import logging
import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv, entity_registry as er
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

## NOTE:
# await async_setup_reload_service(hass, DOMAIN, PLATFORMS)
# this is directly loaded in __init__ because it's a standard service and we don't define it here.

async def async_register_services(hass: HomeAssistant):
    """
    Main service handler for the 'snooze' functionality.
    It extracts target entity IDs and duration from the service call data,
    identifies the corresponding ComplianceManagerSensor instances,
    and triggers the snooze logic. If no specific entity is provided,
    it automatically snoozes all active violations for the target sensors.
    """

    async def handle_snooze(call: ServiceCall):
        """Service handler for silencing (snooze)"""
        target_ids = call.data.get("entity_id", [])
        sub_entities = call.data.get("sub_entities", [])
        duration = call.data.get("duration")

        #  Recover saved instances from  hass.data
        entities = hass.data.get(DOMAIN, {}).get("binary_sensor_instances", [])

        for entity in entities:
            if entity.entity_id in target_ids:
                await entity.async_snooze(sub_entities, duration)

    async def handle_cleanup_test_lab(call: ServiceCall):
        """ Cleanup test lab entities all switches, typically 3 x 40 = 120 entities ."""
        ent_reg = er.async_get(hass)
        entities_to_remove = [
            entry.entity_id
            for entry in ent_reg.entities.values()
            if entry.platform == DOMAIN and "lab_test_" in entry.entity_id
        ]
        for entity_id in entities_to_remove:
            _LOGGER.info("Removing entity lab: %s", entity_id)
            ent_reg.async_remove(entity_id)

    # Actually register the service to ha
    hass.services.async_register(
        DOMAIN, "snooze", handle_snooze,
        schema=vol.Schema({
            vol.Required("entity_id"): cv.entity_ids,
            vol.Optional("sub_entities"): cv.ensure_list,
            vol.Required("duration"): cv.time_period,
        })
    )

    hass.services.async_register(
        DOMAIN, "cleanup_test_lab", handle_cleanup_test_lab
    )