# Compliance Manager 🛡️

[![GitHub Release](https://img.shields.io/github/release/fabriba/compliance_manager.svg?style=flat-square)](https://github.com/fabriba/compliance_manager/releases)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg?style=flat-square)](https://hacs.xyz/)

**Compliance Manager** is a specialized Home Assistant integration designed to monitor the health, security, and operational status of your smart home entities using recursive logic.

It goes beyond simple state monitoring, offering granular control over nested conditions, attribute inspection, grace periods, and temporary silencing (snoozing).

* We all have badges with visibility rules to trigger when some device's state is unusual.
* Many of us may have created more or less complex sensors to make that visibility smarted
* As our smart home grows, we may end up having so many of those that it becomes increasingly difficult to maintain just the badges.
* I hope to have provided a working solution for those cases.

---

## 💡 Abandonware by Design

I created this integration because I felt Home Assistant lacked a flexible way to manage complex compliance logic. However, **I am fully aware of my time constraints and I won't be able to maintain this project in the long run.**

I went out of my way to create a working lab environment, documenting every function as thoroughly as possible to ensure that **forking and maintaining this is as simple as possible.** You are free to fork it, modify it, and take full credit—no strings attached. I hope this serves as a solid foundation for a feature that I believe can be beneficial to many.

---

## Features

- 🎯 **Dynamic Targeting**: Monitor single entities, entire **Areas**, or **Labels**. New devices added to an area are picked up immediately and automatically.
- 🌳 **Flexible Logic**: Build complex rules using templates, or simple maintainable ones using expectes states and basic modifiers.
- 🔍 **Attribute Inspection**: Check specific attributes (e.g., `battery_level`, `firmware_version`) or use Jinja2 templates for advanced evaluations.
- ⏳ **Intelligent Grace Periods**: Prevent false positives with per-entity or group-based grace periods that survive reboots.
- 💤 **Snooze Management**: A dedicated service to temporarily ignore specific violations (e.g., "ignore open garage door for 2 hours while working").
- 💾 **Persistence**: All active timers, grace periods, and snoozes are saved and restored across Home Assistant restarts.
- 🧪 **Developer Lab**: Built-in test environment generation to simulate and validate your compliance logic without affecting real devices. This includes a cleanup service for the switches created.

---

## Configuration

The integration is configured via YAML. Each sensor can track multiple `compliance` rules.

```yaml
binary_sensor:
  - platform: compliance_manager
    sensors:
      - name: "Critical Security"
        alias: "your description can go here, it's ignored by the code"
        unique_id: "compliance_critical_security"
        compliance:
          # Rule 1: Area-based monitoring with nested logic
          - target:
              area_id: "server_room"
            severity: 3  # default: problem (= 1) , can range 1-10
            expected_state: "on"
            allow_unavailable: true # default: false
            allow_unknown:     true # default: false
            attribute: "overheating"
            grace_period: "00:00:10"
            group_grace: true      # default: false
            allowed_violations: -2 #default: 0 ; negative X means "all but X"
          # Rule 2: Numeric check for battery levels via Labels
          - target:
              label_id: "battery_devices"
            severity: 
              level: "info"  # hardcoded severity names: {"critical": 0,"problem": 1,"warning": 2,"unusual": 3,"info": 4 }
              label: "custom-details-here"
            grace_period:
              minutes: 10
            expected_numeric:
                  min: 20
                  max: 30

      - name: "Climate Compliance"
        compliance:
          - target:
              entity_id: sensor.living_room_temp
            severity: "info"
            value_template: "{{ t_state | float > 18.5 and states(t_id) | float < 25.0 and states(t_entity.entity_id) == 20 }}"
```

### Configuration Keys

- **`target`**: Supports `entity_id`, `area_id`, or `label_id`.
- **attribute**: by default "state" is evaluated, if this is passed, state_attr is evaluated instead (ignored by value_template, see below)
- ** value_template**: you can use t_state, t_id or t_entity (t_ as in target). t_entity and t_id allow to access attributes
- **`condition`**: A list of conditions. Supports `expected_state`, `expected_numeric`, `value_template`, and logical operators (`and`, `or`, `not`).
- **`grace_period`**: Duration before a violation triggers the sensor. Accepts `HH:MM:SS` string or dictionary format.
- **`group_grace`**: If `true`, the grace period is shared across all entities in the rule (relay logic). default is false.
- **`allowed_violations`**: numberic: will only trigger a problem if more than x violations are found (eg: at least 2 windows are open) ; a negative number (eg: -2) can be used to indicate more than "all but 2" (eg: at least 2 entities must be compliant >> tollerate  violations unless there's less than 2 compliant entities)
- **`severity`**: Can be a string (`critical`, `problem`, `warning`, `unusual`, `info`) or a custom dict `{level: X, label: "Name"}`.
** allow_unavailable**: false by default, should be self explanatory (applies to attribute instead of state if attribute is passed)
** allow_unknown**: false by default, should be self explanatory (applies to attribute instead of state if attribute is passed)

---

## Services / Actions

### `compliance_manager.snooze`
Temporarily silences violations for specific entities or the whole sensor.

**YAML Example:**
```yaml
action: compliance_manager.snooze
data:
  entity_id: binary_sensor.critical_security
  sub_entities: # Optional: specific sub-entities to snooze (default: only the currently active violations to the compliant rule will be snoozed)
    - switch.server_rack_power 
  duration: "02:00:00"  #supports sub-keys minutes, seconds, hours, days, etc
```

## Installation

### HACS (Recommended)

1. Open **HACS** in your Home Assistant instance.
2. Go to the **Integrations** section.
3. Click the **three dots menu** in the top right corner.
4. Select **Custom repositories**.
5. Paste `https://github.com/fabriba/compliance_manager` into the URL field.
6. Select **Integration** as the Category and click **Add** (or click this)
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=fabriba&repository=compliance_manager)

7. Find the newly added **Compliance Manager** integration, click **Install**, and restart Home Assistant



### Manual
1. Download the `compliance_manager` folder from the [latest release](https://github.com/fabriba/compliance_manager/releases).
2. Copy the folder into your Home Assistant `custom_components` directory.
3. Restart Home Assistant.
