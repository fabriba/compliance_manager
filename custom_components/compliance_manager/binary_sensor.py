"""Platform for sensor integration."""
from __future__ import annotations
import logging
from .const import (
    DOMAIN,
    SEVERITY_LEVELS,
    DEFAULT_SEVERITY,
    SNOOZE_ATTRIBUTE,
    GRACE_ATTRIBUTE,
    DEFAULT_ICON,
    DEFAULT_GRACE
)


from homeassistant.helpers import entity_registry as er
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from datetime import timedelta
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.event import async_track_state_change_event

from homeassistant.util import dt as dt_util

import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from .schema import BS_PLATFORM_SCHEMA as PLATFORM_SCHEMA
_ = PLATFORM_SCHEMA # this is just so it's not greyed out, and I am not tempted to delete the line
_LOGGER = logging.getLogger(__name__)

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
        entities.append(ComplianceManagerSensor(s_conf))
    _LOGGER.debug(f"PODDD [b_sensor] {sensors=}")

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
        self._failing_since: dict[str, dt_util.dt.datetime] = {}
        self._timer_unsubs: dict[str, callable] = {}
        self._snooze_registry: dict[str, str] = {} # {entity_id: expiry_iso_string}
        self._write_count = 0
        self._show_debug_attributes =  s_conf.get("show_debug_attributes", False)

    async def async_snooze(self, entities: list[str], duration: timedelta) -> None:
        """        Applies a snooze period to specific sub-entities.
        Calculates the expiry time and updates the snooze registry. If no
        entities are specified, it automatically snoozes all currently
        active violations for that sensor.
        """
        expiry = dt_util.now() + duration
        expiry_iso = expiry.isoformat()

        # If no entities provided, snooze all currently active violations
        if not entities:
            entities = self._attr_extra_state_attributes.get("active_violations", [])

        for eid in entities:
            self._snooze_registry[eid] = expiry_iso

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
            if SNOOZE_ATTRIBUTE in last_state.attributes:
                self._snooze_registry = dict(last_state.attributes[SNOOZE_ATTRIBUTE])
            if GRACE_ATTRIBUTE in last_state.attributes:
                restored_failing = last_state.attributes[GRACE_ATTRIBUTE]
                for grace_target, iso_time in restored_failing.items():
                    parsed_time = dt_util.parse_datetime(iso_time)
                    if parsed_time:
                        self._failing_since[grace_target] = parsed_time
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
            for idx, rule in enumerate(self._rules):
                # Resolve the target into a pure list of entity_ids
                actual_eids = self._get_entities_from_target(rule["target"])
                self._tracked_entities.update(actual_eids)
                if rule.get("group_grace") == True:
                    rule["grace_target"] = f"{self._attr_name}___rule_{idx}"
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
        for eid, unsub in self._timer_unsubs.items():
            if unsub:
                unsub()  # this physically stops the timer in HA

        self._timer_unsubs.clear()

        # call the methos from the base class in the end
        await super().async_will_remove_from_hass()

    async def _update_event_handler(self, _event):
        """        Standard event handler for state changes.
        Triggered whenever a tracked entity changes its state, prompting
        a full re-evaluation of the compliance logic and a state
        update in the Home Assistant UI.
        """
        await self._evaluate_compliance()
        self.async_schedule_update_ha_state(True)

    async def _evaluate_compliance(self) -> None:
        """   CORE LOGIC engine for determining sensor state.
        Iterates through rules, checks for active snoozes, evaluates
        violations against grace periods, and updates the final
        binary state and attributes (severity, violation list).
        """
        noncompliant_rules = []
        active_violations = []
        max_severity = {"level": 4, "label": "Info"}
        self._write_count += 1

        for rule in self._flattened_rules:      #can be replaced with self._rules
            eid = rule["target"]["entity_id"] #it's only one if using self._flattened_rules

            # --- SNOOZE CHECK ---
            if eid in self._snooze_registry:
                expiry = dt_util.parse_datetime(self._snooze_registry[eid])
                if expiry and expiry > dt_util.now():
                    continue  # Skip this entity, it is snoozed
                else:
                    self._snooze_registry.pop(eid)  # Lazy cleanup of expired snooze
            # --------------------

            state_obj = self.hass.states.get(eid)
            if self._check_rule_violation(rule, state_obj):
                noncompliant_rules.append(rule)

        active_tracking_keys = set()
        for rule in noncompliant_rules:
            eid = rule["target"]["entity_id"]
            grace_delta = rule.get("grace_period", DEFAULT_GRACE)
            rule_sev_raw = rule.get("severity", DEFAULT_SEVERITY)
            grace_target = rule.get("grace_target", eid)

            first_fail_time = self._failing_since.setdefault(grace_target, dt_util.now())
            active_tracking_keys.add(grace_target)
            time_since_fail = dt_util.now() - first_fail_time
            if time_since_fail > grace_delta:
                current_sev = self._get_severity_data(rule_sev_raw)
                active_violations.append({
                        'entity_id': eid,
                        'severity': current_sev['level'],
                        'severity_label': current_sev['label']
                    })
                if current_sev["level"] < max_severity["level"]:
                    max_severity = current_sev
            else:
                # WAITING FOR GRACE > plan a future update
                if grace_target not in self._timer_unsubs:
                    scheduled_time = first_fail_time + grace_delta
                    self._timer_unsubs[grace_target] = async_track_point_in_time(
                        self.hass,
                        self._update_event_handler,
                        scheduled_time
                    )


        active_violations_eids = [v["entity_id"] for v in active_violations]
        all_noncompliant_eids = [r["target"]["entity_id"] for r in noncompliant_rules]
        failing_since_iso = {k: v.isoformat() for k, v in self._failing_since.items()}
        for grace_target in list(self._failing_since.keys()): #this creates a copy, so the pop doesn't change dict size
            if grace_target not in active_tracking_keys:
                # if it's back to a compliant state, reset failing_since
                self._failing_since.pop(grace_target, None)
                unsub = self._timer_unsubs.pop(grace_target, None)
                if unsub:
                    unsub()

        self._attr_is_on = len(active_violations) > 0
        attrs = {
            "active_violations": active_violations_eids,
            "violations_count": len(active_violations),
            "status": "Non-Compliant" if self._attr_is_on else "Compliant",
            SNOOZE_ATTRIBUTE: self._snooze_registry,
            GRACE_ATTRIBUTE: failing_since_iso,
            "severity": max_severity["label"] if self._attr_is_on else None
        }
        if self._show_debug_attributes:
            attrs.update({
            "tracked_entities": self._tracked_entities,
            "tracked_count": len(self._tracked_entities),
            "active_violations_debug_info": active_violations,
            "all_noncompliant_entities": all_noncompliant_eids,
            "write_operations": self._write_count
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
                    variables={"state": val_to_check, "entity": state_obj},
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
