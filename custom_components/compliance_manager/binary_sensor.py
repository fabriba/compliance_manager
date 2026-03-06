"""Platform for sensor integration."""
from __future__ import annotations

import logging
import datetime
from datetime import timedelta
from typing import Any

from homeassistant.helpers.entity_registry import EVENT_ENTITY_REGISTRY_UPDATED
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_GRACE,
    DEFAULT_ICON,
    DEFAULT_SEVERITY,
    DOMAIN,
    SEVERITY_LEVELS,
    CONDITION_KEYS,
    ON_EQUIVALENT_STATES,
    ComplianceManagerAttributes as ATTRIBUTES,
)
from .schema import BINSENS_PLATFORM_SCHEMA as PLATFORM_SCHEMA
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

    # pass the necessary info to services (snooze in particular, in services.py)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["binary_sensor_instances"] = entities

    async_add_entities(entities)


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
        self._rules = s_conf.get("compliance", [])
        self._optimized_rules = [] #  performance-optimized version
        self._tracked_entities: set[str] = set()
        self._snooze_registry: dict[str, RegistryEntry] = {}
        self._violations_registry: dict[str, RegistryEntry] = {}
        self._write_count = 0
        self._config = s_conf
        self._unsub_states = None

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
            self._snooze_registry[eid] = self._create_timer(eid, expiry)


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
                self._snooze_registry = {
                    eid: self._restore_timer(eid, iso_str)
                    for eid, iso_str in _s.items()
                }

            if ATTRIBUTES.VIOLATION_REGISTRY in last_state.attributes:
                _d = last_state.attributes.get(ATTRIBUTES.VIOLATION_REGISTRY) or {}
                self._violations_registry = {
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
            # cleanup before re-calculating
            if self._unsub_states:
                self._unsub_states()
            self._tracked_entities.clear()
            # 1. Flatten the rules once at startup
            resolved_rules = []

            _LOGGER.debug(f" {len(self._rules)} {self._rules=}")
            for idx, rule in enumerate(self._rules):
                # Resolve the target into a pure list of entity_ids
                actual_eids = self._get_entities_from_target(rule["target"])
                self._tracked_entities.update(actual_eids)

                # Create a copy so we don't mess with the original config object
                new_rule = rule.copy()
                new_rule["_idx"] = idx
                # REWRITE the target to be pure entity_ids only:
                new_rule["target"] = {"entity_id": actual_eids }
                condition_key = _get_condition_key(new_rule)
                raw_cond =  new_rule[condition_key]
                if condition_key == "value_template":
                    self.cache_value_templates(raw_cond)

                resolved_rules.append(new_rule)

            # 2. Overwrite self._rules with the "flattened" version
            self._optimized_rules = resolved_rules

            # 3. Standard event setup
            if self._tracked_entities:
                self._unsub_states = async_track_state_change_event(
                    self.hass,
                    list(self._tracked_entities),
                    self._update_event_handler
                )
                # This ensures clean removal if the sensor itself is deleted
                self.async_on_remove(self._unsub_states)
            await self._evaluate_compliance()
            self.async_write_ha_state()

        self.async_on_remove(
            self.hass.bus.async_listen(
                EVENT_ENTITY_REGISTRY_UPDATED,
                _setup_monitoring
            )
        )

        if self.hass.is_running:
            await _setup_monitoring()
        else:
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _setup_monitoring)

    async def async_will_remove_from_hass(self) -> None:
        """        Performs cleanup before the sensor is removed. """
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
        mark_problem = False
        ignored_violations_count = 0
        active_violations = []
        max_severity = {"level": 9, "label": "SeverityEvaluationFail"}
        self._write_count += 1

        all_grace_targets = set()

        _LOGGER.debug(f"{self._optimized_rules=}")
        for rule in self._optimized_rules:  # can be replaced with self._rules
            local_violations = 0
            allowed_violations_count = rule.get("allowed_violations_count", 0)
            if allowed_violations_count < 0:
                allowed_violations_count = len(rule["target"]["entity_id"]) + allowed_violations_count
                allowed_violations_count = max(0, allowed_violations_count)
            for rule_target in rule["target"]["entity_id"]:
                if self._is_condition_compliant(rule, rule_target):
                    continue


                _LOGGER.debug(
                    " Violation detected: %s | Rule: %s | GroupGrace: %s",
                    rule_target, rule.get('_idx'), rule.get('group_grace'))

                grace_delta = rule.get("grace_period", DEFAULT_GRACE)
                rule_sev_raw = rule.get("severity", DEFAULT_SEVERITY)
                grace_target = f"{self._attr_name}___rule_{rule['_idx']}" if rule.get("group_grace") else rule_target

                all_grace_targets.add(grace_target)

                if grace_target not in self._violations_registry:
                    expiry = dt_util.now() + grace_delta
                    _LOGGER.debug("Starting NEW grace period for %s. Expires at %s", grace_target, expiry)
                    self._violations_registry[grace_target] = self._create_timer(grace_target, expiry)

                if timer_snooze := self._snooze_registry.get(rule_target):
                    if not timer_snooze.is_expired:
                        _LOGGER.debug("Snooze active for %s, skipping", rule_target)
                        continue  # if we are here, snooze active >> skip violation evaluation

                timer_grace = self._violations_registry[grace_target]
                if timer_grace.is_expired:
                    _LOGGER.debug("Grace EXPIRED for %s. Adding to active violations.", grace_target)
                    current_sev = self._get_severity_data(rule_sev_raw)
                    active_violations.append({
                        'entity_id': rule_target,
                        'severity': current_sev['level'],
                        'severity_label': current_sev['label']
                    })
                    local_violations += 1
                    if current_sev["level"] < max_severity["level"]:
                        max_severity = current_sev
                    _LOGGER.debug(f"{rule_target=}, {local_violations=}, {ignored_violations_count=}, {rule.get("allowed_violations_count", 0)=}")

                    if local_violations > allowed_violations_count:
                        mark_problem = True
                        ignored_violations_count = 0
            if not mark_problem and local_violations <= allowed_violations_count:
                ignored_violations_count += local_violations

        active_violations_eids = [v["entity_id"] for v in active_violations]

        for grace_target in list(self._violations_registry.keys()):
            if grace_target not in all_grace_targets:
                # if we are here, grace expired >> pop will trigger RegistryEntry.__del__
                self._violations_registry.pop(grace_target)
        for snooze_target in list(self._snooze_registry.keys()):
            if self._snooze_registry[snooze_target].is_expired:
                self._snooze_registry.pop(snooze_target)

        grace_period_display = list({str(rule["grace_period"]) for rule in self._rules if "grace_period" in rule})
        self._attr_is_on = mark_problem
        attrs = {
            ATTRIBUTES.SEVERITY: max_severity["level"] if self._attr_is_on else "",
            ATTRIBUTES.SEVERITY_LABEL: max_severity["label"] if self._attr_is_on else "",
            ATTRIBUTES.GRACE_PERIODS: grace_period_display,
            ATTRIBUTES.ACTIVE_VIOLATIONS: active_violations_eids,
            ATTRIBUTES.ACTIVE_COUNT: len(active_violations),
            ATTRIBUTES.ALLOWED_VIOLATIONS: ignored_violations_count,
            ATTRIBUTES.SNOOZE_REGISTRY: {
                eid: entry.expiry_iso
                for eid, entry in self._snooze_registry.items()
            },
        }
        if self._config.get("show_debug_attributes", False):
            attrs.update({
                ATTRIBUTES.VIOLATION_REGISTRY: {
                    target: entry.expiry_iso
                    for target, entry in self._violations_registry.items()
                },
                ATTRIBUTES.TRACKED_ENTITIES: self._tracked_entities,
                ATTRIBUTES.VIOLATIONS_DEBUG: active_violations,
                ATTRIBUTES.STATUS: "Non-Compliant" if self._attr_is_on else "Compliant",
                ATTRIBUTES.WRITE_OPS: self._write_count
            })
        self._attr_extra_state_attributes = attrs

    def cache_value_templates(self, condition: Any) -> None:
        """    cache this so the value_template actually works
                and you don't have to requery it every time
        """
        condition.hass = self.hass


    def _is_condition_compliant(self, condition: dict, rule_target: str) -> bool:
        """     Handles recursive logic (implicit AND for multiple entities or rules))
             Performs an atomic evaluation of a specific condition.
        Compares the target state or attribute against expected
        numeric ranges, specific states, or rendered templates to
        return a boolean violation result.
        """
        # Handle lists (implicit AND)
        if isinstance(condition, list):
            _LOGGER.error("PODDD this is a list {condition=}")
            return False

        state_obj = self.hass.states.get(rule_target)
        if state_obj is None:
            return False

        if state_obj.state == "unavailable":
            return  condition.get("allow_unavailable", False)
        if state_obj.state == "unknown":
            return  condition.get("allow_unknown", False)

        # Resolve target value (Attribute vs State)
        target_attr = condition.get("attribute")
        val_to_check = state_obj.attributes.get(target_attr) if target_attr else state_obj.state

        # Handle case where attribute is missing
        if target_attr and target_attr not in state_obj.attributes:
            return False

        # A. Value Template
        if "value_template" in condition:
            try:
                res = condition["value_template"].async_render(
                    variables={"t_state": val_to_check,
                               "t_entity": state_obj,
                               "t_id": state_obj.entity_id },
                    parse_result=True
                )
                return  res
            except Exception:
                return False

        # B. Expected Numeric
        if "expected_numeric" in condition:
            try:
                val = float(val_to_check)
                limits = condition["expected_numeric"]
                if "min" in limits and val < limits["min"]:
                    return False
                if "max" in limits and val > limits["max"]:
                    return False
                return True
            except (ValueError, TypeError):
                return False

        # C. Expected State
        if "expected_state" in condition:
            expected = condition["expected_state"]
            if isinstance(expected, bool):
                actual_bool = str(val_to_check).lower() in ON_EQUIVALENT_STATES
                return actual_bool == expected
            return str(val_to_check).lower() == str(expected).lower()

        return True

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


def _get_condition_key(rule: dict) -> str | None:
    """Returns the atomic key if it's an atomic rule, else  None."""
    for key in CONDITION_KEYS:
        if key in rule:
            return key
    return None

def _get_condition(rule: dict) -> str | None:
    """Returns the atomic key if it's an atomic rule, else  None."""
    for key in CONDITION_KEYS:
        if key in rule:
            return rule[key]
    return None