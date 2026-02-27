
# 🧪 Compliance Manager - Integration Lab (Test Mode)

This module provides a sandboxed environment to validate the Compliance Engine logic without relying on real-world hardware. It uses a controlled set of **40 virtual switches** and **10 binary sensors** to simulate complex failure scenarios.

## 🏗 Lab Architecture

The testing environment is built on three main components:

1.  **Mock Entities (`switch.py`)**: Each tester unit consists of three linked entities:
    * `switch.compliance_manager_lab_tester_N`: The primary state (ON/OFF).
    * `switch.compliance_manager_lab_tester_N_unav`: Forces the state to `unavailable`.
    * `switch.compliance_manager_lab_tester_N_unkn`: Forces the state to `unknown`.
2.  **Logic Engine**: Binary sensors (`lab_test_output_01` through `10`) configured within the Compliance component.
3.  **UI Control Panel**: A dedicated Home Assistant dashboard to inject states and observe results in real-time.

## 🛠 Developer Guide

### 1. State Injection
Instead of manually calling services, use the provided Dashboard:
* **Normal Transitions**: Toggle the **State** button to switch between `on` and `off`.
* **Edge Case Simulation**: Activate the **unav** or **unkn** toggles. These overrides are handled within the `switch.py` logic and take precedence over the primary state.

### 2. Test Case Mapping (Reference)

| Test ID | Scenario | Success Condition (Result = ON) |
| :--- | :--- | :--- |
| **01** | Simple State | All 4 assigned switches must be `ON`. |
| **02** | Grace Period | Violation triggers only after a **10s** persistence. |
| **03** | Logic AND | Combination of physical states and Jinja2 templates. |
| **04** | Criticality | Validates `severity: critical` propagation. |
| **05** | Logic NOT | Compliance passes if the entity is **NOT** `OFF`. |
| **06** | Availability | Tests `allow_unavailable: true` (Severity 40). |
| **07** | Group Grace | Applies a **20s** grace period to the entire group. |
| **08** | Template Only | Tests direct `states()` evaluation via templates. |
| **09** | Unknown State | Validates `allow_unknown: true` behavior. |
| **10** | Composite Panic | Complex AND-NOT logic with **Severity 100** (Panic). |

### 3. Debugging & Verification
To monitor how the engine evaluates logic during state changes, monitor the logs:

```bash
# Real-time log monitoring
tail -f /config/home-assistant.log | grep "compliance_manager"
