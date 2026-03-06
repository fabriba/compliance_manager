import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from datetime import timedelta
from .const import SEVERITY_LEVELS, DEFAULT_SEVERITY, MAX_LOGIC_CONTITIONS_DEPTH
from .schema_validators import _binarysensor_schema_validator

from voluptuous import Invalid

# 1. create condition fields that will be used in multiple parts of the code
SHARED_CONDITION_FIELDS = {
    vol.Optional("target"): cv.TARGET_SERVICE_FIELDS,
    vol.Optional("alias"): cv.string,
    vol.Optional("allow_unavailable", default=False): cv.boolean,
    vol.Optional("allow_unknown", default=False): cv.boolean,
    vol.Optional("grace_period", default=timedelta(seconds=0)): cv.time_period,
    vol.Optional("group_grace", default=False): cv.boolean,
    vol.Optional("severity", default=DEFAULT_SEVERITY): vol.Any(
        vol.All(cv.string, vol.Lower, vol.In(SEVERITY_LEVELS.keys())),
        vol.All(
            vol.Schema({
                vol.Required("level"): vol.All(vol.Coerce(int), vol.Range(min=0, max=10)),
                vol.Optional("label"): cv.string,
            })
        )
    ),
}

# 2. This is the working "Atomic" cell
ATONIC_CONDITION_SCHEMA = vol.All(
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
        **SHARED_CONDITION_FIELDS,
    },
    cv.has_at_least_one_key("expected_state", "expected_numeric", "value_template"),
    cv.has_at_most_one_key("expected_state", "expected_numeric", "value_template")
)

# 3. Define Logic Block - UPDATED to be recursive
def _get_recursive_condition_schema(depth=MAX_LOGIC_CONTITIONS_DEPTH):
    """Return a recursive condition item schema limited to `depth`."""

    def _logical_mapping_schema(d):
        # Definiamo cosa può esserci in un nodo logico
        child_item = _get_recursive_condition_schema(d - 1)
        return vol.Schema({
            vol.Optional("and"): vol.All(cv.ensure_list, [child_item]),
            vol.Optional("or"): vol.All(cv.ensure_list, [child_item]),
            vol.Optional("not"): vol.All(cv.ensure_list, [child_item]),
            # Permettiamo 'condition' come alias opzionale per retrocompatibilità/leggibilità
            vol.Optional("condition"): vol.All(cv.ensure_list, [child_item]),
            **SHARED_CONDITION_FIELDS,
        })

    if depth <= 0:
        return ATONIC_CONDITION_SCHEMA

    # Un nodo può essere o Atomico (foglia) o Logico (container)
    return vol.Any(ATONIC_CONDITION_SCHEMA, _logical_mapping_schema(depth))


COMPLIANCE_RULE_ITEM_SCHEMA = _get_recursive_condition_schema(MAX_LOGIC_CONTITIONS_DEPTH)

UNVALIDATED_PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend({
    vol.Required("sensors"): vol.All(cv.ensure_list, [{
        vol.Optional("alias"): cv.string,
        vol.Required("name"): cv.string,
        vol.Optional("unique_id"): cv.string,
        vol.Optional("icon", default="mdi:shield-check"): cv.icon,

        # Ogni elemento della lista compliance_rules è ora validato ricorsivamente
        vol.Required("compliance_rules"): vol.All(
            cv.ensure_list,
            [COMPLIANCE_RULE_ITEM_SCHEMA]
        ),
    }]),
    vol.Optional("show_debug_attributes", default=False): cv.boolean,
})

BINSENS_PLATFORM_SCHEMA = vol.All(UNVALIDATED_PLATFORM_SCHEMA, _binarysensor_schema_validator)

######################## SWITCH SCHEMA ###############

SWITCH_PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend({
    vol.Optional("test_mode", default=False): cv.boolean,
    vol.Optional("test_groups_to_create", default=0): cv.positive_int,
    vol.Optional("show_cleanup_lab_service", default=False): cv.boolean,
    vol.Optional("show_debug_attributes", default=False): cv.boolean,
})