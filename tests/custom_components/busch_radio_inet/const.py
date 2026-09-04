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

# The radio answers only the first of a burst of UDP queries and drops the rest,
# and UDP has no retransmission — so queries are sent one at a time, this far
# apart (seconds), and unanswered ones are repeated after the delays below.
QUERY_SPACING = 0.4
STARTUP_RETRY_DELAYS = (2, 5, 15, 30)

# Timeout for config flow connection validation (seconds)
CONNECT_TIMEOUT = 5

# Setup probe: the device has to answer before an entry counts as set up.
# UDP has no retransmission, so a lost answer is retried before setup fails.
PROBE_TIMEOUT = 2.0
PROBE_ATTEMPTS = 3
PROBE_RETRY_DELAY = 0.5

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

# HTTP Settings feature (options)
CONF_EXPOSE_HTTP_SETTINGS = "expose_http_settings"
CONF_HTTP_POLL_INTERVAL = "http_poll_interval"

DEFAULT_EXPOSE_HTTP_SETTINGS = False
DEFAULT_HTTP_POLL_INTERVAL = 5  # minutes
