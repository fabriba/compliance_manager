from datetime import timedelta

# LAB and DEBUG variables
LAB_PREFIX = "compliance_manager_lab_tester_"

# Integration Domain
DOMAIN = "compliance_manager"  # Change this to your actual folder name
PLATFORMS = ["binary_sensor", "switch"]

from typing import Final


class ComplianceManagerAttributes:
    """Constants for ComplianceManager Attributes."""
    # Core Attributes
    SEVERITY = "severity"
    SEVERITY_LABEL = "severity_label"
    GRACE_PERIODS = "grace_periods"
    ACTIVE_VIOLATIONS = "active_violations"
    ACTIVE_COUNT = "active_count"
    SNOOZE_REGISTRY = "snooze_registry"

    # Debug/Detailed Attributes
    VIOLATION_REGISTRY = "violations_registry"  # Replaces failing_reg
    TRACKED_ENTITIES = "tracked_entities"
    VIOLATIONS_DEBUG = "active_violations_debug_info"
    WRITE_OPS = "write_operations"
    STATUS = "status"

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