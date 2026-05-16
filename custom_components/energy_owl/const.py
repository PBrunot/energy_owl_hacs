"""Constants for the Energy OWL CM160 energy sensor component."""

import json
from pathlib import Path

DOMAIN = "energy_owl"
VERSION = json.loads((Path(__file__).parent / "manifest.json").read_text())["version"]

CONF_NOT_FIRST_RUN = "not_first_run"
CONF_ENABLE_HISTORICAL = "enable_historical_import"
CONF_VOLTAGE = "voltage"
CONF_VOLTAGE_ENTITY = "voltage_entity"

MODEL = "CM160"

# Configuration defaults
DEFAULT_UPDATE_INTERVAL = 15
DEFAULT_SCAN_INTERVAL = 30
DEFAULT_TIMEOUT = 5
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 1
DEFAULT_ENABLE_HISTORICAL = True
DEFAULT_VOLTAGE = 230.0
