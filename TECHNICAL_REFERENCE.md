# Technical Reference: Home Assistant Integration `busch_radio_inet`

**Version:** 1.2.1
**Date:** June 2026
**Target Platform:** Home Assistant Custom Integration
**Development Language:** English (code, comments, variables)
**Repository:** https://github.com/moerk-o/ha-busch-radio-inet

---

## 1. Project Overview

### 1.1 Purpose

This integration controls **Busch-Jäger / ABB "Busch-Radio iNet" (model 8216 U)** in-wall internet radios from Home Assistant. The radio exposes a line-based UDP control protocol on the local network; the integration speaks that protocol to provide a `media_player` entity (power, volume, station selection, now-playing metadata and artwork) plus an optional set of device-settings entities read and written over the radio's HTTP configuration interface.

The integration is **local-only** (`iot_class: local_push`): all primary state changes are pushed by the device via UDP notifications, with a slow fallback poll as a safety net.

### 1.2 Component Overview

| Area | Modules | Responsibility |
|------|---------|----------------|
| **UDP transport** | `udp_client.py`, `udp_listener.py` | Send commands; receive and route incoming packets |
| **State coordinator** | `coordinator.py` | Hold device state, push updates to entities, orchestrate ICY + artwork |
| **Now-playing metadata** | `icy_client.py` | Read ICY `StreamTitle` from the audio stream (two strategies) |
| **Artwork** | `artwork_client.py` | Two-tier cover-art / station-logo lookup from public APIs |
| **HTTP settings (optional)** | `http_client.py`, `http_coordinator.py` | Read/write `/radio.cfg` device settings |
| **Entities** | `media_player.py`, `sensor.py`, `number.py`, `select.py`, `switch.py`, `time.py`, `button.py` | Home Assistant entity platforms |
| **Setup / config** | `__init__.py`, `config_flow.py`, `const.py` | Entry setup, UI configuration, constants |

### 1.3 Naming Convention

