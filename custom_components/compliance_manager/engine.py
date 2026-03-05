# engine.py
from __future__ import annotations
import copy
import logging
from typing import Any
from homeassistant.core import State
from .const import SEVERITY_LEVELS, ON_EQUIVALENT_STATES

from .const import (
    DEFAULT_GRACE,
    DEFAULT_SEVERITY,
    ComplianceManagerAttributes as ATTRIBUTES,
)
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

class ComplianceLogicMixin:
    """CORE LOGIC for evaluating compliance rules."""

    async def _evaluate_compliance(self) -> None:
        """   CORE LOGIC engine for determining sensor state.
        Iterates through rules, checks for active snoozes, evaluates
        violations against grace periods, and updates the final
        binary state and attributes (severity, violation list).
        """
        noncompliant_rules = []
        active_violations = []
        max_severity = {"level": 99, "label": "SeverityEvaluationFail"}
        self._cattr_write_count += 1

        _LOGGER.debug(
            "PODDD EVAL: Starting cycle %s. Flattened rules count: %s",
            self._cattr_write_count,
            len(self._optimized_compliance)
        )

        for idx, rule in enumerate(self._optimized_compliance):
            rule_target = rule["target"]["entity_id"]  # only one entity per rule in _optimized_compliance
            if "grace_target" not in rule:
                rule["grace_target"] = f"{self._attr_name}___rule_{idx}" if rule.get("group_grace") else rule_target

            state_obj = self.hass.states.get(rule_target)
            _LOGGER.debug(
                "PODDD CHECKING: Entity %s. State: %s. Rule Result: %s",
                rule_target,
                state_obj.state if state_obj else "None",
                "COMPLIANT" if self._is_rule_compliant(rule, state_obj) else "VIOLATION"
            )
            if not self._is_rule_compliant(rule, state_obj):
                noncompliant_rules.append(rule)

        all_grace_targets = set()
        for rule in noncompliant_rules:
            rule_target = rule["target"]["entity_id"]
            grace_delta = rule.get("grace_period", DEFAULT_GRACE)
            rule_sev_raw = rule.get("severity", DEFAULT_SEVERITY)
            grace_target = rule["grace_target"]

            all_grace_targets.add(grace_target)

            if grace_target not in self._cattr_violations_registry:
                expiry = dt_util.now() + grace_delta
                self._cattr_violations_registry[grace_target] = self._create_timer(grace_target, expiry)

            if timer_snooze := self._cattr_snooze_registry.get(rule_target):
                if not timer_snooze.is_expired:
                    continue  # if we are here, snooze active >> skip violation evaluation

            timer_grace = self._cattr_violations_registry[grace_target]
            if timer_grace.is_expired:
                current_sev = self._get_severity_data(rule_sev_raw)
                active_violations.append({
                    'entity_id': rule_target,
                    'severity': current_sev['level'],
                    'severity_label': current_sev['label']
                })
                if current_sev["level"] < max_severity["level"]:
                    max_severity = current_sev

        active_violations_eids = [v["entity_id"] for v in active_violations]

        for grace_target in list(self._cattr_violations_registry.keys()):
            if grace_target not in all_grace_targets:
                # if we are here, grace expired >> pop will trigger RegistryEntry.__del__
                self._cattr_violations_registry.pop(grace_target)
        for snooze_target in list(self._cattr_snooze_registry.keys()):
            if self._cattr_snooze_registry[snooze_target].is_expired:
                self._cattr_snooze_registry.pop(snooze_target)

        grace_period_display = list({str(rule["grace_period"]) for rule in self._config.get("compliance", []) if "grace_period" in rule})
        self._attr_is_on = len(active_violations) > 0
        attrs = {
            ATTRIBUTES.SEVERITY: max_severity["level"] if self._attr_is_on else "",
            ATTRIBUTES.SEVERITY_LABEL: max_severity["label"] if self._attr_is_on else "",
            ATTRIBUTES.GRACE_PERIODS: grace_period_display,
            ATTRIBUTES.ACTIVE_VIOLATIONS: active_violations_eids,
            ATTRIBUTES.ACTIVE_COUNT: len(active_violations),
            ATTRIBUTES.SNOOZE_REGISTRY: { eid: v.expiry_iso for eid, v in self._cattr_snooze_registry.items() },
        }
        if self._config.get("show_debug_attributes", False):
            attrs.update({
                ATTRIBUTES.VIOLATION_REGISTRY: { target: v.expiry_iso for target, v in self._cattr_violations_registry.items() },
                ATTRIBUTES.TRACKED_ENTITIES: self._cattr_tracked_entities,
                ATTRIBUTES.VIOLATIONS_DEBUG: active_violations,
                ATTRIBUTES.STATUS: "Non-Compliant" if self._attr_is_on else "Compliant",
                ATTRIBUTES.WRITE_OPS: self._cattr_write_count
            })
        self._attr_extra_state_attributes = attrs

    def _is_rule_compliant(self, rule: dict, state_obj: State | None) -> bool:
        """
        Evaluate a high-level rule against a given Home Assistant state object.
        This method acts as the entry point for compliance checking, handling
        edge cases such as 'unavailable' or 'unknown' entity states based on
        the rule configuration. If the state is valid, it delegates complex
        logic parsing to the meta-condition evaluator.
        """
        if state_obj is None:
            return False
        if state_obj.state == "unavailable":
            return rule.get("allow_unavailable", False)
        if state_obj.state == "unknown":
            return rule.get("allow_unknown", False)
        return self._is_metacondition_compliant(rule["condition"], state_obj)

    def _is_metacondition_compliant(self, item: dict | list, state_obj: State) -> bool:
        """
        Recursively process logical operators within a compliance rule.
        It handles complex nested structures including 'and', 'or', and 'not'
        metaconditions. Lists are treated as implicit 'and' groups. The method
        traverses the rule tree until it reaches atomic conditions, ensuring
        that logical hierarchies are respected during evaluation.
        """
        if isinstance(item, list):
            return all(self._is_metacondition_compliant(i, state_obj) for i in item)
        if "and" in item:
            return all(self._is_metacondition_compliant(i, state_obj) for i in item["and"])
        if "or" in item:
            return any(self._is_metacondition_compliant(i, state_obj) for i in item["or"])
        if "not" in item:
            not_clause = item["not"]
            return not self._is_metacondition_compliant(not_clause, state_obj)
        return self._is_condition_compliant(item, state_obj)

    def _is_condition_compliant(self, condition: dict, state_obj: State) -> bool:
        """        Performs an atomic evaluation of a specific condition.
        Compares the target state or attribute against expected
        numeric ranges, specific states, or rendered templates to
        return a boolean violation result.
        """
        _LOGGER.debug(
            "PODDD CONDITION: Testing %s against condition (Expected: %s)",
            state_obj.entity_id,
            condition.get("expected_state")
        )
        if "target" in condition:
            target_eids = condition["target"].get("entity_id", [])
            # If the current entity is not in the condition's target,
            # this condition cannot make it compliant.
            if target_eids and state_obj.entity_id not in target_eids:
                return False

        # 1. Determine which state object to use
        actual_state = state_obj

        # If this specific condition has a target (pushed down or local)
        # that doesn't match the current state_obj, fetch the correct one.
        if "target" in condition:
            target_eids = condition["target"].get("entity_id", [])
            if target_eids and state_obj.entity_id not in target_eids:
                # Take the first entity from the resolved target list
                new_state = self.hass.states.get(target_eids[0])
                if not new_state:
                    return False  # Entity doesn't exist
                actual_state = new_state

        # 2. Proceed with evaluation using actual_state
        target_attr = condition.get("attribute")
        val_to_check = actual_state.attributes.get(target_attr) if target_attr else actual_state.state

        if target_attr and target_attr not in actual_state.attributes:
            return False

        # A. Value Template
        if "value_template" in condition:
            try:
                return condition["value_template"].async_render(
                    variables={
                        "t_state": val_to_check,
                        "t_entity": actual_state,
                        "t_id": actual_state.entity_id
                    },
                    parse_result=True
                )
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
        if isinstance(sev_cfg, str):
            return {"level": SEVERITY_LEVELS.get(sev_cfg, 1), "label": sev_cfg.capitalize()}
        return {"level": sev_cfg["level"], "label": sev_cfg.get("label", f"Level {sev_cfg['level']}")}
