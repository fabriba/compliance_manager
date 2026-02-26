import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from datetime import timedelta
from .const import SEVERITY_LEVELS, DEFAULT_SEVERITY

# 1. This is your working "Atomic" cell
CONDITION_SCHEMA = vol.All(
    {
        vol.Optional("attribute"): cv.string,
        vol.Optional("expected_state"): vol.Any(cv.string, vol.Coerce(float), bool),
        vol.Optional("expected_numeric"): vol.All(
            vol.Schema({
                vol.Optional("min"): vol.Coerce(float),
                vol.Optional("max"): vol.Coerce(float),
            }), cv.has_at_least_one_key("min", "max")
        ),
        vol.Optional("value_template"): cv.template,
    },
    cv.has_at_least_one_key("expected_state", "expected_numeric", "value_template"),
    cv.has_at_most_one_key("expected_state", "expected_numeric", "value_template")
)

# 2. Define a "Logic Block" that can contain Atomic Cells
# This allows one level of nesting (Logic -> Atomic) which is usually enough for 99% of cases
LOGIC_SCHEMA = vol.Schema({
    vol.Optional("and"): vol.All(cv.ensure_list, [CONDITION_SCHEMA]),
    vol.Optional("or"): vol.All(cv.ensure_list, [CONDITION_SCHEMA]),
    vol.Optional("not"): CONDITION_SCHEMA,
})

# 3. Update the Rule to accept either
# vol.Any(Atomic, Logic, List of Atomic, List of Logic)
FINAL_CONDITION_VALIDATOR = vol.Any(
    CONDITION_SCHEMA,
    LOGIC_SCHEMA,
    vol.All(cv.ensure_list, [vol.Any(CONDITION_SCHEMA, LOGIC_SCHEMA)])
)

PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend({
    vol.Required("sensors"): vol.All(cv.ensure_list, [{
        vol.Required("name"): cv.string,
        vol.Optional("unique_id"): cv.string,
        vol.Optional("icon", default="mdi:shield-check"): cv.icon,
        # This is the native HA "target" schema (entity_id, device_id, area_id, label_id)
        vol.Required("rules"): vol.All(
            cv.ensure_list,
            [vol.All(
                {
                    vol.Required("target"): cv.TARGET_SERVICE_FIELDS,
                    vol.Required("condition"): vol.Any(CONDITION_SCHEMA, vol.All(
                        cv.ensure_list, [CONDITION_SCHEMA])),
                    vol.Optional("allow_unavailable", default=False): cv.boolean,
                    vol.Optional("allow_unknown", default=False): cv.boolean,
                    vol.Optional("grace_period", default=timedelta(seconds=0)): cv.time_period,
                    vol.Optional("group_grace", default=False): cv.boolean,
                    vol.Optional("severity", default=DEFAULT_SEVERITY): vol.Any(
                        vol.All(cv.string, vol.Lower, vol.In(SEVERITY_LEVELS.keys())),  # Accepts strings like "critical" or numberd
                        vol.All(
                            vol.Schema({
                                vol.Required("level"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
                                vol.Optional("label"): cv.string,
                            })
                        )
                    )
                }
            )]
        ),
    }]),
})
