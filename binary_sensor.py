"""Platform for sensor integration."""
from __future__ import annotations
import random
from homeassistant.helpers import entity_registry as er
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from datetime import timedelta
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.event import async_track_state_change_event

from homeassistant.util import dt as dt_util

import homeassistant.helpers.config_validation as cv
import voluptuous as vol

# Integration Domain
DOMAIN = "compliance_manager"  # Change this to your actual folder name
SEVERITY_LEVELS = {
    "critical": 0,
    "problem": 1,
    "warning": 2,
    "unusual": 3,
    "info": 4,
}
DEFAULT_SEVERITY = "problem"
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
                    vol.Optional("expected_state"): vol.Any(cv.string, vol.Coerce(float), bool),
                    vol.Optional("expected_numeric"): vol.All(
                        vol.Schema({
                            vol.Optional("min"): vol.Coerce(float),
                            vol.Optional("max"): vol.Coerce(float),
                        }), cv.has_at_least_one_key("min", "max")
                    ),
                    vol.Optional("value_template"): cv.template,
                    vol.Optional("grace_period", default=timedelta(seconds=0)): cv.time_period,
                    vol.Optional("severity", default=DEFAULT_SEVERITY): vol.Any(
                        vol.All(cv.string, vol.Lower, vol.In(SEVERITY_LEVELS.keys())),  # Accepts strings like "critical" or numberd
                        vol.All(
                            vol.Schema({
                                vol.Required("level"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
                                vol.Optional("label"): cv.string,
                            })
                        )
                    ),
                    vol.Optional("allow_unavailable", default=False): cv.boolean,
                    vol.Optional("allow_unknown", default=False): cv.boolean,
                }, vol.All(
                    cv.has_at_least_one_key("expected_state", "expected_numeric", "value_template"),
                    cv.has_at_most_one_key("expected_state", "expected_numeric", "value_template")
                )
            )]
        ),
    }]),
})



async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None
) -> None:
    """Set up the sensor platform."""

    entities: list[BinarySensorEntity] = [
        ExampleSensor(f"sample_component_{n}") for n in range(10)
    ]

    for s_conf in config.get("sensors", []):
        entities.append(ComplianceManagerSensor(s_conf))

    # Add entities using the provided callback
    async_add_entities(entities)

######### ExampleSensor #############
class ExampleSensor(BinarySensorEntity):
    """Sensor that changes state exactly every 3-6 seconds."""

    _attr_should_poll = False  # Manual timing control

    def __init__(self, name: str) -> None:
        self._attr_name = name
        self._attr_unique_id = f"sample_compliance_{self._attr_name.lower().replace(' ', '_')}"
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        """Start the cycle as soon as the sensor is ready."""
        self._schedule_next_toggle()

    def _schedule_next_toggle(self) -> None:
        """Schedule the next state change between 3 and 6 seconds."""
        wait_time = random.randint(3, 6)
        next_run = dt_util.now() + timedelta(seconds=wait_time)

        # Request HA for a wake-up call in the future
        async_track_point_in_time(self.hass, self._async_handle_toggle, next_run)

    async def _async_handle_toggle(self, _now) -> None:
        """Execute the toggle and reschedule."""
        rand = random.random()

        if rand < 0.0833:
            # 8.33% probability: State ON
            self._attr_is_on = True
            self._attr_available = True
        elif rand < 0.1666:
            # 8.33% probability: State UNAVAILABLE
            self._attr_is_on = False  # Irrelevant if unavailable
            self._attr_available = False
        elif rand < 0.25:
            # 8.33% probability: State UNKNOWN
            self._attr_is_on = None  # Represents 'unknown' for a binary_sensor
            self._attr_available = True
        else:
            # 75% probability: State OK (OFF)
            self._attr_is_on = False
            self._attr_available = True

        self.async_write_ha_state()  # Notify the UI and ComplianceManager of the change
        self._schedule_next_toggle()  # Restart the cycle

