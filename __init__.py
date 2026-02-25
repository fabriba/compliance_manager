"""The example sensor integration."""
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.reload import async_setup_reload_service

DOMAIN = "compliance_manager"
PLATFORMS = ["binary_sensor"] # o "sensor" a seconda di cosa usi

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Compliance Manager component."""
    # Questo abilita il tasto magico in Developer Tools
    await async_setup_reload_service(hass, DOMAIN, PLATFORMS)
    return True
