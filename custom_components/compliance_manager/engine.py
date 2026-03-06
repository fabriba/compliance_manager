# engine.py
from __future__ import annotations
import logging
from homeassistant.core import State
from .const import SEVERITY_LEVELS, ON_EQUIVALENT_STATES
from datetime import timedelta

from .const import (
    DEFAULT_GRACE,
    DEFAULT_SEVERITY,
    ComplianceManagerAttributes as ATTRIBUTES,
    LOGIC_KEYS,
    ATOMIC_KEYS
)
from homeassistant.util import dt as dt_util
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

_LOGGER = logging.getLogger(__name__)

@dataclass
class ComplianceResult:
    """Object representing the evaluation of a logic node."""
    # --- LOGICAL STATES ---
    is_compliant: bool = True  # Physical/Raw state
    is_graced: bool = False  # Under grace period
    is_snoozed: bool = False  # Under active snooze

    @property
    def is_active_violation(self) -> bool:
        """Confirmed violation: non-compliant, grace expired, no snooze."""
        return not self.is_compliant and not self.is_graced and not self.is_snoozed

    # --- TIMERS ---
    next_grace_expiry: Optional[datetime] = None
    next_snooze_expiry: Optional[datetime] = None

    # --- ATTRIBUTES ---
    active_violations: List[str] = field(default_factory=list)
    pending_violations: List[str] = field(default_factory=list)
    tracked_entities: List[str] = field(default_factory=list)
    severity: str = 10
    severity_label: str = ""

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

        for condition in self._optimized_compliance:
            compliance_results = self._is_logic_condition_compliant(condition)
            if compliance_results.is_compliant:
                noncompliant_rules.append(condition)

        for grace_target in list(self._cattr_violations_registry.keys()):
            if grace_target not in compliance_results.pending_violations:
                # if we are here, grace expired >> pop will trigger RegistryEntry.__del__
                self._cattr_violations_registry.pop(grace_target)
        for snooze_target in list(self._cattr_snooze_registry.keys()):
            if self._cattr_snooze_registry[snooze_target].is_expired:
                self._cattr_snooze_registry.pop(snooze_target)

        # TODO: review this last bit and test
        grace_period_display = list({str(rule["grace_period"]) for rule in self._config.get("compliance_rules", []) if "grace_period" in rule})
        self._attr_is_on = len(active_violations) > 0
        attrs = {
            ATTRIBUTES.SEVERITY: max_severity["level"] if self._attr_is_on else "",
            ATTRIBUTES.SEVERITY_LABEL: max_severity["label"] if self._attr_is_on else "",
            ATTRIBUTES.GRACE_PERIODS: grace_period_display,
            ATTRIBUTES.ACTIVE_VIOLATIONS: compliance_results.active_violations,
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


    def _is_logic_condition_compliant(self, condition: dict ) -> ComplianceResult:
        """
        Recursively process logical operators within a compliance rule.
        It handles complex nested structures including 'and', 'or', and 'not'
        metaconditions. Lists are treated as implicit 'and' groups. The method
        traverses the rule tree until it reaches atomic conditions, ensuring
        that logical hierarchies are respected during evaluation.
        """
        rule_target = condition["target"]
        rule_sev_raw = condition.get("severity", {"level": DEFAULT_SEVERITY})
        sev = rule_sev_raw["level"]
        sev_label = rule_sev_raw.get("label")
        base_compliance = ComplianceResult(
                    is_compliant=False,
                    is_graced=False,
                    is_snoozed=False,
                    active_violations = [],
                    pending_violations = [],
                    tracked_entities = [],
                    severity = sev,
                    severity_label = sev_label
            )

        if "grace_target" in condition:
            grace_delta = condition.get("grace_period", DEFAULT_GRACE)
            base_compliance.next_grace_expiry = self._determine_grace(grace_delta, condition["grace_target"])
            base_compliance.is_graced = base_compliance.next_grace_expiry is not None

        meta_results = base_compliance
        for i in condition:
            i_res = self._is_atomic_condition_compliant(i)
            if isinstance(condition, list) or "and" in condition:
                meta_results.is_compliant = meta_results.is_compliant and i_res.is_compliant
                meta_results.is_graced = meta_results.is_graced and i_res.is_graced
                meta_results.active_violations = meta_results.active_violations + i_res.active_violations
                meta_results.pending_violations = meta_results.pending_violations + i_res.pending_violations
                meta_results.tracked_entities = meta_results.tracked_entities + i_res.tracked_entities
                if not i_res.is_compliant:
                    meta_results.severity = min(meta_results.severity, i_res.severity)
                    meta_results.severity_label = f"{meta_results.severity_labe}; {i_res.severity_label}"
            elif "or" in condition:
                meta_results.is_compliant = meta_results.is_compliant or i_res.is_compliant
                meta_results.is_graced = not meta_results.is_compliant and (meta_results.is_graced and not i_res.is_active_violation)
                meta_results.active_violations = meta_results.active_violations + i_res.active_violations
                meta_results.pending_violations = meta_results.pending_violations + i_res.pending_violations
                meta_results.tracked_entities = meta_results.tracked_entities + i_res.tracked_entities
                if not i_res.is_compliant:
                    meta_results.severity = min(meta_results.severity, i_res.severity)
                    meta_results.severity_label = f"{meta_results.severity_labe}; {i_res.severity_label}"
            elif "not" in condition:
                # not (L and b) == not L or not b ; meta_results is already recursively-prenegated
                meta_results.is_compliant = meta_results.is_compliant or not i_res.is_compliant
                group_grace = meta_results.is_graced
                _child_grace = False # the not clause automatically nils the sub-graces
                #meta_results.is_graced = meta_results.is_graced or not i_res.is_graced
                i_res__negated_failures = list(set(i_res.tracked_entities) - set(i_res.active_violations))
                #   is there's a group grace, we extend it to all non-failing sub entities
                if group_grace:
                    meta_results.active_violations = []
                    meta_results.pending_violations = meta_results.pending_violations + i_res__negated_failures
                else:
                    meta_results.active_violations = meta_results.active_violations + i_res__negated_failures
                    meta_results.pending_violations = []
                meta_results.tracked_entities = meta_results.tracked_entities + i_res.tracked_entities
                if i_res.is_compliant:
                    meta_results.severity = min(meta_results.severity, i_res.severity)
                    meta_results.severity_label = f"{meta_results.severity_labe}; {i_res.severity_label}"

        return meta_results

    def _is_atomic_condition_compliant(self, condition: dict) -> ComplianceResult:
        """        Performs an atomic evaluation of a specific condition.
        Compares the target state or attribute against expected
        numeric ranges, specific states, or rendered templates to
        return a boolean violation result.
        """
        rule_target = condition["target"]["entity_id"]
        grace_delta = condition.get("grace_period", DEFAULT_GRACE)
        rule_sev_raw = condition.get("severity", { "level": DEFAULT_SEVERITY} )
        sev = rule_sev_raw["level"]
        sev_label = rule_sev_raw.get("label")
        base_compliance = ComplianceResult(
                    is_compliant=False,
                    is_graced=False,
                    is_snoozed=False,
                    active_violations = [rule_target],
                    pending_violations= [],
                    tracked_entities = [rule_target],
                    severity = sev,
                    severity_label = sev_label
            )
        actual_state = self.hass.states.get(rule_target)

        if timer_snooze := self._cattr_snooze_registry.get(rule_target):
            base_compliance.is_snoozed = False if not timer_snooze else not timer_snooze.is_expired
            base_compliance.next_snooze_expiry = timer_snooze.expiry

        # 2. Proceed with evaluation using actual_state
        target_attr = condition.get("attribute")
        val_to_check = actual_state.attributes.get(target_attr) if target_attr else actual_state.state

        state_obj = self.hass.states.get(rule_target)

        if state_obj is None:
            base_compliance.severity_label = f"{rule_target=} not found"
            return base_compliance
        elif state_obj.state == "unavailable" and condition.get("allow_unavailable", False):
            return base_compliance
        elif state_obj.state == "unknown" and condition.get("allow_unknown", False):
            return base_compliance
        elif target_attr and target_attr not in actual_state.attributes:
            base_compliance.severity = "no attribute"
            return base_compliance

        # A. Value Template
        if "value_template" in condition:
            try:
                is_compliant =  condition["value_template"].async_render(
                    variables={
                        "t_state": val_to_check,
                        "t_entity": actual_state,
                        "t_id": actual_state.entity_id
                    },
                    parse_result=True
                )
                if is_compliant:
                    base_compliance.is_snoozed = True
                    base_compliance.active_violations = []
                    return base_compliance
                else:
                    base_compliance.next_grace_expiry = self._determine_grace(grace_delta, rule_target)
                    base_compliance.is_graced = base_compliance.next_grace_expiry is not None
                    return base_compliance
            except Exception:
                base_compliance.severity = "invalid template"
                base_compliance.next_grace_expiry = self._determine_grace(grace_delta, rule_target)
                base_compliance.is_graced = base_compliance.next_grace_expiry is not None
                return base_compliance

        # B. Expected Numeric
        if "expected_numeric" in condition:
            try:
                val = float(val_to_check)
                limits = condition["expected_numeric"]
                if (    ("min" in limits and val < limits["min"] ) or
                        ( "max" in limits and val > limits["max"] ) ) :
                    base_compliance.next_grace_expiry = self._determine_grace(grace_delta, rule_target)
                    base_compliance.is_graced = base_compliance.next_grace_expiry is not None
                    base_compliance.pending_violations = rule_target
                    base_compliance.active_violations = []
                    return base_compliance
                base_compliance.is_compliant = True
                base_compliance.active_violations = []
                return base_compliance
            except (ValueError, TypeError):
                base_compliance.severity = "numeric condition error"
                base_compliance.next_grace_expiry = self._determine_grace(grace_delta, rule_target)
                base_compliance.is_graced = base_compliance.next_grace_expiry is not None
                return base_compliance

        # C. Expected State
        if "expected_state" in condition:
            expected = condition["expected_state"]
            if ( ( isinstance(expected, bool) and str(val_to_check).lower() in ON_EQUIVALENT_STATES ) or
                str(val_to_check).lower() == str(expected).lower() ) :
                base_compliance.is_compliant = True
                base_compliance.active_violations = []
                return base_compliance
            else :
                base_compliance.next_grace_expiry = self._determine_grace(grace_delta, rule_target)
                base_compliance.is_graced = base_compliance.next_grace_expiry is not None
                return base_compliance

        base_compliance.severity_label = "no atomic rule"
        return base_compliance

    def _determine_grace(self, grace_delta: timedelta, grace_target: str) -> datetime:
        # TODO: check if it's already in grace period, otherwise you just keep overwriting it
        if grace_delta:
            expiry = dt_util.now() + grace_delta
            self._cattr_violations_registry[grace_target] = self._create_timer(grace_target, expiry)
            return expiry
        return None

    def _get_severity_data(self, sev_cfg):
        if isinstance(sev_cfg, str):
            return {"level": SEVERITY_LEVELS.get(sev_cfg, 1), "label": sev_cfg.capitalize()}
        return {"level": sev_cfg["level"], "label": sev_cfg.get("label", f"Level {sev_cfg['level']}")}


def get_atomic_key(condition: dict) -> str | None:
    """Returns the atomic key if it's an atomic condition, else  None."""
    for key in condition:
        if key in ATOMIC_KEYS:
            return key
    return None

def get_logic_key(condition: dict) -> str | None:
    """Returns the logic key if it's an atomic condition, else  None."""
    for key in condition:
        if key in LOGIC_KEYS:
            return key
    return None