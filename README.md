# Busch-Radio iNet

A Home Assistant custom integration for the Busch-Jäger Busch-Radio iNet (model 8216 U).

## What This Integration Does

Turns your Busch-Radio iNet into a fully-featured Home Assistant media player. The radio communicates locally over your home network – no cloud connection, no API key needed.

Features:

- **Media player entity** with turn on/off, volume control, mute, and source selection
- **Optional settings entities** – expose brightness, contrast, sound mode, alarm, sleep timer, and more as writable HA entities
- **Sync time button** – push HA's local time to the device

## Extra Features

### What is this?
- **Now-playing info** – artist and song title, read from the audio stream
- **Artwork** – album covers for the current song, fetched based on artist and title

### How it's done?

Sadly, the radio itself doesn't expose artist or song information. But it does tell us which stream is playing. So this integration can launch the stream by itself and extract the artist information from it. You can choose either an interval mode (reconnects periodically) or let the stream run the whole time the radio is playing.

**Note 1:** This will use additional resources on your HA server as well as your internet connection, as the stream is played a second time. (For each radio you have – if you live in a mansion with five bathrooms and have an iNet radio playing in each, it will be 10 streams and so on.)

**Note 2:** The artist information is not read from the exact same stream the radio is playing – it comes from a parallel connection. Therefore they won't be in sync – there will be a gap caused by buffering, Wi-Fi delay and other factors.

## How It Works

### Real-Time Updates

The radio proactively sends a notification to Home Assistant the instant something changes –
when you turn it on or off, adjust the volume, or switch stations. Home Assistant doesn't need
to constantly ask "anything new?"; the radio just tells it. This means the entities in HA always
reflect the current state without any noticeable delay.

When HA first starts up, it sends a few questions to the radio to retrieve the initial state
(power, volume, current station).

### Song & Artist Info

