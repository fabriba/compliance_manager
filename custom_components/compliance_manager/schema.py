import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from datetime import timedelta
from .const import SEVERITY_LEVELS, DEFAULT_SEVERITY


# 1. This is your working "Atomic" cell
CONDITION_SCHEMA = vol.All(
    {
        vol.Optional("alias"): cv.string,
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

# 2. Define Logic Block - UPDATED to be recursive
def _get_recursive_condition_schema(depth=5):
    """Return a recursive condition item schema limited to `depth`."""
    if depth <= 0:
        # at leaf only allow atomic conditions
        return CONDITION_SCHEMA

    # placeholder for recursion
    def make_child_schema(d):
        return vol.Any(CONDITION_SCHEMA, _logical_mapping_schema(d))

    def _logical_mapping_schema(d):
        # each operator must map to a list of condition items (recursing with depth-1)
        child_item = _get_recursive_condition_schema(d - 1)
        return vol.All(
            {
                vol.Optional("alias"): cv.string,
                vol.Optional("and"): vol.All(cv.ensure_list, [child_item]),
                vol.Optional("or"): vol.All(cv.ensure_list, [child_item]),
                # 'not' can be a single child or a list of children; normalize to list
                vol.Optional("not"): vol.Any(child_item, vol.All(cv.ensure_list, [child_item])),
            },
            cv.has_at_least_one_key("and", "or", "not")
        )

    return vol.Any(CONDITION_SCHEMA, _logical_mapping_schema(depth))


# Final validator accepts either:
#  - a single condition item (mapping-style), or
#  - a sequence (list) of condition items (sequence-style)
FINAL_CONDITION_VALIDATOR = vol.Any(
    _get_recursive_condition_schema(6),
    vol.All(cv.ensure_list, [_get_recursive_condition_schema(6)])
)

BS_PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend({
    vol.Required("sensors"): vol.All(cv.ensure_list, [{
        vol.Optional("alias"): cv.string,
        vol.Required("name"): cv.string,
        vol.Optional("unique_id"): cv.string,
        vol.Optional("icon", default="mdi:shield-check"): cv.icon,
        # This is the native HA "target" schema (entity_id, device_id, area_id, label_id)
        vol.Required("rules"): vol.All(
            cv.ensure_list,
            [vol.All(
                {
                    vol.Required("target"): cv.TARGET_SERVICE_FIELDS,
                    vol.Optional("alias"): cv.string,
                    vol.Required("condition"): FINAL_CONDITION_VALIDATOR,
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
    vol.Optional("show_debug_attributes", default=False): cv.boolean,
})

SWITCH_PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend({
    vol.Optional("test_mode", default=False): cv.boolean,
    vol.Optional("test_groups_to_create", default=0): cv.positive_int,
    vol.Optional("show_cleanup_lab_service", default=False): cv.boolean,
    vol.Optional("show_debug_attributes", default=False): cv.boolean,
})