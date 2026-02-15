import logging
import re
from datetime import timedelta
import voluptuous as vol

from homeassistant.core import HomeAssistant, callback
from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_point_in_time,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers import (
    config_validation as cv,
    entity_registry as er,
    device_registry as dr,
    area_registry as ar,
    template as template_helper,
)
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_BINARY_SENSORS,
    CONF_GLOBAL_SENSOR,
    CONF_COMPLIANCE_CONDITIONS,
    CONF_EXPECTED_STATE,
    CONF_EXPECTED_NUMERIC,
    CONF_VALUE_TEMPLATE,
    CONF_GRACE_PERIOD,
    CONF_SEVERITY,
    SEVERITY_MAP,
    SEVERITY_LABELS,
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Setup della piattaforma binary_sensor per Compliance Manager."""
    if discovery_info is None:
        return

    # Recupera la configurazione validata da __init__.py
    full_config = hass.data[DOMAIN]
    sensors_config = full_config.get(CONF_BINARY_SENSORS, [])
    global_config = full_config.get(CONF_GLOBAL_SENSOR)

    entities = []
    
    # 1. Crea i sensori di conformità specifici
    compliance_sensors = []
    for sensor_conf in sensors_config:
        sensor = ComplianceBinarySensor(hass, sensor_conf)
        compliance_sensors.append(sensor)
        entities.append(sensor)

    # 2. Crea il Global Aggregator (se configurato)
    if global_config:
        aggregator = GlobalComplianceSensor(hass, global_config, compliance_sensors)
        entities.append(aggregator)

    async_add_entities(entities)


class ComplianceBinarySensor(BinarySensorEntity, RestoreEntity):
    """Sensore che monitora la conformità di un set di entità."""

    _attr_has_entity_name = False
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, hass: HomeAssistant, config: dict):
        self.hass = hass
        self._config = config
        self._attr_name = config["name"]
        
        # Generazione Unique ID stabile
        slug = config.get("entity_id", config["name"].lower().replace(" ", "_"))
        if slug.startswith("binary_sensor."):
            slug = slug.replace("binary_sensor.", "")
        self._attr_unique_id = f"compliance_{slug}"
        
        # Strutture dati
        self._monitored_entities = {} # {entity_id: {config_merged}}
        self._timers = {}             # {entity_id: cancel_callback}
        self._snooze_registry = {}    # {expiry_iso: [entity_ids]}
        
        # Attributi extra per il frontend
        self._attr_extra_state_attributes = {
            "severity": "Normal",
            "active_violations": [],
            "affected_entities": [],
            "snooze_registry": {},
            "count": 0
        }

    async def async_added_to_hass(self):
        """Handle entity which will be added."""
        # Registriamo noi stessi nel dizionario globale per il servizio snooze
        if "binary_sensor_component" not in self.hass.data:
            # Cerchiamo di risalire al component binary_sensor
            # (In un'integrazione professionale si userebbe async_setup_entry, 
            # ma in YAML setup_platform questo è il modo più rapido)
            self.hass.data["binary_sensor_component"] = self.registry_entry
            # Nota: useremo un approccio basato su eventi se questo fallisce
        
        await super().async_added_to_hass()
        # 1. Ripristino stato precedente (Snooze)
        last_state = await self.async_get_last_state()
        if last_state and last_state.attributes:
            self._snooze_registry = last_state.attributes.get("snooze_registry", {})
            self._clean_snooze_registry()

        # 2. Risoluzione Entità
        await self._resolve_monitored_entities()

        # 3. Registrazione Listener e check iniziale
        if self._monitored_entities:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    list(self._monitored_entities.keys()),
                    self._handle_state_change
                )
            )
            for entity_id in self._monitored_entities:
                self._check_compliance(entity_id)
            
            self._update_sensor_state()

    # --- NUOVO METODO PER IL SERVIZIO SNOOZE ---
    async def async_snooze_entity(self, entity_id: str, duration: timedelta):
        """Silenzia una violazione specifica per un tempo determinato."""
        if entity_id not in self._monitored_entities:
            _LOGGER.warning(f"Entità {entity_id} non monitorata da {self.name}")
            return

        expiry = (dt_util.utcnow() + duration).isoformat()
        
        # Aggiorna il registro locale
        if expiry not in self._snooze_registry:
            self._snooze_registry[expiry] = []
        
        if entity_id not in self._snooze_registry[expiry]:
            self._snooze_registry[expiry].append(entity_id)
            _LOGGER.info(f"Snoozed {entity_id} in {self.name} until {expiry}")

        self._update_sensor_state()
      
    async def _resolve_monitored_entities(self):
        """Logica gerarchica di risoluzione delle entità (Il cuore dell'integrazione)."""
        final_map = {}
        
        # Setup Default della Regola
        rule_defaults = {
            CONF_GRACE_PERIOD: self._config.get(CONF_GRACE_PERIOD, timedelta(0)),
            CONF_SEVERITY: self._config.get(CONF_SEVERITY, "Warning"),
            CONF_COMPLIANCE_CONDITIONS: self._config[CONF_COMPLIANCE_CONDITIONS],
        }

        # Helper per merge
        def merge_conf(base, override):
            new_conf = base.copy()
            if override.get(CONF_GRACE_PERIOD): new_conf[CONF_GRACE_PERIOD] = override[CONF_GRACE_PERIOD]
            if override.get(CONF_SEVERITY): new_conf[CONF_SEVERITY] = override[CONF_SEVERITY]
            return new_conf

        # --- LIVELLO 3: TARGET GLOBALI (Aree, Device, Label ID grezzi) ---
        # Nota: Qui usiamo i metodi interni dei registry per espandere i target
        target = self._config.get("target", {})
        
        # Espansione Area -> Entità
        ent_reg = er.async_get(self.hass)
        dev_reg = dr.async_get(self.hass)
        
        target_entities = set(target.get("entity_id", []))
        
        # Risoluzione Device -> Entità
        for dev_id in target.get("device_id", []):
            entries = er.async_entries_for_device(ent_reg, dev_id)
            target_entities.update(e.entity_id for e in entries)
            
        # Risoluzione Area -> Device -> Entità
        for area_id in target.get("area_id", []):
            # Device nell'area
            for dev in dr.async_entries_for_area(dev_reg, area_id):
                entries = er.async_entries_for_device(ent_reg, dev.id)
                target_entities.update(e.entity_id for e in entries)
            # Entità orfane nell'area
            entries = er.async_entries_for_area(ent_reg, area_id)
            target_entities.update(e.entity_id for e in entries)

        for ent_id in target_entities:
            final_map[ent_id] = rule_defaults

        # --- LIVELLO 2: LABEL OVERRIDES ---
        # Itera su tutte le entità del registro per trovare le label (più lento ma preciso)
        # Ottimizzazione: Usiamo il nuovo label_registry di HA se disponibile, altrimenti scan
        configured_labels = self._config.get("labels", [])
        if configured_labels:
            # Normalizziamo input (può essere stringa o dict)
            label_confs = {}
            for l in configured_labels:
                if isinstance(l, str): label_confs[l] = {}
                else: label_confs[l["label"]] = l
            
            # Scansione registry per label
            # (Nota: HA > 2024.4 supporta label native)
            all_entries = ent_reg.entities.values()
            for entry in all_entries:
                for label in entry.labels:
                    if label in label_confs:
                        # Trovata entità con label monitorata
                        base = final_map.get(entry.entity_id, rule_defaults)
                        final_map[entry.entity_id] = merge_conf(base, label_confs[label])

        # --- LIVELLO 1: ENTITY OVERRIDES (Massima priorità) ---
        for ent_def in self._config.get("entities", []):
            if isinstance(ent_def, str):
                ent_id = ent_def
                override = {}
            else:
                ent_id = ent_def["entity"]
                override = ent_def
            
            base = final_map.get(ent_id, rule_defaults)
            final_map[ent_id] = merge_conf(base, override)

        self._monitored_entities = final_map

    @callback
    def _handle_state_change(self, event):
        """Callback scatenato al cambio di stato di un'entità monitorata."""
        entity_id = event.data["entity_id"]
        self._check_compliance(entity_id)
        self._update_sensor_state()

    def _check_compliance(self, entity_id):
        """Valuta le condizioni per una singola entità."""
        conf = self._monitored_entities.get(entity_id)
        if not conf: return

        state = self.hass.states.get(entity_id)
        
        # Gestione Unavailable/Unknown (Hardcoded flags per semplicità, espandibili)
        if not state or state.state in ["unavailable", "unknown"]:
            # Qui potremmo implementare 'ignore_unavailable' se fosse nel conf
            return 

        is_compliant = self._evaluate_recursive(state, conf[CONF_COMPLIANCE_CONDITIONS])
        
        if is_compliant:
            # È conforme: Cancella timer se esisteva
            self._cancel_timer(entity_id)
            # Rimuovi da violazioni attive
            self._remove_violation(entity_id)
        else:
            # Non conforme: Avvia timer se non esiste
            if entity_id not in self._timers and not self._is_in_violation(entity_id):
                grace = conf[CONF_GRACE_PERIOD]
                if grace.total_seconds() > 0:
                    self._timers[entity_id] = async_track_point_in_time(
                        self.hass,
                        lambda now: self._confirm_violation(entity_id),
                        dt_util.utcnow() + grace
                    )
                else:
                    self._confirm_violation(entity_id)

    def _evaluate_recursive(self, state, conditions):
        """Valuta le condizioni ricorsive (AND/OR/NOT)."""
        if isinstance(conditions, list):
            return all(self._evaluate_recursive(state, c) for c in conditions)
        
        if "and" in conditions:
            return all(self._evaluate_recursive(state, c) for c in conditions["and"])
        if "or" in conditions:
            return any(self._evaluate_recursive(state, c) for c in conditions["or"])
        if "not" in conditions:
            return not self._evaluate_recursive(state, conditions["not"])

        # Condizioni Atomiche
        val_to_check = state.state
        if conditions.get("attribute"):
            val_to_check = state.attributes.get(conditions["attribute"])

        # 1. Template
        if conditions.get(CONF_VALUE_TEMPLATE):
            tmpl = conditions[CONF_VALUE_TEMPLATE]
            tmpl.hass = self.hass
            try:
                # Passiamo entity_id e state al template
                res = tmpl.async_render(variables={"entity_id": state.entity_id, "state": state})
                return str(res).lower() == "true"
            except Exception as e:
                _LOGGER.warning(f"Errore template per {state.entity_id}: {e}")
                return False

        # 2. Expected State
        if conditions.get(CONF_EXPECTED_STATE):
            expected = conditions[CONF_EXPECTED_STATE]
            if isinstance(expected, list):
                return str(val_to_check) in [str(e) for e in expected]
            return str(val_to_check) == str(expected)

        # 3. Numeric State
        if conditions.get(CONF_EXPECTED_NUMERIC):
            try:
                num_val = float(val_to_check)
                criterion = conditions[CONF_EXPECTED_NUMERIC]
                match = re.match(r"([<>=!]+)\s*(-?\d+\.?\d*)", criterion)
                if match:
                    op, target = match.groups()
                    target = float(target)
                    ops = {
                        ">": lambda x,y: x>y, "<": lambda x,y: x<y,
                        ">=": lambda x,y: x>=y, "<=": lambda x,y: x<=y,
                        "==": lambda x,y: x==y, "!=": lambda x,y: x!=y
                    }
                    return ops.get(op, lambda x,y: False)(num_val, target)
            except (ValueError, TypeError):
                return False
                
        return True

    @callback
    def _confirm_violation(self, entity_id):
        """Timer scaduto: conferma la violazione."""
        self._cancel_timer(entity_id) # Pulizia riferimento
        
        # Aggiungi a violazioni confermate (Severità è calcolata qui)
        conf = self._monitored_entities[entity_id]
        sev_label = conf[CONF_SEVERITY]
        
        # Salviamo la violazione come tupla (entity_id, severity_value, severity_label)
        # Usiamo un dict interno per gestire lo stato
        current_violations = dict(self._attr_extra_state_attributes.get("raw_violations", {}))
        current_violations[entity_id] = sev_label
        
        self._attr_extra_state_attributes["raw_violations"] = current_violations
        self._update_sensor_state()

    def _remove_violation(self, entity_id):
        raw = dict(self._attr_extra_state_attributes.get("raw_violations", {}))
        if entity_id in raw:
            del raw[entity_id]
            self._attr_extra_state_attributes["raw_violations"] = raw
            self._update_sensor_state()

    def _cancel_timer(self, entity_id):
        if entity_id in self._timers:
            self._timers[entity_id]() # Chiama la funzione di cancellazione di HA
            del self._timers[entity_id]

    def _is_in_violation(self, entity_id):
        raw = self._attr_extra_state_attributes.get("raw_violations", {})
        return entity_id in raw

    def _clean_snooze_registry(self):
        """Rimuove snooze scaduti."""
        now = dt_util.utcnow().isoformat()
        new_reg = {k: v for k, v in self._snooze_registry.items() if k > now}
        self._snooze_registry = new_reg

    def _update_sensor_state(self):
        """Calcola lo stato finale del sensore e gli attributi."""
        self._clean_snooze_registry()
        
        raw_violations = self._attr_extra_state_attributes.get("raw_violations", {})
        all_bad_entities = list(raw_violations.keys())
        
        # Calcolo Snoozed
        snoozed_entities = set()
        for ents in self._snooze_registry.values():
            snoozed_entities.update(ents)
            
        active_violations = [e for e in all_bad_entities if e not in snoozed_entities]
        
        # Aggiornamento Attributi Pubblici
        self._attr_is_on = len(active_violations) > 0
        self._attr_extra_state_attributes["affected_entities"] = all_bad_entities
        self._attr_extra_state_attributes["active_violations"] = active_violations
        self._attr_extra_state_attributes["count"] = len(active_violations)
        self._attr_extra_state_attributes["snooze_registry"] = self._snooze_registry
        
        # Calcolo Severità Massima
        max_sev_val = 99
        max_sev_label = "Normal"
        
        if active_violations:
            # Default fallback
            max_sev_label = self._config.get(CONF_SEVERITY)
            
            for ent in active_violations:
                label = raw_violations[ent]
                val = SEVERITY_MAP.get(str(label).lower(), 99)
                if val < max_sev_val:
                    max_sev_val = val
                    max_sev_label = label
        
        self._attr_extra_state_attributes["severity"] = max_sev_label
        
        # Scrivi stato in HA
        self.async_write_ha_state()


class GlobalComplianceSensor(BinarySensorEntity):
    """Aggregatore globale."""
    
    _attr_has_entity_name = True 
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, hass, config, sensors):
        self.hass = hass
        self._sensors = sensors # Lista di oggetti ComplianceBinarySensor
        self._attr_name = config["name"]
        self._attr_unique_id = f"compliance_global_{config.get('entity_id', 'main')}"

    async def async_added_to_hass(self):
        # Ascolta i cambiamenti di stato dei sensori figli
        ids = [s.entity_id for s in self._sensors] # Nota: entity_id è disponibile solo dopo add_entities
        # Qui c'è un tricky part: gli entity_id potrebbero non essere pronti subito in async_setup_platform.
        # Meglio ascoltare un evento generico o collegarsi dopo.
        # Per semplicità in questa versione Custom, assumiamo di ascoltare tutti i binary_sensor.compliance_*
        self.async_on_remove(
            async_track_state_change_event(self.hass, [s.entity_id for s in self._sensors], self._update)
        )

    @callback
    def _update(self, event=None):
        active_rules = []
        notes = []
        worst_val = 99
        
        for sensor in self._sensors:
            if sensor.is_on:
                active_rules.append(sensor.name)
                sev = sensor.extra_state_attributes.get("severity")
                val = SEVERITY_MAP.get(str(sev).lower(), 99)
                if val < worst_val:
                    worst_val = val
                
                # Raccogli note custom (severità > 5 o stringhe libere)
                if val >= 5 and sev not in notes:
                    notes.append(sev)

        self._attr_is_on = len(active_rules) > 0
        
        # Formattazione Severità
        main_label = SEVERITY_LABELS.get(worst_val, "Normal") if active_rules else "Normal"
        if notes:
            self._attr_extra_state_attributes = {
                "severity": f"{main_label} ({', '.join(notes)})",
                "active_violations": active_rules
            }
        else:
             self._attr_extra_state_attributes = {
                "severity": main_label,
                "active_violations": active_rules
            }
        
        self.async_write_ha_state()
