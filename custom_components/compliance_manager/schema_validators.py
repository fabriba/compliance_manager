import voluptuous as vol

def _recursive_validate_target(item):
    """Recursively verify that every condition branch has a target (local or inherited)."""
    ATOMIC_KEYS = {"expected_state", "expected_numeric", "value_template"}
    LOGIC_KEYS = {"and", "or", "not"}

    if not isinstance(item, dict):
        raise vol.Invalid(f"Condition item must be a dictionary: {item=}")

    # 1. Check if this specific node introduces a target
    # If the 'target' key exists and is not None, this branch is covered
    has_local_target = item.get("target") is not None
    if has_local_target:
        return True  # This node is valid as it has its own target

    # 2. Identify if the node is LOGICAL or ATOMIC
    found_logic_key = next((k for k in LOGIC_KEYS if k in item), None)
    is_atomic = any(k in item for k in ATOMIC_KEYS)

    # 3. Validation Logic
    if found_logic_key:
        # If logical, descend into children and pass the inheritance flag
        children = item[found_logic_key]
        child_list = children if isinstance(children, list) else [children]
        for child in child_list:
            _recursive_validate_target(child)
        return True

    # If we reach here, the node is empty or malformed
    raise vol.Invalid(f"Missing target for condition: {item=}")


def _binarysensor_schema_validator(config):
    """Final validation function for the integration platform."""
    sensors = config.get("sensors", [])
    used_unique_ids = set()
    for idx, sensor in enumerate(sensors):
        name = sensor.get("name")
        raise_id = f"sensor {idx} ({name=}) - "

        unique_id = sensor.get("unique_id")
        if unique_id:
            if unique_id in used_unique_ids:
                raise vol.Invalid(f"{raise_id} duplicate unique_id '{unique_id}'")
            used_unique_ids.add(unique_id)

        # validate 'compliance' list further if needed
        if "compliance" not in sensor or not isinstance(sensor["compliance"], list):
            raise vol.Invalid(f"{raise_id} missing 'compliance' or not  a list")


        for cidx, rule in enumerate(sensor.get("compliance", [])):
            # The root of the compliance rule can define a global target
            root_has_target = rule.get("target") is not None
            if root_has_target:
                return config

            # Conditions is a list of root condition nodes
            for cond in rule.get("condition", []):
                try:
                    _recursive_validate_target(rule)
                except Exception as e:
                    raise vol.Invalid(f"{raise_id} -{cidx} compliance validation error - {e}")

    return config