DOMAIN = "compliance_manager"

CONF_BINARY_SENSORS = "binary_sensors"
CONF_GLOBAL_SENSOR = "global_compliance_sensor"
CONF_COMPLIANCE_CONDITIONS = "compliance_conditions"
CONF_EXPECTED_STATE = "expected_state"
CONF_EXPECTED_NUMERIC = "expected_numeric_state"
CONF_VALUE_TEMPLATE = "value_template"
CONF_GRACE_PERIOD = "grace_period"
CONF_SEVERITY = "severity"

# User Preferences
DEFAULT_SEVERITY = "Unusual"

SEVERITY_MAP = {
    "critical": 1, "1": 1,
    "problem": 2, "2": 2,  # Changed from Error to Problem
    "warning": 3, "3": 3,
    "unusual": 4, "4": 4,  # Now the default
    "note": 5, "5": 5
}

SEVERITY_LABELS = {1: "Critical", 2: "Problem", 3: "Warning", 4: "Unusual", 5: "Note"}

# Services
SERVICE_SNOOZE = "snooze"
ATTR_TARGET_ENTITY = "target_entity"
ATTR_DURATION = "duration"
