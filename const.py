from datetime import timedelta

# LAB and DEBUG variables
TESTMODE = True
NUM_TEST_GROUPS = 4
LAB_PREFIX = "switch.compliance_manager_lab_tester_"
SHOW_DEBUG_ATTRIBUTES = True

# Integration Domain
DOMAIN = "compliance_manager"  # Change this to your actual folder name
PLATFORMS = ["binary_sensor"] if not TESTMODE else ["binary_sensor", "switch"]

SNOOZE_ATTRIBUTE = "snoozed"
GRACE_ATTRIBUTE = "grace_periods"
SEVERITY_LEVELS = {
    "critical": 0,
    "problem": 1,
    "warning": 2,
    "unusual": 3,
    "info": 4,
}
DEFAULT_SEVERITY = "problem"
DEFAULT_ICON = "mdi:shield-check"
DEFAULT_GRACE = timedelta(seconds=0)


