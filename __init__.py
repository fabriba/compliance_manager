import logging
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.const import (
    CONF_NAME,
    CONF_ENTITY_ID,
    CONF_ENTITIES,
    CONF_DEVICE_ID,
    CONF_AREA_ID,
)

from .const import (
    DOMAIN,
    CONF_BINARY_SENSORS,
    CONF_GLOBAL_SENSOR,
    CONF_COMPLIANCE_CONDITIONS,
    CONF_EXPECTED_STATE,
    CONF_EXPECTED_NUMERIC,
    CONF_VALUE_TEMPLATE,
    CONF_GRACE_PERIOD,
    CONF_SEVERITY,
    DEFAULT_SEVERITY,
    SERVICE_SNOOZE,
    ATTR_TARGET_ENTITY,
    ATTR_DURATION,
)

_LOGGER = logging.getLogger(__name__)

# --- SCHEMI DI VALIDAZIONE ---

# Schema per le singole condizioni atomiche o nidificate (AND, OR, NOT)
CONDITION_SCHEMA = vol.Schema({
    vol.Optional("alias"): cv.string,
    vol.Optional("attribute"): cv.string,
    vol.Optional(CONF_EXPECTED_STATE): vol.Any(cv.string, vol.All(cv.ensure_list, [cv.string])),
    vol.Optional(CONF_EXPECTED_NUMERIC): cv.string,
    vol.Optional(CONF_VALUE_TEMPLATE): cv.template,
    vol.Optional("or"): vol.All(cv.ensure_list, [vol.Self]),
    vol.Optional("and"): vol.All(cv.ensure_list, [vol.Self]),
    vol.Optional("not"): vol.Self,
})

# Schema per l'override a livello di LABEL
LABEL_OVERRIDE_SCHEMA = vol.Schema({
    vol.Required("label"): cv.string,
    vol.Optional(CONF_GRACE_PERIOD): cv.time_period,
    vol.Optional(CONF_SEVERITY): cv.string,
})

# Schema per l'override a livello di ENTITÀ
ENTITY_OVERRIDE_SCHEMA = vol.Schema({
    vol.Required("entity"): cv.entity_id,
    vol.Optional(CONF_GRACE_PERIOD): cv.time_period,
    vol.Optional(CONF_SEVERITY): cv.string,
})

# Schema per ogni Regola di Conformità (Binary Sensor)
SENSOR_CONFIG_SCHEMA = vol.Schema({
    vol.Required(CONF_NAME): cv.string,
    vol.Optional(CONF_ENTITY_ID): cv.string,
    
    # Selezione Target (Aree, Device, Label o Entità semplici)
    vol.Optional("target"): vol.Schema({
        vol.Optional(CONF_ENTITY_ID): vol.All(cv.ensure_list, [cv.entity_id]),
        vol.Optional(CONF_DEVICE_ID): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_AREA_ID): vol.All(cv.ensure_list, [cv.string]),
    }),
    
    # Overrides con logica gerarchica
    vol.Optional("labels"): vol.All(cv.ensure_list, [vol.Any(cv.string, LABEL_OVERRIDE_SCHEMA)]),
    vol.Optional(CONF_ENTITIES): vol.All(cv.ensure_list, [vol.Any(cv.entity_id, ENTITY_OVERRIDE_SCHEMA)]),
    
    # Parametri globali della regola
    vol.Required(CONF_COMPLIANCE_CONDITIONS): vol.All(cv.ensure_list, CONDITION_SCHEMA),
    vol.Optional(CONF_GRACE_PERIOD, default="00:00:00"): cv.time_period,
    vol.Optional(CONF_SEVERITY, default=DEFAULT_SEVERITY): cv.string,
})

# Schema radice dell'integrazione
CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Optional(CONF_GLOBAL_SENSOR): vol.Schema({
            vol.Required(CONF_NAME): cv.string,
            vol.Optional(CONF_ENTITY_ID): cv.string,
        }),
        vol.Required(CONF_BINARY_SENSORS): vol.All(cv.ensure_list, [SENSOR_CONFIG_SCHEMA]),
    })
}, extra=vol.ALLOW_EXTRA)

# --- LOGICA DI SETUP ---

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Configura il componente Compliance Manager leggendo lo YAML."""
    if DOMAIN not in config:
        return True

    conf = config[DOMAIN]
    
    # Salviamo la configurazione in hass.data
    hass.data.setdefault(DOMAIN, conf)

    # REGISTRAZIONE SERVIZIO SNOOZE
    async def handle_snooze(call: ServiceCall):
        entity_ids = call.data.get("entity_id")
        target_sub_entity = call.data.get(ATTR_TARGET_ENTITY)
        duration = call.data.get(ATTR_DURATION)

        # Cerchiamo l'oggetto entità per ogni ID passato
        # Nota: usiamo l'entity_component registrato dalla piattaforma binary_sensor
        component: EntityComponent = hass.data.get("binary_sensor_component")
        if not component:
            _LOGGER.error("Componente binary_sensor non ancora pronto per lo snooze")
            return

        for eid in entity_ids:
            entity = component.get_entity(eid)
            if entity and hasattr(entity, "async_snooze_entity"):
                await entity.async_snooze_entity(target_sub_entity, duration)
            else:
                _LOGGER.warning(f"L'entità {eid} non supporta lo snooze o non è stata trovata")

    hass.services.async_register(
        DOMAIN,
        SERVICE_SNOOZE,
        handle_snooze,
        schema=vol.Schema({
            vol.Required("entity_id"): cv.comp_entity_ids,
            vol.Required(ATTR_TARGET_ENTITY): cv.entity_id,
            vol.Required(ATTR_DURATION): cv.time_period,
        }),
    )

    # Iniziamo il caricamento della piattaforma binary_sensor
    hass.async_create_task(
        hass.helpers.discovery.async_load_platform(
            "binary_sensor", 
            DOMAIN, 
            conf, 
            config
        )
    )

    _LOGGER.info("Compliance Manager: Integrazione e servizio Snooze caricati.")
    return True
