# Compliance Manager for Home Assistant

**Compliance Manager** è un'integrazione personalizzata per Home Assistant progettata per monitorare la conformità dei dispositivi in modo dinamico. A differenza dei gruppi standard, permette di definire regole complesse, periodi di grazia (grace periods) e la gestione dei "silenziamenti" (snooze) delle violazioni.

## 🚀 Caratteristiche principali

* **Targeting Dinamico**: Monitora entità singole, intere **Aree** o **Label**. Se aggiungi un dispositivo a un'area, verrà monitorato automaticamente.
* **Ispezione Attributi**: Controlla non solo lo stato principale, ma qualsiasi attributo (es. livello batteria, versione firmware, segnale WiFi).
* **Grace Period**: Evita falsi allarmi permettendo alle entità di rimanere fuori norma per un tempo prestabilito prima di attivare la segnalazione.
* **Servizio Snooze**: Silenzia temporaneamente una violazione specifica direttamente dalla dashboard o tramite automazione.
* **Severità Dinamica**: Ogni regola può avere un livello di gravità (Critical, Warning, Info, ecc.) che determina lo stato del sensore principale.
* **Persistenza**: Tutti i timer (snooze e violazioni in corso) vengono salvati e ripristinati al riavvio di Home Assistant.

## 🛠️ Installazione

1.  Copia la cartella `compliance_manager` nella cartella `custom_components` della tua istanza di Home Assistant.
2.  Assicurati che la struttura sia la seguente:
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

## ⚙️ Configurazione

Aggiungi la piattaforma nel tuo file `configuration.yaml` sotto `binary_sensor`:

```yaml
binary_sensor:
  - platform: compliance_manager
    sensors:
      - name: "Sicurezza Perimetrale"
        unique_id: "sicurezza_perimetro_01"
        icon: "mdi:shield-home"
        rules:
          # Esempio 1: Controllo stato semplice (Tutte le porte chiuse)
          - target:
              label_id: "porte_esterne"
            expected_state: "off"
            severity: "critical"

          # Esempio 2: Controllo numerico con Grace Period (Batteria sensori)
          - target:
              area_id: "Soggiorno"
            attribute: "battery_level"
            expected_numeric:
              min: 20
            grace_period: "01:00:00" # Notifica solo se sotto il 20% per più di un'ora
            severity: "warning"

          # Esempio 3: Template personalizzato
          - target:
              entity_id: "sensor.nas_status"
          value_template: "{{ state == 'online' }}"
          severity: "problem"