- **Domain:** `busch_radio_inet`
- **Device identifier:** the radio's serial number (`SERNO`), used as the config entry `unique_id`
- **Entity unique-id pattern:**
  - media_player: `{unique_id}` (the entry's unique id itself)
  - UDP energy-mode sensor: `{unique_id}_energy_mode`
  - HTTP settings entities: `{unique_id}_http_{field}` (e.g. `..._http_bb` for brightness)
  - HTTP time entities: `{unique_id}_http_{hour_key}_{minute_key}`

---

## 2. Communication Architecture

The radio is controlled through two independent channels: a mandatory **UDP control channel** and an optional **HTTP settings channel**. They are fully decoupled — the HTTP feature can be turned off without affecting playback control.

### 2.1 UDP Protocol

Commands are sent to the device on **port 4244**; the device sends responses and unsolicited notifications back to **port 4242**.

**Wire format** — CRLF-separated lines, always terminated by a blank line:

```
COMMAND:GET\r\n<parameter>\r\nID:HA\r\n\r\n     # query a value
COMMAND:SET\r\n<parameter>\r\nID:HA\r\n\r\n     # change a value
COMMAND:PLAY\r\n<parameter>\r\nID:HA\r\n\r\n    # start a station
```

Every command carries `ID:HA` as a sender tag. Responses echo this field, so the listener and parser deliberately drop the `ID:HA` echo line to avoid colliding with the station `ID` field used in `PLAYING_MODE` responses (see `parse_packet()` in `udp_listener.py`).

**Startup queries** (sent on every setup, answered asynchronously via the listener): `INFO_BLOCK`, `ALL_STATION_INFO`, `POWER_STATUS`, `VOLUME`, `PLAYING_MODE`.

**Notification → follow-up GET pattern:** Unsolicited `NOTIFICATION` packets (e.g. `VOLUME_CHANGED`, `STATION_CHANGED`, `URL_IS_PLAYING`, `POWER_ON`, `POWER_OFF`) do not contain the new value. The listener reacts by sending the matching `GET` (e.g. `VOLUME_CHANGED → GET VOLUME`) and additionally forwards the raw event name to the coordinator for higher-level reactions (ICY start/stop, artwork clearing).

### 2.2 Shared UDP Listener (multi-device)

**Decision:** A single `SharedUDPListener` binds once to port 4242 for the whole integration and routes incoming datagrams to the correct device coordinator by **source IP address**. It is created on the first device setup, reused by every further device, and stopped when the last device is unloaded.

**Context:** Port 4242 can only be bound once per host. The integration supports multiple radios (each its own config entry), so a per-entry listener would conflict on the second device. The device's source IP uniquely identifies which radio a packet came from.

**Why this approach:** One bind, N devices. The listener keeps a `host → (on_packet, on_notification, client)` registry and dispatches per datagram. Lifecycle is reference-counted via `has_devices`. The config-flow validation reuses the running listener when one already exists, instead of opening a second socket (see `validate_connection()` in `config_flow.py`).

**Alternatives considered:**
- One listener socket per config entry — rejected: second device fails to bind 4242.
- A single global coordinator for all devices — rejected: muddles per-device state and entity ownership.

**Consequences:** All packet routing depends on a correct, stable device IP. A device whose IP changes (DHCP) stops being matched until the entry is reconfigured. The shared object lives in `hass.data[DOMAIN]["shared_listener"]`.

### 2.3 Port Rebind on Reload

**Decision:** The listener socket is created with `SO_REUSEADDR` and `start()` retries the bind up to 5 times (0.5 s apart) before failing.

**Context:** On an integration reload the old socket is closed and a new one is opened almost immediately. The OS may still hold the port for a short moment, which would otherwise make a reload fail with `OSError: address already in use`.

**Why this approach:** `SO_REUSEADDR` plus a short retry loop bridges the close/reopen gap reliably. A failure after all retries surfaces as `ConfigEntryNotReady`, so Home Assistant retries setup later.

**Consequences:** Reloads (e.g. after an options change) are robust against transient port-busy errors.

### 2.4 Fire-and-Forget Client

The `BuschRadioUDPClient` (`udp_client.py`) is send-only: it opens a datagram endpoint, sends, and closes. It has **no receive socket** — all responses arrive through the shared listener. This keeps command sending stateless and avoids a second socket competing for port 4242.

---

## 3. Core Logic

### 3.1 State Coordinator

`BuschRadioCoordinator` (`coordinator.py`) is a **custom, push-based coordinator** — not a `DataUpdateCoordinator`. It holds the complete device state (power, volume, mute, station id/name, station list, media title, artwork URL, device info, energy mode) and a list of entity callbacks.

**Decision:** Use a hand-written callback coordinator for the UDP-driven media state instead of HA's polling `DataUpdateCoordinator`.

**Context:** The device pushes state via UDP notifications. The natural model is event-driven: a packet arrives → state is updated → entities are told to re-render. `DataUpdateCoordinator` is built around periodic polling and a single `data` snapshot, which fits the HTTP settings channel but not the push-based media state.

**Why this approach:** `handle_packet()` updates only the fields present in a packet and calls registered callbacks **only when something actually changed**. Entities register `async_write_ha_state` as the callback (`media_player.py`, energy-mode sensor in `sensor.py`). A slow fallback poll (`POLL_INTERVAL = 300 s`) re-queries power/volume/playing-mode in case a notification was lost.

**Alternatives considered:**
- `DataUpdateCoordinator` with short polling — rejected: wasteful and laggy for a push device; would poll a quiet device every few seconds for nothing.

**Consequences:** Two different coordinator styles coexist (push for media, polling for HTTP settings — see §3.4 and §6.4). Entities must register/unregister their callback in `async_added_to_hass` / `async_will_remove_from_hass`.

**Readiness / availability:** `is_ready` becomes true once both power and volume have been received. The media_player is `unavailable` until then and maps state to `OFF` / `IDLE` (powered, no station) / `PLAYING` (station active).

### 3.2 ICY Now-Playing Metadata

When a stream is playing, the song title is read from the audio stream's ICY metadata (`StreamTitle=...`). Two interchangeable strategies implement a common `IcyFetcher` protocol (`start(url)` / `stop()`):

| Mode | Class | Behaviour | Trade-off |
|------|-------|-----------|-----------|
| **Interval** (default) | `IcyIntervalScheduler` | Connects briefly every *N* s (10–300, default 60), reads the first metadata block, disconnects | Low bandwidth, title can lag up to *N* s |
| **Live** | `IcyPersistentConnection` | Holds the stream connection open, reacts to every metadata block immediately | Instant titles, ~16 KB/s continuous traffic per stream |

The mode, enable flag and interval are configured via the Options Flow (`CONF_ICY_*`). ICY is **off by default** (`DEFAULT_ICY_ENABLED = False`).

**Lifecycle coupling to playback state** (driven from the coordinator):
- `URL_IS_PLAYING` (stream stable) → `icy_fetcher.start(url)`
- `STATION_CHANGED` → stop fetch, clear title + artwork
- `POWER_OFF` → stop fetch, clear title + artwork
- **Already-playing-on-startup edge case:** when the radio is already streaming at integration load, no `URL_IS_PLAYING` event arrives. `__init__.py` schedules a one-shot `start_icy_if_playing()` 5 s after the startup queries settle.

### 3.3 Artwork Lookup

When the media title changes, the coordinator schedules an artwork lookup and writes the resulting `media_image_url`.

**Decision (concurrency):** Artwork lookups use a **cancel-and-replace** scheme guarded by a monotonically increasing **generation counter**.

**Context:** Titles can change rapidly (e.g. station hops, ad/jingle transitions). A naive "fire a lookup per title" approach risks a slow earlier lookup completing *after* a newer one and overwriting the correct artwork with stale data.

**Why this approach:** `_schedule_artwork_lookup()` cancels any in-flight task, increments `_artwork_generation`, and starts a new task tagged with that generation. When a lookup finishes it writes its result **only if its generation is still current** (`generation == self._artwork_generation`). `asyncio.CancelledError` is swallowed as the normal path.

**Consequences:** At most one authoritative result wins; superseded lookups can neither overwrite newer state nor leak. `stop_artwork()` cancels cleanly on station change / power off / unload.

**Decision (sources — two tiers, no API keys):** see `artwork_client.py`.

- **Tier 1 — music artwork** (only when the title parses into artist + song):
  1. **iTunes Search API** — primary; fast, broad mainstream coverage; thumbnail upscaled `100x100bb → 600x600bb`.
  2. **MusicBrainz + Cover Art Archive** — fallback; CC0 data, strong for classical/niche. A relevance `score >= 85` is required; release selection prefers *Official Album > Official > first*.
- **Tier 2 — station logo** (always, as final fallback): radio-browser.info by exact stream URL, then by station name (sorted by votes).

**Title parsing for Tier 1:** a title qualifies only when **exactly one** known separator is present — `Artist - Title` *or* `Title / Artist` (not both, to avoid ambiguity). Otherwise Tier 1 is skipped and the station logo is used. The same parsing rule backs the `media_artist` property in `media_player.py`.

> The `Title / Artist` variant was added in v1.0.6 — some stations send the ICY `StreamTitle` in that order.

**Caching & rate-limiting:** results (including "not found") are cached in-memory for the HA session — `_music_cache` keyed by `artist|title`, `_logo_cache` keyed by stream URL or name. MusicBrainz is rate-limited to one request per 1.5 s via a **module-level** timestamp shared across all `ArtworkClient` instances (i.e. across all radios in the same HA process), staying within MusicBrainz's 1 req/s policy.

---

## 4. Entities

All entities of one radio are grouped under a single device (identified by the entry `unique_id`). Platforms are loaded conditionally — see §6.2.

### 4.1 Media Player (always present)

`BuschRadioMediaPlayer` — the primary entity. `has_entity_name = True` with `name = None`, so it adopts the device name.

| Feature | Implementation |
|---------|----------------|
| Power | `TURN_ON` / `TURN_OFF` → `SET RADIO_ON` / `RADIO_OFF` |
| Volume | `VOLUME_SET` (0..1 mapped to raw 0..`MAX_VOLUME`=31), `VOLUME_STEP` (`VOLUME_INC`/`DEC`), `VOLUME_MUTE` |
| Source | `SELECT_SOURCE` — station name → `PLAY STATION:{id}` |
| Now playing | `media_title` (ICY title, falling back to station name), `media_artist` (parsed), `media_image_url` |

**Mute** is tracked locally (`set_muted`) because the device has no GET for mute state.

### 4.2 Energy Mode Sensor (always present alongside HTTP settings)

`BuschRadioEnergyModeSensor` — diagnostic sensor exposing `energy_mode` (PREMIUM / ECO). Its data comes from UDP `POWER_STATUS`, **not** HTTP, but it is registered on the `sensor` platform so it appears and disappears together with the HTTP diagnostic sensors.

### 4.3 HTTP Settings Entities (optional)

Loaded only when `expose_http_settings` is enabled. All read from the `HttpSettingsCoordinator` snapshot of `/radio.cfg` and write back via Read-Modify-Write (§6.4). Field keys are the radio's native `/radio.cfg` keys.

| Platform | Entities (field) |
|----------|------------------|
| **number** | Brightness (`bb`), Contrast (`co`), Timezone (`tz`, integer hours only), Short Timer Duration (`st`), Sleep Timer Duration (`ss`) |
| **select** | Backlight (`bl`), Display Mode (`dm`), Audio Mode (`ms`), Sound Mode (`sm`), Language (`ln`), Time Source (`zs`) |
| **switch** | Audio World (`aw`), Daylight Saving (`sz`), Alarm (`ea`), Short Timer (`et`), Sleep Timer (`es`) |
| **time** | Local Time (`hr`+`mi`), Alarm Time (`ah`+`am`) |
| **button** | Refresh Settings, Sync Time from Home Assistant |
| **sensor** | Switch Input (`sw`, read-only), Mains Voltage (`sp`, read-only), Energy Mode (UDP) |

**Switch semantics:** checkbox fields are `"1"` (on) / `""` (off).

**Time entities** combine two device fields (hour + minute) into a single `TimeEntity` and write both atomically.

**Sync Time button:** writes `hr`, `mi` and `zs=1` (Manual) atomically — the device ignores `hr`/`mi` while Internet time sync is active, so manual mode must be set together with the time. The user can switch back to Internet sync via the Time Source select.

**Read-only diagnostics:** `sw` ("Switch Input") and `sp` ("Mains Voltage") are exposed as sensors only and are **write-blocked** at the HTTP client level (§6.4). Their real meaning is **unconfirmed** — the device reports a value (observed: `4`) that matches neither originally assumed encoding (`sw`: 0/1/2, `sp`: 0/1), and both fields always carry the same value. No value mapping is applied (raw value shown) and both sensors are **disabled by default**.

---

## 5. ConfigFlow & Options Flow

### 5.1 Config Flow

A single-step user flow (`async_step_user`) collects **Host**, **Port** (default 4244) and **Name**. Validation:

1. `_async_abort_entries_match` aborts early if the same host is already configured.
2. `validate_connection()` sends `GET INFO_BLOCK` and waits up to `CONNECT_TIMEOUT` (5 s) for a response containing `SERNO`. If a shared listener already exists it is reused; otherwise a temporary validation socket is opened on port 4242.
3. The returned `SERNO` becomes the entry's `unique_id` (`_abort_if_unique_id_configured` prevents duplicates by serial).

The default name auto-increments for additional devices ("Busch-Radio iNet", "Busch-Radio iNet 2", …).

### 5.2 Options Flow

A single form (`async_step_init`) exposes:

| Option | Key | Default | Notes |
|--------|-----|---------|-------|
| ICY enabled | `icy_enabled` | `False` | Master switch for now-playing metadata |
| ICY mode | `icy_mode` | `interval` | `interval` or `live` |
| ICY interval | `icy_interval` | `60` | 10–300 s (slider); only relevant in interval mode |
| Expose HTTP settings | `expose_http_settings` | `False` | Loads the number/select/switch/time/button/sensor platforms |
| HTTP poll interval | `http_poll_interval` | `5` | 1–60 minutes |

Changing options triggers `async_reload_entry`, which fully reloads the config entry so platform sets and ICY/HTTP subsystems are rebuilt from the new options.

---

## 6. Technical Reference

### 6.1 Project Language & Code Style

- **Language:** English for all code, comments, docstrings, commit messages, release notes.
- **Type hints:** used throughout.
- **Linting:** Ruff.
- Logging is heavily used at `DEBUG` level (per-device, prefixed with the host) to make field debugging of the UDP/ICY/artwork pipeline tractable.

### 6.2 Platform Routing

`__init__.py` decides which platforms to load per entry:

| Condition | Platforms |
|-----------|-----------|
| Always | `media_player` |
| `expose_http_settings = True` | `number`, `select`, `switch`, `time`, `button`, `sensor` |

The chosen list is stored in `hass.data[DOMAIN][entry_id]["platforms"]` and used again on unload.

### 6.3 Entry Data, Options & `hass.data` Layout

- **Entry `data`** (immutable connection info): `host`, `port`, `name`.
- **Entry `options`** (reconfigurable): all `icy_*`, `expose_http_settings`, `http_poll_interval`.
- **`hass.data[DOMAIN]`:**
  - `"shared_listener"` → the single `SharedUDPListener`
  - `entry_id` → `{coordinator, client, cancel_startup_icy, http_coordinator, platforms, host}`

### 6.4 HTTP Settings: Read-Modify-Write

`HttpSettingsCoordinator` is a standard `DataUpdateCoordinator[dict[str, str]]` that polls `/radio.cfg` every `http_poll_interval` minutes. Writes go through `async_set(fields)`:

1. GET the full current `/radio.cfg`
2. patch the changed field(s) into the full dict
3. POST the **complete** dict to `/en/general.cgi`
4. `async_refresh()` to re-read the resulting state

**Decision:** Always write the full settings document, never a single field.

**Context:** `/en/general.cgi` accepts a full form post; posting a partial set risks the device resetting unlisted fields to defaults.

**Why this approach:** Read-Modify-Write preserves all other settings and makes multi-field changes (time entities, Sync Time) atomic from the device's perspective.

**Safety rails in `http_client.py`:**
- **Blocked fields** (`sw`, `sp`) are stripped from every POST — they are hardware-level (switch-input function, mains voltage) and must never be set over HTTP. They remain readable as diagnostic sensors.
- **Checkbox fields** (`aw`, `sz`, `ea`, `et`, `es`) are always included explicitly as `"1"` or `""`, because an omitted checkbox would read as "off" and could silently clear a setting.

The HTTP coordinator is started in the background (`async_create_task`) so an unreachable HTTP interface never blocks the main setup — entities simply stay `unavailable` until the first successful fetch.

### 6.5 Device Registration

| Field | Value |
|-------|-------|
| **Identifier** | `(DOMAIN, entry.unique_id)` — the serial number |
| **Name** | the user-defined entry name |
| **Manufacturer** | `Busch-Jäger / ABB` |
| **Model** | `8216 U` |
| **SW version** | `sw_version` from `INFO_BLOCK` |
| **Serial number** | `serial_number` from `INFO_BLOCK` (same value as the identifier/`unique_id`) |
| **Connections** | `(CONNECTION_NETWORK_MAC, mac)` — MAC from `INFO_BLOCK`, normalized via `format_mac()`; only set once the MAC has been received |
| **Configuration URL** | `http://{host}` — renders the "Visit" link to the device's web interface |

All `INFO_BLOCK` fields (serial, MAC, firmware) arrive asynchronously after the
startup query, so they populate the device record once the response is processed.
All entities reference the same identifier so they group under one device.

### 6.6 HACS Distribution

Distributed via HACS as a ZIP release. `hacs.json` sets `zip_release: true` and `filename: busch_radio_inet.zip`; the `release.yml` workflow builds that ZIP from `custom_components/busch_radio_inet/` on every published GitHub release and runs the test suite first.

**Brand images:** The integration ships its own icon locally in `custom_components/busch_radio_inet/brand/` (`icon.png` 256×256, `icon@2x.png` 512×512, transparent PNG). Since Home Assistant 2026.3, local brand images in a `brand/` folder are served via the brands proxy API and take priority over the brands CDN, so no pull request to the `home-assistant/brands` repository is required, and no `manifest.json` change is needed. There is no separate `logo` or `dark_` variant — the single icon reads well on both light and dark backgrounds. The folder is included in the release ZIP automatically.

### 6.7 File Structure

```
Busch_Radio_iNet/
├── custom_components/
│   └── busch_radio_inet/
│       ├── __init__.py            # Setup, shared-listener lifecycle, platform routing
│       ├── const.py               # Constants, option keys, defaults
│       ├── config_flow.py         # Config + Options flow, connection validation
│       ├── coordinator.py         # Push-based state coordinator (media)
│       ├── udp_client.py          # Fire-and-forget UDP sender
│       ├── udp_listener.py        # Shared UDP listener + packet parser
│       ├── icy_client.py          # ICY metadata: interval + persistent strategies
│       ├── artwork_client.py      # Two-tier artwork/logo lookup
│       ├── http_client.py         # /radio.cfg read + /en/general.cgi write
│       ├── http_coordinator.py    # DataUpdateCoordinator for HTTP settings
│       ├── media_player.py        # Media player entity
│       ├── sensor.py              # Energy-mode (UDP) + diagnostic HTTP sensors
│       ├── number.py / select.py / switch.py / time.py / button.py  # HTTP settings entities
│       ├── brand/                # Local brand images (icon.png, icon@2x.png) — HA 2026.3+
│       ├── manifest.json
│       ├── strings.json
│       └── translations/
├── tests/                         # pytest suite (+ tests/custom_components copy, see below)
├── .github/workflows/             # validate.yml (hassfest + HACS), release.yml (tests + ZIP)
├── hacs.json
├── pyproject.toml
├── requirements-test.txt
├── sync_and_test.sh               # rsync tests/ copy, then pytest
└── README.md / RELEASENOTES.md / LICENSE
```

### 6.8 Testing Notes

The `pytest-homeassistant-custom-component` plugin loads the integration from **`tests/custom_components/busch_radio_inet/`**, a copy of the production code that must be kept in sync. `sync_and_test.sh` rsyncs the copy before running pytest, and `pyproject.toml` points the coverage source at the test copy so coverage measures the code that actually executes. See the central `TESTING_GUIDE.md` §3.7.1.

### 6.9 manifest.json

| Field | Value | Note |
|-------|-------|------|
| `domain` | `busch_radio_inet` | |
| `config_flow` | `true` | UI configuration |
| `iot_class` | `local_push` | UDP notifications push state |
| `requirements` | `[]` | only HA-bundled libs (`aiohttp`, `voluptuous`) |
| `version` | `x.y.z` | single source of truth, matches the release tag |

---

## 7. Resources

| Topic | Link |
|-------|------|
| HA Developer Documentation | https://developers.home-assistant.io/ |
| Integration Manifest | https://developers.home-assistant.io/docs/creating_integration_manifest/ |
| ConfigFlow | https://developers.home-assistant.io/docs/config_entries_config_flow_handler/ |
| Media Player Entity | https://developers.home-assistant.io/docs/core/entity/media-player/ |
| DataUpdateCoordinator | https://developers.home-assistant.io/docs/integration_fetching_data/ |
| ICY / SHOUTcast metadata | https://cast.readme.io/docs/icy |
| iTunes Search API | https://performance-partners.apple.com/search-api |
| MusicBrainz API | https://musicbrainz.org/doc/MusicBrainz_API |
| Cover Art Archive | https://coverartarchive.org/ |
| radio-browser.info API | https://api.radio-browser.info/ |

---

## 8. Release Process

The release process follows the central `RELEASE_GUIDE.md` (HACS ZIP release, version in `manifest.json` = git tag, rolling `RELEASENOTES.md`). No project-specific deviations.

---

## 9. Version History

| Doc Version | Date | Changes |
|-------------|------|---------|
| 1.2.1 | June 2026 | Clarified `sw`/`sp` diagnostic sensors: meaning unconfirmed, raw value shown (no mapping), disabled by default |
| 1.2.0 | June 2026 | §6.5 device registration: documented serial number, MAC connection and configuration URL ("Visit" link) |
| 1.1.0 | June 2026 | Added §6.6 note on local brand images (`brand/` folder, HA 2026.3 brands proxy API); updated file structure |
| 1.0.0 | June 2026 | Initial technical reference — communication architecture, push coordinator, ICY strategies, artwork concurrency & sources, HTTP settings Read-Modify-Write, entity catalogue |

> **Doc version ≠ integration version.** This document is versioned independently of `manifest.json`.

---

*This technical reference documents the internal design of the `busch_radio_inet` Home Assistant integration. User-facing documentation lives in [`README.md`](README.md); release history in [`RELEASENOTES.md`](RELEASENOTES.md).*
