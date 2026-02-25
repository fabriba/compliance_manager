"""Platform for sensor integration."""
from __future__ import annotations
from .example_sensor import ExampleSensor
from .const import (
    DOMAIN,
    SEVERITY_LEVELS,
    DEFAULT_SEVERITY,
    SNOOZE_ATTRIBUTE,
    GRACE_ATTRIBUTE,
    DEFAULT_ICON,
    DEFAULT_GRACE,
    TESTMODE
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
                    vol.Optional("attribute"): cv.string,
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

    entities = []
    # (Optional) Example sensors
    if TESTMODE:
        for n in range(10):
            entities.append(ExampleSensor(f"sample_component_{n}"))

    for s_conf in config.get("sensors", []):
        entities.append(ComplianceManagerSensor(s_conf))

    async_add_entities(entities)

    # REGISTER SERVICE AFTER ADDING ENTITIES
    async def handle_snooze(call):
        """Service to snooze specific violations."""
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

    async def async_snooze(self, entities: list[str], duration: timedelta) -> None:
        """Add entities to the snooze registry."""
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
        """Subscribe to events only when HA is ready."""
        await super().async_added_to_hass()

        # RESTORE STATE FROM REBOOT
        last_state = await self.async_get_last_state()
        if last_state:
            if SNOOZE_ATTRIBUTE in last_state.attributes:
                self._snooze_registry = dict(last_state.attributes[SNOOZE_ATTRIBUTE])
            if GRACE_ATTRIBUTE in last_state.attributes:
                restored_failing = last_state.attributes[GRACE_ATTRIBUTE]
                for eid, iso_time in restored_failing.items():
                    parsed_time = dt_util.parse_datetime(iso_time)
                    if parsed_time:
                        self._failing_since[eid] = parsed_time
        self._attr_is_on = (last_state.state == "on") if last_state else False

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
                    new_rule["target"] = {"entity_id": eid }
                    if "value_template" in new_rule:
                        # template precompilation, it helps performance
                        new_rule["value_template"].hass = self.hass


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

    async def _update_event_handler(self, _event):
        """Handle state change events by triggering a sensor update."""
        await self._evaluate_compliance()
        self.async_schedule_update_ha_state(True)

    async def _evaluate_compliance(self) -> None:
        """CORE LOGIC: evaluate rules to determine  if there is a compliance problem."""
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
            if self._is_noncompliant(rule, state_obj):
                noncompliant_rules.append(rule)

        for rule in noncompliant_rules:
            eid = rule["target"]["entity_id"]
            grace_delta = rule.get("grace_period", DEFAULT_GRACE)
            rule_sev_raw = rule.get("severity", DEFAULT_SEVERITY)

            first_fail_time = self._failing_since.setdefault(eid, dt_util.now())
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
                if eid not in self._timer_unsubs:
                    scheduled_time = first_fail_time + grace_delta
                    self._timer_unsubs[eid] = async_track_point_in_time(
                        self.hass,
                        self._update_event_handler,
                        scheduled_time
                    )


        all_violations_eids = [v["entity_id"] for v in active_violations]
        all_noncompliant_eids = [r["target"]["entity_id"] for r in noncompliant_rules]
        failing_since_iso = {k: v.isoformat() for k, v in self._failing_since.items()}
        for eid in list(self._failing_since.keys()): #this creates a copy, so the pop doesn't change dict size
            if eid not in all_noncompliant_eids:
                # if it's back to a compliant state, reset failing_since
                self._failing_since.pop(eid, None)
                unsub = self._timer_unsubs.pop(eid, None)
                if unsub:
                    unsub()

        self._attr_is_on = len(active_violations) > 0
        self._attr_extra_state_attributes = {
            "tracked_entities": self._tracked_entities,
            "tracked_count": len(self._tracked_entities),
            "active_violations_debug_info": active_violations,
            "active_violations": all_violations_eids,
            "raw_violation_entities": all_noncompliant_eids,
            "violations_count": len(active_violations),
            "status": "Non-Compliant" if self._attr_is_on else "Compliant",
            SNOOZE_ATTRIBUTE: self._snooze_registry,
            GRACE_ATTRIBUTE: failing_since_iso,
            "severity": max_severity["label"] if self._attr_is_on else None,
            "write_operations": self._write_count
        }

    def _is_noncompliant(self, rule: dict, state_obj: State | None) -> bool:
        """Valuta se una singola regola è in stato di non-compliance."""

        # 1. Se l'entità non esiste
        if state_obj is None:
            return True

        target_attr = rule.get("attribute")
        if target_attr:
            # if attribute exists, we use that instead of state
            if target_attr not in state_obj.attributes:
                return True
            val_to_check = state_obj.attributes[target_attr]
        else:
            val_to_check = state_obj.state

        # 2. Controllo stati speciali (unavailable/unknown)
        if val_to_check == "unavailable":
            return not rule.get("allow_unavailable", False)
        if val_to_check == "unknown":
            return not rule.get("allow_unknown", False)

        # 3. Valutazione basata sul tipo di regola
        # Ordine di priorità: template > numeric > state

        # A. Value Template
        if "value_template" in rule:
            try:
                # Rendering del template: deve restituire True se conforme
                res = rule["value_template"].async_render(
                    variables={"state": val_to_check, "entity": state_obj},
                    parse_result=True
                )
                return not res  # Se il template è False, è non-compliant
            except Exception:
                return True

        # B. Expected Numeric
        if "expected_numeric" in rule:
            try:
                val = float(val_to_check)
                limits = rule["expected_numeric"]
                if "min" in limits and val < limits["min"]:
                    return True
                if "max" in limits and val > limits["max"]:
                    return True
                return False
            except (ValueError, TypeError):
                return True

        # C. Expected State
        if "expected_state" in rule:
            expected = rule["expected_state"]
            if isinstance(expected, bool):
                # Mapping booleano per stati comuni HA
                actual_bool = str(val_to_check).lower() in ["on", "true", "home", "open", "connected", "1", "yes"]
                return actual_bool != expected

            return str(val_to_check).lower() != str(expected).lower()

        return False

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