See [Extra Features](#extra-features) above for a full explanation of how song and artist
information is retrieved.

### Cover Art & Station Logos

Once HA knows the artist and song title, it automatically searches for the matching album cover:

1. **iTunes** – checked first; fast and covers most mainstream music
2. **MusicBrainz / Cover Art Archive** – used as a fallback for classical, jazz, and niche music

If only the station is known (no song info available), HA looks up the station's logo in the
**radio-browser.info** directory, first by stream URL, then by station name.

All images are cached for the current HA session, so they are never fetched twice for the same
song or station. No account or API key is needed.

## Requirements

- Busch-Jäger **Busch-Radio iNet** (obviously)
- UDP port **4242** available on the HA host (listen port)
- The radio's device port **4244** reachable from HA

## Installation

### HACS (Custom Repository)

1. Open HACS in your Home Assistant
2. Click the three dots → **Custom repositories**
3. Add `https://github.com/moerk-o/ha-busch-radio-inet` and select **Integration**
4. Install **Busch-Radio iNet**
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/busch_radio_inet` folder to your Home Assistant's `custom_components` directory
2. Restart Home Assistant

## Configuration

### Initial Setup

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **Busch-Radio iNet**
3. Enter:
   - **Host** – IP address of the radio (e.g. `192.168.1.123`)
   - **Port** – Device port (default: `4244`)
   - **Name** – Display name in HA (default: `Busch-Radio iNet`)
4. HA validates the connection by querying the device; setup fails if unreachable or device already configured.

### Options

After setup, open the integration options to configure:

| Option | Default | Description |
|--------|---------|-------------|
| **Enable "Now Playing" metadata** | disabled | Read current song and artist from the audio stream |
| **Fetch mode** | Interval | `Interval (every N seconds)` – reconnects periodically; `Live (persistent connection)` – holds connection open (~16 KB/s) |
| **Update interval (seconds)** | 60 s | How often to check for song updates in Interval mode (10–300 s) |
| **Expose device settings as HA entities** | disabled | Create additional entities for device settings |
| **Settings poll interval (minutes)** | 5 min | How often to read settings from the device (1–60 min) |

## Entities

### Media Player (`media_player.{name}`)

The main entity for controlling the radio.

| Property | Value |
|----------|-------|
| States | `playing` (station active), `idle` (on, no station), `off` |
| Features | Turn on/off, volume set/step, mute, source selection |

**Attributes shown in HA:**
- `media_title` – Song title from the stream, or station name if no song info is available
- `media_artist` – Artist name, parsed from the stream's `"Artist - Title"` format
- `media_image_url` – Album cover for the current song, or the station's logo
- `source` – Currently playing station name
- `source_list` – All configured stations

---

### Device Settings Entities (optional)

Enabled when **Expose device settings as HA entities** is turned on in the options. All settings
are fetched from the radio over the local network and written back when changed.

#### Audio

| Entity | Options | Description |
|--------|---------|-------------|
| `select.{name}_sound_mode` | `Rock` / `Jazz` / `Classic` / `Electro` / `Speech` | Equalizer preset |
| `switch.{name}_audio_world` | on / off | Audio World mode |

#### Display & Language

| Entity | Options / Range | Description |
|--------|-----------------|-------------|
| `number.{name}_brightness` | 0–100 | Display brightness |
| `number.{name}_contrast` | 0–100 | Display contrast |
| `select.{name}_backlight` | `Off` / `On` / `Auto` | Display backlight mode |
| `select.{name}_language` | `Deutsch`, `English`, … | Menu language – affects both the radio's on-device menu and its web interface |

#### Timers

| Entity | Range | Description |
|--------|-------|-------------|
| `switch.{name}_sleep_timer` | on / off | Sleep timer active |
| `number.{name}_sleep_timer_duration` | 0–120 min | Sleep timer duration |
| `switch.{name}_short_timer` | on / off | Short timer active |
| `number.{name}_short_timer_duration` | 0–120 min | Short timer duration |

#### Clock & Alarm

| Entity | Options / Range | Description |
|--------|-----------------|-------------|
| `select.{name}_time_source` | `Internet` / `Manual` | Clock source |
| `number.{name}_timezone` | −12 – +12 h | Timezone offset |
| `switch.{name}_daylight_saving` | on / off | Daylight saving time |
| `time.{name}_local_time` | HH:MM | Device clock (read/write) |
| `button.{name}_sync_time` | – | Push Home Assistant's current local time to the device |
| `switch.{name}_alarm` | on / off | Alarm enabled |
| `time.{name}_alarm_time` | HH:MM | Alarm time (read/write) |

#### Diagnostics (read-only)

| Entity | Values | Description |
|--------|--------|-------------|
| `sensor.{name}_energy_mode` | `PREMIUM` / `ECO` | Current energy mode |
| `sensor.{name}_switch_input` | `Switch` / `Button` / `Automatic` | External switch input function |
| `sensor.{name}_mains_voltage` | `110V` / `230V` | Configured mains voltage |
| `button.{name}_refresh_settings` | – | Force re-read of all device settings from the radio |

## Troubleshooting

### Integration setup fails with "Cannot connect"

- Confirm the IP address and port are correct
- Ensure UDP port 4242 is not already in use on the HA host
- Check that no firewall blocks traffic between HA and the radio

### Entity shows `unavailable`

The integration becomes unavailable if the radio does not respond at startup. Reload the
integration after fixing network connectivity.

### Song/artist info not updating

- Check that **Enable "Now Playing" metadata** is enabled in the integration options
- Some stations do not include song info in their stream; the station name will be used as fallback
- In Live mode, a stuck connection may need an integration reload

### Device settings not appearing

Enable **Expose device settings as HA entities** in the integration options and reload.

## Contributing

This project is open source and contributions are warmly welcomed! Issues for bugs or feature requests are just as appreciated as pull requests for code improvements.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments
- Inspired by the protocol documentation shared by [intruder7](https://forum.iobroker.net/user/intruder7) in this [ioBroker community thread](https://forum.iobroker.net/topic/24043/vorlage-busch-j%C3%A4ger-radio-inet-8216-u).
- Development assisted by [Claude](https://claude.ai/) (Anthropic)

---

⭐ **Like what you get?** Instead of buying me a coffee, give the project a star on GitHub!