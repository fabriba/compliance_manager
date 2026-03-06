import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from datetime import timedelta
from .const import SEVERITY_LEVELS, DEFAULT_SEVERITY


BINSENS_PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend({
    vol.Required("sensors"): vol.All(cv.ensure_list, [{
        vol.Optional("alias"): cv.string,
        vol.Required("name"): cv.string,
        vol.Optional("unique_id"): cv.string,
        vol.Optional("icon", default="mdi:shield-check"): cv.icon,
        # This is the native HA "target" schema (entity_id, device_id, area_id, label_id)
        vol.Required("compliance"): vol.All(
            cv.ensure_list,
            [vol.All(
                {
                    vol.Required("target"): cv.TARGET_SERVICE_FIELDS,
                    vol.Optional("alias"): cv.string,
                    vol.Optional("alias"): cv.string,
                    vol.Optional("attribute"): cv.string,
                    vol.Optional("expected_state"): vol.Any(cv.string, vol.Coerce(float), bool),
                    vol.Optional("expected_number"): vol.All(
                        vol.Schema({
                            vol.Optional("min"): vol.Coerce(float),
                            vol.Optional("max"): vol.Coerce(float),
                        }), cv.has_at_least_one_key("min", "max")
                    ),
                    vol.Optional("value_template"): cv.template,
                    vol.Optional("allowed_violations_count", default=0): vol.Coerce(int),
                    vol.Optional("allow_unavailable", default=False): cv.boolean,
                    vol.Optional("allow_unknown", default=False): cv.boolean,
                    vol.Optional("grace_period", default=timedelta(seconds=0)): cv.time_period,
                    vol.Optional("group_grace", default=False): cv.boolean,
                    vol.Optional("severity", default=DEFAULT_SEVERITY): vol.Any(
                        vol.All(cv.string, vol.Lower, vol.In(SEVERITY_LEVELS.keys())),  # Accepts strings like "critical" or number
                        vol.All(
                            vol.Schema({
                                vol.Required("level"): vol.All(vol.Coerce(int), vol.Range(min=0, max=9)),
                                vol.Optional("label"): cv.string,
                            })
                        )
                    )
                },
                        cv.has_at_least_one_key("expected_state", "expected_numeric", "value_template"),
                        cv.has_at_most_one_key("expected_state", "expected_numeric", "value_template")
            )]
        ),
    }]),
    vol.Optional("show_debug_attributes", default=False): cv.boolean,
})

SWITCH_PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend({
    vol.Optional("test_mode", default=False): cv.boolean,
    vol.Optional("test_groups_to_create", default=0): cv.positive_int,
    vol.Optional("show_cleanup_lab_service", default=False): cv.boolean,
    vol.Optional("show_debug_attributes", default=False): cv.boolean,
})
