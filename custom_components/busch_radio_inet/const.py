"""Constants for the Busch-Radio iNet integration."""

DOMAIN = "busch_radio_inet"

# Config entry keys
CONF_HOST = "host"
CONF_PORT = "port"
CONF_NAME = "name"

# Default connection values
DEFAULT_PORT = 4244
DEFAULT_LISTEN_PORT = 4242
DEFAULT_NAME = "Busch-Radio iNet"

# Device specs
MAX_VOLUME = 31
MANUFACTURER = "Busch-Jäger / ABB"
MODEL = "8216 U"

# Polling interval for fallback (seconds)
POLL_INTERVAL = 300

# Timeout for config flow connection validation (seconds)
CONNECT_TIMEOUT = 5

# Notification event names
EVENT_POWER_ON = "POWER_ON"
EVENT_POWER_OFF = "POWER_OFF"
EVENT_VOLUME_CHANGED = "VOLUME_CHANGED"
EVENT_STATION_CHANGED = "STATION_CHANGED"
EVENT_URL_IS_PLAYING = "URL_IS_PLAYING"

# ICY metadata options (stored in config entry options, not data)
CONF_ICY_ENABLED = "icy_enabled"
CONF_ICY_MODE = "icy_mode"
CONF_ICY_INTERVAL = "icy_interval"

ICY_MODE_INTERVAL = "interval"
ICY_MODE_LIVE = "live"

DEFAULT_ICY_ENABLED = False
DEFAULT_ICY_MODE = ICY_MODE_INTERVAL
DEFAULT_ICY_INTERVAL = 60
