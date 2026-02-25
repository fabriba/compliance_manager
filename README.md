# Compliance Manager for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
![version](https://img.shields.io/badge/version-0.1.0-blue.svg)

Compliance Manager permette di creare sensori di monitoraggio avanzati che aggregano lo stato di conformità di molteplici entità basandosi su regole personalizzabili.

---

## Table of Contents
* [Introduction](#introduction)
* [Installation](#installation)
* [Configuration](#configuration)
* [Usage & Examples](#usage--examples)
* [Services](#services)
* [Development & Testing](#development--testing)

---

## Introduction
A differenza dei gruppi nativi di Home Assistant, questa integrazione offre un controllo granulare sulla "salute" del sistema, permettendo di ignorare temporaneamente errori (Snooze) e gestire ritardi nella segnalazione (Grace Period).

## Installation

### Manual Installation
1. Scarica il repository.
2. Copia la cartella `compliance_manager` nella cartella `custom_components` della tua installazione.
3. Riavvia Home Assistant.

### HACS (Prossimamente)
Sarà possibile aggiungere questo repository come "Custom Repository" su HACS.

## Configuration

L'integrazione si configura esclusivamente tramite YAML. Aggiungi alla tua configurazione:

```yaml
binary_sensor:
  - platform: compliance_manager
    sensors:
      - name: "Nome Sensore"
        unique_id: "id_univoco"
        rules:
          # ... definisci qui le tue regole ...
