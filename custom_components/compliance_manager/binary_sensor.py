"""Platform for sensor integration."""
from __future__ import annotations

import logging
import datetime
from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change_event,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_GRACE,
    DEFAULT_ICON,
    DEFAULT_SEVERITY,
    DOMAIN,
    SEVERITY_LEVELS,
    ComplianceManagerAttributes as ATTRIBUTES,
)
from .schema import BS_PLATFORM_SCHEMA as PLATFORM_SCHEMA
from .timers import RegistryEntry

_LOGGER = logging.getLogger(__name__)
_ = PLATFORM_SCHEMA # this only avoids "unused import warnings

async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None
) -> None:
    """    Sets up the compliance_manager binary sensor platform.
    Initializes global domain data, instantiates ComplianceManagerSensor
    objects from the YAML configuration, and registers the 'snooze'
    service for managing active violations.
    """
    cmp_mgr_cfg = config

    entities = []
    # (Optional) Example sensors
    sensors = cmp_mgr_cfg.get("sensors", [])
    for s_conf in sensors:
        # ToDo: injectiing show_debug_attributes is inelegant, find a better way
        s_conf["show_debug_attributes"] = cmp_mgr_cfg.get("show_debug_attributes", False)
        entities.append(ComplianceManagerSensor(s_conf))


    async_add_entities(entities)

    # REGISTER SERVICE AFTER ADDING ENTITIES
    async def handle_snooze(call):
        """    Service handler for silencing specific compliance violations.
        It parses the targeted sensor and sub-entities from the service call
        data and applies a snooze duration to the matching sensor instances
        registered in the system.
        """
        # This service now finds entities currently registered in HA
        target_entities = call.data.get("entity_id", [])
        entities_to_snooze = call.data.get("entities", [])
        duration = call.data.get("duration")

        for entity in entities:
            # Check if this specific instance matches the targeted entity_id
            if entity.entity_id in target_entities:
                await entity.async_snooze(entities_to_snooze, duration)

    hass.services.async_register(
        DOMAIN,
        "snooze",
        handle_snooze,
        schema=vol.Schema({
            vol.Required("entity_id"): cv.entity_ids,
            vol.Optional("entities"): cv.ensure_list,
            vol.Required("duration"): cv.time_period,
        })
    )


