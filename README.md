# Compliance Manager 🛡️

[![GitHub Release](https://img.shields.io/github/release/fabriba/compliance_manager.svg?style=flat-square)](https://github.com/fabriba/compliance_manager/releases)
[![License](https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square)](LICENSE)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg?style=flat-square)](https://hacs.xyz/)

Compliance Manager is a powerful Home Assistant integration designed to monitor entity health and security compliance across your entire smart home.
Unlike standard groups, it provides granular control over "non-compliant" states, grace periods, severity and temporary silencing (snooze).



## Features

-   **Dynamic Targeting**: Track single entities, entire **Areas**, or **Labels**. New devices added to an area are picked up automatically.
-   **Attribute Inspection**: Monitor specific attributes (e.g., `battery_level`, `firmware_version`) instead of just the main state.
-   **Grace Periods**: Delay alerts to avoid false positives (e.g., only alert if a door is open for > 5 minutes). This is a Per-Entity grace, not a group grace
-   **Snooze Management**: Silencing service to ignore specific violations for a set duration (eg: someone is working in the garage, ignore port open for 2 hours).
-   **State Restoration**: All active timers, grace periods, and snoozes persist through Home Assistant restarts.
-   **Test Mode**: Built-in simulator for stress-testing your compliance logic. (requires tampering with the hardcoded constants in const.py, for developers only)

## Installation

### HACS (Recommended)
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=fabriba&repository=compliance_manager)

1. Go to **HACS** > **Integrations** > **3 dots menu**.
2. Select **Custom repositories**.
3. Add `https://github.com/fabriba/compliance_manager` with category `Integration`.
4. Click **Install**.
5. Restart Home Assistant.

### Manual

1. Download the `compliance_manager` folder from the [latest release](https://github.com/fabriba/compliance_manager/releases).
2. Copy it into your `custom_components` directory.
3. Restart Home Assistant.

## Configuration

The integration is configured via YAML. Add your sensors to `configuration.yaml`:

```yaml
binary_sensor:
  - platform: compliance_manager
    sensors:
      - name: "Critical Infrastructure"
        unique_id: "compliance_critical_infra"
        icon: "mdi:server-security"
        rules:
          # Rule 1: Area-wide check with Nested Logic
          - target:
              area_id: "server_room"
            condition:
              and: # Rule is violated if ANY sub-condition fails
                - expected_state: "on"
                - not:
                    attribute: "overheating"
                    expected_state: true
            severity: "critical"
            grace_period: "00:02:00"

          # Rule 2: Label-based check with Templates
          - target:
              label_id: "climate_sensors"
            condition:
              - value_template: "{{ state | float > 18.5 and state | float < 25.0 }}"
            severity: "warning"
            group_grace: true
            grace_period:
              minutes: 5

      - name: "Battery Health"
        unique_id: "compliance_battery_check"
        rules:
          - target:
              label_id: "battery_devices"
            condition:
              expected_numeric:
                min: 20
            allow_unavailable: false
            severity: "info"
```

## Snooze Service/Action
**Action: compliance_manager.snooze**
```yaml
data:
  entity_id: binary_sensor.server_security          # required: compliance_manager entity goes here
  entities:                                         # optional: sub-entities go here
    - switch.compliance_manager_lab_tester_3
  duration:
    minutes: 30
```
