# Compliance Manager 🛡️

[![GitHub Release](https://img.shields.io/github/release/tuo_username/compliance_manager.svg?style=flat-square)](https://github.com/tuo_username/compliance_manager/releases)
[![License](https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square)](LICENSE)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg?style=flat-square)](https://hacs.xyz/)

Compliance Manager is a powerful Home Assistant integration designed to monitor entity health and security compliance across your entire smart home. Unlike standard groups, it provides granular control over "non-compliant" states, grace periods, and temporary silencing (snooze).



## Features

-   **Dynamic Targeting**: Track single entities, entire **Areas**, or **Labels**. New devices added to an area are picked up automatically.
-   **Attribute Inspection**: Monitor specific attributes (e.g., `battery_level`, `firmware_version`) instead of just the main state.
-   **Grace Periods**: Delay alerts to avoid false positives (e.g., only alert if a door is open for > 5 minutes). This is a Per-Entity grace, not a group grace
-   **Snooze Management**: Silencing service to ignore specific violations for a set duration.
-   **State Restoration**: All active timers, grace periods, and snoozes persist through Home Assistant restarts.
-   **Test Mode**: Built-in simulator for stress-testing your compliance logic.

## Installation

### HACS (Recommended)
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=fabriba&repository=compliance_manager)

1. Go to **HACS** > **Integrations** > **3 dots menu**.
2. Select **Custom repositories**.
3. Add `https://github.com/fabriba/compliance_manager` with category `Integration`.
4. Click **Install**.
5. Restart Home Assistant.

### Manual

1. Download the `compliance_manager` folder from the [latest release](https://github.com/tuo_username/compliance_manager/releases).
2. Copy it into your `custom_components` directory.
3. Restart Home Assistant.

## Configuration

The integration is configured via YAML. Add your sensors to `configuration.yaml`:

```yaml
binary_sensor:
  - platform: compliance_manager
    sensors:
      - name: "Security Compliance"
        unique_id: "security_compliance_01"
        icon: "mdi:shield-check"
        rules:
          # Check all doors in the Garage area
          - target:
              area_id: "garage"
            condition:
                expected_state: "off"
            severity: "critical"

          # Monitor battery levels with a 1-hour grace period
          - target:
              label_id: "battery_powered_devices"
            condition:
                - attribute: "battery_level"
                  expected_numeric:
                    min: 20
            grace_period: "01:00:00"
            group_grace: true # 1h in which there's always at least one non-com , default: False
            severity: "warning"