###############  ComplianceManagerSensor ###############
class ComplianceManagerSensor(BinarySensorEntity):
    """Compliance monitoring sensor."""

    _attr_should_poll = False

    def __init__(self, s_conf: dict) -> None:
        self._attr_name = s_conf.get("name")
        self._attr_unique_id = s_conf.get("unique_id") or f"compliance_{self._attr_name.lower().replace(' ', '_')}"
        self._attr_icon = s_conf.get("icon")
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM
        self._rules = s_conf.get("rules", [])
        self._flattened_rules = [] #  performance-optimized version
        self._tracked_entities: set[str] = set()
        self._failing_since: dict[str, dt_util.dt.datetime] = {}

    async def async_added_to_hass(self) -> None:
        """Subscribe to events only when HA is ready."""

        async def _setup_monitoring(_event=None):
            ent_reg = er.async_get(self.hass)

            # 1. Flatten the rules once at startup
            resolved_rules = []
            for rule in self._rules:
                # Resolve the target into a pure list of entity_ids
                actual_eids = self._get_entities_from_target(rule["target"])
                self._tracked_entities.update(actual_eids)
                for eid in actual_eids:
                    # Create a copy so we don't mess with the original config object
                    new_rule = rule.copy()
                    # REWRITE the target to be pure entity_ids only:
                    # list for analogy with self._rules, but it's a 1-items' list
                    new_rule["target"] = {"entity_id": [eid]}

                    resolved_rules.append(new_rule)

            # 2. Overwrite self._rules with the "flattened" version
            self._flattened_rules = resolved_rules

            # 3. Standard event setup
            if self._tracked_entities:
                self.async_on_remove(
                    async_track_state_change_event(
                        self.hass,
                        list(self._tracked_entities),
                        self._update_event_handler
                    )
                )
            self.async_schedule_update_ha_state(True)

        if self.hass.is_running:
            await _setup_monitoring()
        else:
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _setup_monitoring)

    async def _update_event_handler(self, _event):
        """Handle state change events by triggering a sensor update."""
        self.async_schedule_update_ha_state(True)

    async def async_update(self) -> None:
        """CORE LOGIC: evaluate rules to determine  if there is a compliance problem."""
        noncompliant_entities = []
        active_violations = []
        max_severity = {"level": 4, "label": "Info"}

        for rule in self._flattened_rules:      #can be replaced with self._rules
            target_entities = rule["target"]["entity_id"]
            #target_entities = self._get_entities_from_target(rule["target"]) # use this if looping on self._rules
            grace_delta = rule.get("grace_period", timedelta(0))
            rule_sev_cfg = rule.get("severity", DEFAULT_SEVERITY)

            for eid in target_entities:
                state_obj = self.hass.states.get(eid)


                # If the entity does not exist at all
                if state_obj is None:
                    noncompliant_entities.append(eid)
                    continue

                state_val = state_obj.state

                # Check special states
                # 1. Check stati speciali (Allowed -> Reset e salta)
                if state_val == "unavailable" and rule.get("allow_unavailable"):
                    continue
                if state_val == "unknown" and rule.get("allow_unknown"):
                    continue
                if state_val in ["unavailable", "unknown"]:
                    noncompliant_entities.append(eid)
                    continue

                # 1. Value Template
                if "value_template" in rule:
                    template = rule["value_template"]
                    # Pass both 'state' (string) and 'state_obj' (full object)
                    res = template.async_render(variables={"state": state_val, "entity": state_obj}, parse_result=True)
                    if not res:
                        noncompliant_entities.append(eid)
                        continue

                # 2. Expected Numeric
                elif "expected_numeric" in rule:
                    try:
                        val = float(state_val)
                        limits = rule["expected_numeric"]
                        if "min" in limits and val < limits["min"]:
                            noncompliant_entities.append(eid)
                            continue
                        if "max" in limits and val > limits["max"]:
                            noncompliant_entities.append(eid)
                            continue
                    except (ValueError, TypeError):
                        noncompliant_entities.append(eid)
                        continue

                # 3. Expected State
                elif "expected_state" in rule:
                    expected = rule["expected_state"]
                    if isinstance(expected, bool):
                        actual_bool = state_val.lower() in ["on", "true", "home", "open"]
                        if actual_bool != expected:
                            noncompliant_entities.append(eid)
                            continue
                    else:
                        if str(state_val).lower() != str(expected).lower():
                            noncompliant_entities.append(eid)
                            continue

        for eid in noncompliant_entities:
            first_fail_time = self._failing_since.setdefault(eid, dt_util.now())
            if (dt_util.now() - first_fail_time) > grace_delta:
                active_violations.append(eid)

                current_sev = self._get_severity_data(rule_sev_cfg)
                if current_sev["level"] < max_severity["level"]:
                    max_severity = current_sev

        for eid in list(self._failing_since.keys()): #this creates a copy, so the pop doesn't change dict size
            if eid not in noncompliant_entities:
                # if it's back to a compliant state, reset failing_since
                self._failing_since.pop(eid, None)

        self._attr_is_on = len(noncompliant_entities) > 0
        self._attr_extra_state_attributes = {
            "tracked_count": len(self._tracked_entities),
            "status": "Non-Compliant" if self._attr_is_on else "Compliant",
            "problems": active_violations,
            "problem_count": len(active_violations),
            "severity": max_severity["label"] if self._attr_is_on else None
        }

    def _get_severity_data(self, sev_cfg):
        """Helper to parse severity config."""
        if isinstance(sev_cfg, str):
            return {"level": SEVERITY_LEVELS.get(sev_cfg, 1), "label": sev_cfg.capitalize()}
        return {"level": sev_cfg["level"], "label": sev_cfg.get("label", f"Level {sev_cfg['level']}")}

    def _get_entities_from_target(self, target) -> list[str]:
        """Helper to filter entities for the current target (resolved in async_added)."""
        ent_reg = er.async_get(self.hass)
        entities = set(cv.ensure_list(target.get("entity_id", [])))
        if area_ids := target.get("area_id"):
            for a_id in cv.ensure_list(area_ids):
                entities.update(e.entity_id for e in er.async_entries_for_area(ent_reg, a_id))
        if label_ids := target.get("label_id"):
            for l_id in cv.ensure_list(label_ids):
                entities.update(e.entity_id for e in er.async_entries_for_label(ent_reg, l_id))
        return list(entities)
