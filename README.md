# Compliance Manager for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
![version](https://img.shields.io/badge/version-0.1.0-blue.svg)
![license](https://img.shields.io/badge/license-MIT-green.svg)

**Compliance Manager** è un'integrazione personalizzata avanzata che permette di monitorare la conformità dei dispositivi della tua casa intelligente. A differenza dei gruppi standard, permette di definire regole complesse, gestire periodi di tolleranza (Grace Periods) e silenziare temporaneamente le violazioni (Snooze).

---

## 📖 Indice
* [Caratteristiche](#caratteristiche)
* [Installazione](#installazione)
* [Configurazione](#configurazione)
* [Esempi di Regole](#esempi-di-regole)
* [Servizi](#servizi)
* [Sviluppo e Debug](#sviluppo-e-debug)

---

## 🚀 Caratteristiche

* **Targeting Dinamico**: Monitora entità singole, intere **Aree** o **Label**. I nuovi dispositivi aggiunti alle aree verranno monitorati automaticamente.
* **Ispezione Attributi**: Supporto per il monitoraggio di attributi specifici (es. `battery_level`, `temperature`, `signal_strength`).
* **Grace Period**: Definisce quanto tempo un'entità può rimanere fuori norma prima che il sensore principale segnali un problema.
* **Snooze Manager**: Servizio dedicato per silenziare violazioni specifiche per una durata prestabilita.
* **Restore State**: I timer di snooze e i periodi di grazia persistono dopo il riavvio di Home Assistant.

---

## 🛠 Installazione

1.  Scarica i file dal repository.
2.  Copia la cartella `compliance_manager` nella cartella `custom_components` della tua installazione di Home Assistant.
    La struttura finale dovrà essere:
    ```text
    custom_components/compliance_manager/
    ├── __init__.py
    ├── binary_sensor.py
    ├── const.py
    ├── example_sensor.py
    ├── manifest.json
    └── services.yaml
    ```
3.  Riavvia Home Assistant.

---

## ⚙️ Configurazione

Aggiungi la configurazione al tuo file `configuration.yaml`. L'integrazione genera sensori di classe `problem`.

```yaml
binary_sensor:
  - platform: compliance_manager
    sensors:
      - name: "Monitoraggio Sicurezza"
        unique_id: "compliance_security_01"
        icon: "mdi:shield-check"
        rules:
          # Esempio: Tutte le luci esterne devono essere OFF
          - target:
              area_id: "Giardino"
            expected_state: "off"
            severity: "warning"