###############  ComplianceManagerSensor ###############
class ComplianceManagerSensor(RestoreEntity, BinarySensorEntity):
    """Compliance monitoring sensor."""

    _attr_should_poll = False

    def __init__(self, s_conf: dict) -> None:
        """        Initializes a compliance sensor instance.
         Sets up the sensor name, unique ID, icon, and internal registries
         for rules, tracked entities, grace periods, and snooze status
         based on the provided configuration dictionary.
         """
        self._attr_name = s_conf.get("name")
        self._attr_unique_id = s_conf.get("unique_id") or f"compliance_{self._attr_name.lower().replace(' ', '_')}"
        self._attr_icon = s_conf.get("icon", DEFAULT_ICON)
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM
        self._rules = s_conf.get("rules", [])
        self._flattened_rules = [] #  performance-optimized version
        self._tracked_entities: set[str] = set()
        #Todo: remove all references  to self._snooze_registry:v1, _violations_registry_v1 and active_violations_v1
        #self._snooze_registry_v1: dict[str, str] = {} # {entity_id: expiry_iso_string}
        #self._violations_registry_v1: dict[str, str] = {} # {grace_target: first_fail_iso_string}
        #self._timer_unsubs: dict[str, callable] = {}
        self._snooze_registry_v2: dict[str, RegistryEntry] = {}
        self._violations_registry_v2: dict[str, RegistryEntry] = {}
        self._write_count = 0
        self._config = s_conf

    async def async_snooze(self, entities: list[str], duration: timedelta) -> None:
        """        Applies a snooze period to specific sub-entities.
        Calculates the expiry time and updates the snooze registry. If no
        entities are specified, it automatically snoozes all currently
        active violations for that sensor.
        """
        expiry = dt_util.now() + duration

        # If no entities provided, snooze all currently active violations
        if not entities:
            entities = self._attr_extra_state_attributes.get("active_violations", [])

        for eid in entities:
            self._snooze_registry_v2[eid] = self._create_timer(eid, expiry)


        await self._evaluate_compliance()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """        Called when the sensor is added to Home Assistant.
        Restores the previous state (snoozes and grace periods) from
        the database and initializes the entity tracking and monitoring
        logic once the system has fully started.
        """
        await super().async_added_to_hass()

        # RESTORE STATE FROM REBOOT
        last_state = await self.async_get_last_state()
        if last_state:
            if ATTRIBUTES.SNOOZE_REGISTRY in last_state.attributes:
                _s = last_state.attributes.get(ATTRIBUTES.SNOOZE_REGISTRY) or {}
                #self._snooze_registry_v1 = dict(saved_snoozes)
                # ToDo: _snooze_registry_v1 replaced by v2
                self._snooze_registry_v2 = {
                    eid: self._restore_timer(eid, iso_str)
                    for eid, iso_str in _s.items()
                }

            if ATTRIBUTES.VIOLATION_REGISTRY in last_state.attributes:
                _d = last_state.attributes.get(ATTRIBUTES.VIOLATION_REGISTRY) or {}
                # TODO: remove _violations_registry_v1
                #self._violations_registry_v1 = _d
                self._violations_registry_v2 = {
                    eid: self._restore_timer(eid, iso_str)
                    for eid, iso_str in _d.items()
                }

        self._attr_is_on = (last_state.state == "on") if last_state else False

        async def _setup_monitoring(_event=None):
            """        Initializes the monitoring engine for the sensor.
              Flattens complex target rules into individual entity tracking,
              sets up Jinga2 templates for conditions, and subscribes to
              state change events for all relevant entities.
              """
            #ent_reg = er.async_get(self.hass)

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
                    new_rule["target"] = {"entity_id": eid }
                    raw_cond = new_rule.get("condition")
                    if not isinstance(raw_cond, list):
                        new_rule["condition"] = [raw_cond]

                    for cond_item in new_rule["condition"]:
                        self._setup_condition_templates(cond_item)



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
            await self._evaluate_compliance()
            self.async_write_ha_state()

        if self.hass.is_running:
            await _setup_monitoring()
        else:
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _setup_monitoring)

    async def async_will_remove_from_hass(self) -> None:
        """        Performs cleanup before the sensor is removed.
        Explicitly cancels and clears all active grace period timers
        in Home Assistant to prevent background tasks from running
        on non-existent entities.
        """
        # Clinging on all active timers and unsubscribing them
        #for eid, unsub in self._timer_unsubs.items():
        #    if unsub:
        #        unsub()  # this physically stops the timer in HA

        #self._timer_unsubs.clear()

        # call the methos from the base class in the end
        await super().async_will_remove_from_hass()

    async def _update_event_handler(self, _event):
        """        Standard event handler for state changes.
        Triggered whenever a tracked entity changes its state, prompting
        a full re-evaluation of the compliance logic and a state
        update in the Home Assistant UI.
        """
        await self._evaluate_compliance()
        self.async_schedule_update_ha_state()

    async def _evaluate_compliance(self) -> None:
        """   CORE LOGIC engine for determining sensor state.
        Iterates through rules, checks for active snoozes, evaluates
        violations against grace periods, and updates the final
        binary state and attributes (severity, violation list).
        """
        noncompliant_rules = []
        # active_violations_v1 = []
        active_violations_v2 = []
        max_severity = {"level": 99, "label": "SeverityEvaluationFail"}
        self._write_count += 1

        for idx, rule in enumerate(self._flattened_rules):  # can be replaced with self._rules
            rule_target = rule["target"]["entity_id"]  # it's only one if using self._flattened_rules
            if "grace_target" not in rule:
                rule["grace_target"] = f"{self._attr_name}___rule_{idx}" if rule.get("group_grace") else rule_target

            state_obj = self.hass.states.get(rule_target)
            if self._check_rule_violation(rule, state_obj):
                noncompliant_rules.append(rule)

        all_grace_targets = set()
        for rule in noncompliant_rules:
            rule_target = rule["target"]["entity_id"]
            grace_delta = rule.get("grace_period", DEFAULT_GRACE)
            rule_sev_raw = rule.get("severity", DEFAULT_SEVERITY)
            grace_target = rule["grace_target"]

            all_grace_targets.add(grace_target)

            if grace_target not in self._violations_registry_v2:
                expiry = dt_util.now() + grace_delta
                self._violations_registry_v2[grace_target] = self._create_timer(grace_target, expiry)

            if timer_snooze := self._snooze_registry_v2.get(rule_target):
                if not timer_snooze.is_expired:
                    continue  # if we are here, snooze active >> skip violation evaluation

            timer_grace = self._violations_registry_v2[grace_target]
            if timer_grace.is_expired:
                current_sev = self._get_severity_data(rule_sev_raw)
                active_violations_v2.append({
                    'entity_id': rule_target,
                    'severity': current_sev['level'],
                    'severity_label': current_sev['label']
                })
                if current_sev["level"] < max_severity["level"]:
                    max_severity = current_sev

        active_violations_eids = [v["entity_id"] for v in active_violations_v2]

        for grace_target in list(self._violations_registry_v2.keys()):
            if grace_target not in all_grace_targets:
                # if we are here, grace expired >> pop will trigger RegistryEntry.__del__
                self._violations_registry_v2.pop(grace_target)
        for snooze_target in list(self._snooze_registry_v2.keys()):
            if self._snooze_registry_v2[snooze_target].is_expired:
                self._snooze_registry_v2.pop(snooze_target)

        grace_period_display = list({str(rule["grace_period"]) for rule in self._rules if "grace_period" in rule})
        self._attr_is_on = len(active_violations_v2) > 0
        attrs = {
            ATTRIBUTES.SEVERITY: max_severity["level"] if self._attr_is_on else "",
            ATTRIBUTES.SEVERITY_LABEL: max_severity["label"] if self._attr_is_on else "",
            ATTRIBUTES.GRACE_PERIODS: grace_period_display,
            ATTRIBUTES.ACTIVE_VIOLATIONS: active_violations_eids,
            ATTRIBUTES.ACTIVE_COUNT: len(active_violations_v2),
            ATTRIBUTES.SNOOZE_REGISTRY: {
                eid: entry.expiry_iso
                for eid, entry in self._snooze_registry_v2.items()
            },
        }
        if self._config.get("show_debug_attributes", False):
            attrs.update({
                # ATTRIBUTES.VIOLATION_REGISTRY: self._violations_registry_v1,
                ATTRIBUTES.VIOLATION_REGISTRY + "_v2": {
                    target: entry.expiry_iso
                    for target, entry in self._violations_registry_v2.items()
                },
                ATTRIBUTES.TRACKED_ENTITIES: self._tracked_entities,
                ATTRIBUTES.VIOLATIONS_DEBUG: active_violations_v2,
                ATTRIBUTES.STATUS: "Non-Compliant" if self._attr_is_on else "Compliant",
                ATTRIBUTES.WRITE_OPS: self._write_count
            })
        self._attr_extra_state_attributes = attrs

    def _setup_condition_templates(self, condition: Any) -> None:
        """        Recursively links the HA instance to condition templates.
        Ensures that any 'value_template' defined in the YAML rules
        has access to the Home Assistant object for proper rendering
        of logic during evaluation.
        """
        if isinstance(condition, list):
            for item in condition:
                self._setup_condition_templates(item)
        elif isinstance(condition, dict):
            if "value_template" in condition:
                condition["value_template"].hass = self.hass

            # Check for nested logic blocks
            for key in ["and", "or", "not"]:
                if key in condition:
                    self._setup_condition_templates(condition[key])

    def _check_rule_violation(self, rule: dict, state_obj: State | None) -> bool:
        """        Evaluates a single rule against an entity's state object.
        Handles special states like 'unavailable' and 'unknown' based
        on the rule configuration before passing the entity to the
        recursive logic evaluation block.
        """
        if state_obj is None:
            return True

        if state_obj.state == "unavailable":
            return not rule.get("allow_unavailable", False)
        if state_obj.state == "unknown":
            return not rule.get("allow_unknown", False)

        # We start the evaluation. Since rule["condition"] is a list,
        # it's an implicit AND.
        return self._evaluate_logic_block({"and": rule["condition"]}, state_obj)

    def _evaluate_logic_block(self, item: dict | list, state_obj: State) -> bool:
        """        Handles recursive logic operators (AND, OR, NOT).
        Orchestrates complex rule trees by evaluating nested logic
        blocks and calling atomic condition checks for individual
        state or attribute comparisons.
        """
        # Handle lists (implicit AND)
        if isinstance(item, list):
            return any(self._evaluate_logic_block(i, state_obj) for i in item)
        # Logic Operators
        if "and" in item:
            return any(self._evaluate_logic_block(i, state_obj) for i in item["and"])
        if "or" in item:
            return all(self._evaluate_logic_block(i, state_obj) for i in item["or"])
        if "not" in item:
            return not self._evaluate_logic_block(item["not"], state_obj)
        # If it's not a logic operator, it MUST be an atomic condition
        return self._check_condition_violation(item, state_obj)

    def _check_condition_violation(self, condition: dict, state_obj: State) -> bool:
        """        Performs an atomic evaluation of a specific condition.
        Compares the target state or attribute against expected
        numeric ranges, specific states, or rendered templates to
        return a boolean violation result.
        """

        # Resolve target value (Attribute vs State)
        target_attr = condition.get("attribute")
        val_to_check = state_obj.attributes.get(target_attr) if target_attr else state_obj.state

        # Handle case where attribute is missing
        if target_attr and target_attr not in state_obj.attributes:
            return True

        # A. Value Template
        if "value_template" in condition:
            try:
                res = condition["value_template"].async_render(
                    variables={"t_state": val_to_check,
                               "t_entity": state_obj,
                               "t_id": state_obj.entity_id },
                    parse_result=True
                )
                return not res
            except Exception:
                return True

        # B. Expected Numeric
        if "expected_numeric" in condition:
            try:
                val = float(val_to_check)
                limits = condition["expected_numeric"]
                if "min" in limits and val < limits["min"]:
                    return True
                if "max" in limits and val > limits["max"]:
                    return True
                return False
            except (ValueError, TypeError):
                return True

        # C. Expected State
        if "expected_state" in condition:
            expected = condition["expected_state"]
            if isinstance(expected, bool):
                actual_bool = str(val_to_check).lower() in ["on", "true", "home", "open", "connected", "1", "yes"]
                return actual_bool != expected
            return str(val_to_check).lower() != str(expected).lower()

        return False

    def _get_severity_data(self, sev_cfg):
        """        Helper to normalize severity configuration data.
         Converts raw severity strings or dictionaries into a standardized
         internal format containing both a numerical level and a
         human-readable label for reporting.
         """
        if isinstance(sev_cfg, str):
            return {"level": SEVERITY_LEVELS.get(sev_cfg, 1), "label": sev_cfg.capitalize()}
        return {"level": sev_cfg["level"], "label": sev_cfg.get("label", f"Level {sev_cfg['level']}")}

    def _get_entities_from_target(self, target) -> list[str]:
        """        Resolves HA targets into a list of entity IDs.
        Interprets configuration targets containing specific entity IDs,
        area IDs, or labels, and queries the registry to provide a
        comprehensive list of tracked entities.
        """
        ent_reg = er.async_get(self.hass)
        entities = set(cv.ensure_list(target.get("entity_id", [])))
        if area_ids := target.get("area_id"):
            for a_id in cv.ensure_list(area_ids):
                entities.update(e.entity_id for e in er.async_entries_for_area(ent_reg, a_id))
        if label_ids := target.get("label_id"):
            for l_id in cv.ensure_list(label_ids):
                entities.update(e.entity_id for e in er.async_entries_for_label(ent_reg, l_id))
        return list(entities)

    def _create_timer(self, eid: str, expiry: datetime) -> RegistryEntry:
        """Restores a timer from an expiry time in datetime format."""
        return RegistryEntry(
                eid,
                expiry,
                self.hass,
                self._update_event_handler )

    def _restore_timer(self, eid: str, iso_str: str) -> RegistryEntry:
        """Restores a timer from an an expiry time in iso  string
            (that was probably saved in attributes.)"""
        return RegistryEntry.create_from_iso(
            eid,
            iso_str,
            self.hass,
            self._update_event_handler )