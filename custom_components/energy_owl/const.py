"""Constants for the Energy OWL CM160 energy sensor component."""

DOMAIN = "energy_owl"

CONF_NOT_FIRST_RUN = "not_first_run"

FIRST_RUN = "first_run"
OWL_OBJECT = "owl_object"
COORDINATOR = "coordinator"
UNDO_UPDATE_LISTENER = "undo_update_listener"

MODEL = "CM160"

# Configuration defaults
DEFAULT_UPDATE_INTERVAL = 15
DEFAULT_SCAN_INTERVAL = 30
DEFAULT_TIMEOUT = 5
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 1
