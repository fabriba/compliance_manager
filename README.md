# Compliance Manager 🛡️

[![GitHub Release](https://img.shields.io/github/release/fabriba/compliance_manager.svg?style=flat-square)](https://github.com/fabriba/compliance_manager/releases)
[![License](https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square)](LICENSE)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg?style=flat-square)](https://hacs.xyz/)

Compliance Manager is a sophisticated Home Assistant integration designed to monitor entity health, security, and operational standards. It transforms complex state logic into simple binary "Compliance" sensors with advanced filtering, nested logic, and full state persistence.

---

## 🚀 Key Features

* **Dynamic Targeting**: Monitor single entities, **Areas**, or **Labels**. New devices added to a label or area are picked up automatically without a restart.
* **Deep Inspection**: Monitor main states, specific attributes, or use **Jinja2 Templates** for complex logic.
* **Boolean Logic Engine**: Nest your rules using `and`, `or`, and `not` blocks to create high-fidelity compliance checks.
* **Smart Grace Periods**: 
    * **Per-Entity**: Each device gets its own timer (e.g., alert only if a specific door is open for > 5 mins).
    * **Group Grace**: A single timer for the whole rule (e.g., alert if *any* device in the area has been non-compliant for > 5 mins).
* **Snooze Registry**: Use the `snooze` service to temporarily ignore specific failing entities.
* **Full Persistence**: Active snoozes and grace period timers survive Home Assistant restarts and integration reloads.
* **Native Reload**: Update your YAML and click **Reload Compliance Manager** in Developer Tools to apply changes instantly.

---

## 🛠️ Configuration

The integration is configured via YAML under the `binary_sensor` platform.

### Comprehensive Example
This example demonstrates nested logic, attribute monitoring, and template-based conditions.

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
