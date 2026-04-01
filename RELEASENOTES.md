### 🐞 Bug Fixes

- **Multi-device support** – Fixed an issue where adding a second device failed with "port already in use". The integration now uses a shared UDP listener that routes packets by source IP, supporting any number of devices simultaneously.

**Full Changelog**: https://github.com/moerk-o/ha-busch-radio-inet/compare/v1.0.1...v1.0.2

---

# v1.0.1

### ✨ Features

- **Media player entity** with turn on/off, volume control, mute, and source selection
- **Instant state updates** – the radio notifies Home Assistant immediately when something changes; no polling delay
- **Now-playing info** – current song title and artist, read directly from the audio stream (two modes: Interval or persistent Live connection)
- **Artwork** – album covers via iTunes / MusicBrainz, station logos via radio-browser.info; no API key required
- **Optional device settings entities** – expose brightness, contrast, backlight, sound mode (EQ), alarm, sleep timer, timezone, and more as writable HA entities
- **Sync Time button** – push Home Assistant's local time to the device with one tap

**This is the initial public release.**
