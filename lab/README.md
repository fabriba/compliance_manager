
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

## 🚀 Deployment

Follow these steps to initialize the Integration Lab:

### 1. File Placement
Ensure the following files are located within your `custom_components/compliance_manager/` directory:
* **Mock Driver**: `switch.py`is installed with this integration. It generates the 40 testers and their override logic.
* **Logic Config**: Your YAML configuration defining the 10 `lab_test_output` sensors must be loaded. via
        `sensor: !include tests/lab_setup/compliance_manager_lab_sensors.yaml`

### 2. Entity Generation
Restart Home Assistant or reload the Integration. The system will automatically register:
* 40 primary switches (`tester_1` to `tester_40`).
* 80 helper switches for `unavailable` and `unknown` states.

### 3. Dashboard Setup
1. Open your Home Assistant UI.
2. Enter **Edit Dashboard** mode -> **Add View**.
3. Open the **Raw Configuration Editor**.
4. Paste the provided `dashboard.yaml` code. 


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
```

## 🧹 Cleanup & Teardown

To dismantle the Integration Lab and prevent "ghost" entities from cluttering your Home Assistant entity registry, follow this procedure:

### 1. Disable Configurations
* Remove or comment out the `!include` line in your `configuration.yaml` that loads the lab sensors.

### 2. Purge the Registry
Access **Developer Tools > Actions** (formerly Services) and run the following action:
* **Action**: `compliance_manager.cleanup_registry`
* this cleans up the 120 switches (4 groups of 3 for each of the 10 tests)
* manually delete the 10 test compliance_manager sensors

> [!IMPORTANT]
> This service identifies and removes orphaned entities previously managed by the Compliance Manager that are no longer present in your YAML configuration.

### 3. Finalize
* **Restart Home Assistant**: This ensures all virtual devices are fully unloaded from the state machine and the UI dashboard is cleared of unavailable entities.
