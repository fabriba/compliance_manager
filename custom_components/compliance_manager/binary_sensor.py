"""Platform for sensor integration."""
from __future__ import annotations

import logging
import datetime
import copy
from datetime import timedelta
from typing import Any


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
    async_track_state_change_event,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_ICON,
    DOMAIN,
    ComplianceManagerAttributes as ATTRIBUTES,
    RECURSIVE_KEYS
)
from .schema import BINSENS_PLATFORM_SCHEMA  as PLATFORM_SCHEMA
from .timers import RegistryEntry, ComplianceTimerMixin
from .engine import ComplianceLogicMixin
from .engine import get_atomic_key, get_logic_key

from pprint import pprint as pp

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
class ComplianceManagerSensor(RestoreEntity, BinarySensorEntity, ComplianceTimerMixin,ComplianceLogicMixin):
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
        self._config = s_conf
        self._optimized_compliance = []
        self._cattr_tracked_entities: set[str] = set() # custom attr
        self._cattr_snooze_registry: dict[str, RegistryEntry] = {}
        self._cattr_violations_registry: dict[str, RegistryEntry] = {}
        self._cattr_write_count = 0

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
                self._cattr_snooze_registry = {
                    eid: self._restore_timer(eid, iso_str)
                    for eid, iso_str in _s.items()
                }

            if ATTRIBUTES.VIOLATION_REGISTRY in last_state.attributes:
                _d = last_state.attributes.get(ATTRIBUTES.VIOLATION_REGISTRY) or {}
                self._cattr_violations_registry = {
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
            _LOGGER.debug("PODDD SETUP_START:  %s", self._attr_name)
            self._optimized_compliance = self._recursively_preprocess_rules( self._config.get("compliance_rules"))
            self._optimized_compliance = self._add_grace_targets_to_optimized_compliance

            _LOGGER.warning(f"PODDD DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD OPTIMIZATION COMPLETED: {self._attr_name=} ; {self._optimized_compliance=}")

            # 3. Standard event setup
            if self._cattr_tracked_entities:
                self.async_on_remove(
                    async_track_state_change_event(
                        self.hass,
                        list(self._cattr_tracked_entities),
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
            self._cattr_snooze_registry[eid] = self._create_timer(eid, expiry)


        await self._evaluate_compliance()
        self.async_write_ha_state()

    async def _update_event_handler(self, _event):
        """
        Generic event dispatcher for state changes and timer triggers.
        It processes incoming Home Assistant state change events for tracked
        entities and handles expiration callbacks from grace period timers.
        Updates the internal compliance logic and schedules a state write
        operation for the binary sensor.
        """

        # If _event is a Home Assistant Event object
        if hasattr(_event, "data"):
            entity_id = _event.data.get('entity_id')
            _LOGGER.debug("PODDD EVENT_RECEIVED: change of state for %s", entity_id)
        # If _event is a datetime (timer callback)
        elif isinstance(_event, datetime.datetime):
            _LOGGER.debug("PODDD TIMER_EXPIRED:  Grace Period ended")
        else:
            _LOGGER.debug("PODDD UPDATE_TRIGGERED: generic update triggered")

        await self._evaluate_compliance()
        self.async_schedule_update_ha_state()


    def _recursively_preprocess_rules(self, condition_list: list) -> list:
        """
        Recursively process and optimize the rule logic tree during initialization.

        This method performs three critical pre-computation tasks:
        1. Target Resolution: Converts high-level targets (area_id, label_id) into
           static lists of entity_ids once to avoid registry lookups during runtime.
        2. Configuration Inheritance: Propagates recursive keys (grace_period, severity,
           etc.) from parent rules down to nested logical conditions.
        3. Template Preparation: Injects the Home Assistant instance into Jinja2
           templates to ensure they are ready for immediate rendering.

        By running this during setup, the evaluation engine can perform at peak
        efficiency using pre-resolved data and cached configurations.
        """

        optimized_condition_list = []
        for idx, dict_condition in enumerate(condition_list):
            atomic_key = get_atomic_key(dict_condition)
            logic_key = get_logic_key(dict_condition)

            # a) can be a single rule with multiple eids
            # b) can be a list of  rules with multiple eids
            # c) can be a logic node with multiple eids

            if atomic_key:
                eids = self._get_entities_from_target(dict_condition["target"])
                for eidx, eid in enumerate(eids):
                    optimized_child_dict = dict_condition.copy()
                    optimized_child_dict["target"] = {"entity_id": eid}  # Forza l'ID singolo
                    optimized_child_dict.pop("group_grace") #doesn't make sense at single target leaf-levels
                    optimized_dict_condition["grace_target"] = eid
                    self._cattr_tracked_entities.add(eid)
                    if "value_template" in optimized_child_dict:
                        optimized_child_dict["value_template"].hass = self.hass
                    optimized_children_list.append(optimized_child_dict)
                # implicit "and" amongst targets to handle group_grace at leaf level
                optimized_dict_condition["and"] = optimized_children_list
                if "group_grace" in optimized_dict_condition:
                    _tmp_idx = optimized_dict_condition.get('idx', f"{idx}_{eidx}")
                    optimized_dict_condition["grace_target"] = f"{self._attr_name}___rule_{_tmp_idx}"
                optimized_condition_list.append(optimized_dict_condition)

            elif logic_key:
                _LOGGER.warning(f"PODDDD {dict_condition[logic_key]=}")
                for cidx, child in enumerate(dict_condition[logic_key]):
                    for recursive_key in RECURSIVE_KEYS:
                        if recursive_key not in child and recursive_key in dict_condition:
                            child[recursive_key] = dict_condition[recursive_key]
                            child["idx"] = f"{dict_condition.get("idx"),idx}_{cidx}"

                optimized_children_list = self._recursively_preprocess_rules(dict_condition[logic_key])
                optimized_dict_condition = dict_condition.copy()
                optimized_dict_condition[logic_key] = optimized_children_list
                optimized_condition_list.append(optimized_dict_condition)

        return optimized_condition_list

    def _get_entities_from_target(self, target: dict) -> list[str]:
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

    def _safe_deepcopy_rule(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: self._safe_deepcopy_rule(v) for k, v in obj.items() if k != "hass"}
        elif isinstance(obj, list):
            return [self._safe_deepcopy_rule(i) for i in obj]
        return copy.copy(obj)