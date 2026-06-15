### ✨ New Features

- **UPnP & AUX sources** – The media player source list now includes **UPnP** and **AUX**. Switching to UPnP turns the radio into a DLNA renderer, so Home Assistant can stream audio or send TTS to it. ([#5](https://github.com/moerk-o/ha-busch-radio-inet/issues/5))
- **Offline detection** – The radio is marked **unavailable** when it stops responding (powered off, network outage, crash) and recovers automatically once it is reachable again. ([#3](https://github.com/moerk-o/ha-busch-radio-inet/issues/3))
- **Station presets sensor** – A new read-only sensor exposes the 8 station preset slots (name and URL per slot), handy for building dashboard cards.
- **Integration icon** – The integration now ships its own icon, shown throughout the Home Assistant UI.
- **Device info** – The device page now shows the **serial number**, the **MAC address**, and a **Visit** link that opens the radio's web interface.

### 🐞 Bug Fixes

- **Device settings now actually apply** – Changing a device setting (sound mode, brightness, timers, …) previously reported success but never took effect on the radio. Writes now persist correctly. ([#6](https://github.com/moerk-o/ha-busch-radio-inet/issues/6))
- **Misleading diagnostic sensors** – "Switch Input" and "Mains Voltage" showed guessed values that did not match the device. They now show the raw value and are disabled by default.

### 🔧 Infrastructure

- **Minimum Home Assistant version is now 2026.3** – required for the local integration icon.

**Full Changelog**: https://github.com/moerk-o/ha-busch-radio-inet/compare/v1.0.6...v1.1.0

---

# v1.0.6

### 🐞 Bug Fixes

- **Improved artist/title separation** – The integration now accepts more stream formats. Previously only `Artist - Title` was recognised; `Title / Artist` is now supported as well.

**Full Changelog**: https://github.com/moerk-o/ha-busch-radio-inet/compare/v1.0.5...v1.0.6

---

# v1.0.5

### 🔮 What's up with all these releases?

They are a direct follow-up to [issue #1](https://github.com/moerk-o/ha-busch-radio-inet/issues/1). Since this integration currently has a very small user base, I've decided to iterate releases directly rather than going through a longer testing cycle – fixes go out as soon as they're ready, and so do some verifying improvements for #1. Thanks for your patience!

### 🐞 Bug Fixes

- **Cover stuck after song change** – The cover image was only updated when a new title arrived from the stream. If the stream sent an empty title between songs, the previous cover remained visible indefinitely. This is now fixed.

### 🔧 Improvements

- **Extended debug logging** – ICY stream connections, title changes, artwork URL updates, and all lookup steps are now fully logged at `DEBUG` level.

**Full Changelog**: https://github.com/moerk-o/ha-busch-radio-inet/compare/v1.0.4...v1.0.5

---

# v1.0.4

### 🐞 Bug Fixes

- **Artwork lookup** – Improved verification of cover results: iTunes now validates the artist name, MusicBrainz rejects low-confidence matches and prefers official album releases over compilations.

### 🔧 Improvements

- **Debug logging** – The artwork lookup now outputs detailed information at `DEBUG` log level. Useful for diagnosing unexpected behavior.

**Full Changelog**: https://github.com/moerk-o/ha-busch-radio-inet/compare/v1.0.3...v1.0.4

---

# v1.0.3

### ✨ New Features

- **Device name suggestion** – When adding an additional device, the name field now pre-fills with "Busch-Radio iNet 2" (or 3, etc.) instead of repeating the same default.

### 🐞 Bug Fixes

- **Multi-device setup** – Fixed an issue where adding a second device through the setup dialog would fail with a connection error even if the device was reachable.

**Full Changelog**: https://github.com/moerk-o/ha-busch-radio-inet/compare/v1.0.2...v1.0.3

---

# v1.0.2

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
