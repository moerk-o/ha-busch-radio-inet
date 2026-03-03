#!/usr/bin/env python3
"""test_icy.py – ICY stream metadata tester for Busch-Radio iNet.

Plays a radio stream via ffplay and shows StreamTitle changes in real-time.
Imports _parse_stream_title directly from the integration's icy_client.py.

Usage:
    python test_icy.py [1|2|3]
        1 = WDR 2           (default)
        2 = NDR 90.3
        3 = Rockantenne Hamburg
        4 = Absolut Relax

Prerequisites:
    pip install aiohttp
    sudo apt install ffmpeg   (for audio playback)
"""

import asyncio
import shutil
import subprocess
import sys
import types
from pathlib import Path

# ── 1. Mock HA modules so icy_client.py can be imported without Home Assistant ──

_ha_mock = types.ModuleType("homeassistant")
_ha_core = types.ModuleType("homeassistant.core")
_ha_core.HomeAssistant = type("HomeAssistant", (), {})
_ha_helpers = types.ModuleType("homeassistant.helpers")
_ha_helpers_event = types.ModuleType("homeassistant.helpers.event")
_ha_helpers_event.async_track_time_interval = lambda *a, **kw: None
_ha_helpers_aiohttp = types.ModuleType("homeassistant.helpers.aiohttp_client")
_ha_helpers_aiohttp.async_get_clientsession = lambda *a, **kw: None

sys.modules.update({
    "homeassistant": _ha_mock,
    "homeassistant.core": _ha_core,
    "homeassistant.helpers": _ha_helpers,
    "homeassistant.helpers.event": _ha_helpers_event,
    "homeassistant.helpers.aiohttp_client": _ha_helpers_aiohttp,
})

# ── 2. Import _parse_stream_title from the real integration ─────────────────

_INTEGRATION = Path(__file__).parent / "custom_components" / "busch_radio_inet"
sys.path.insert(0, str(_INTEGRATION))

from icy_client import _parse_stream_title  # noqa: E402

# ── 3. Hardcoded stream URLs ─────────────────────────────────────────────────
# These match the URLs returned by the device via GET ALL_STATION_INFO.
# Adjust here if your device uses different stream URLs.

STREAMS = {
    1: ("WDR 2",         "http://wdr-wdr2-ruhrgebiet.icecast.wdr.de/wdr/wdr2/ruhrgebiet/mp3/128/stream.mp3"),
    2: ("NDR 90.3",      "http://icecast.ndr.de/ndr/ndr903/hamburg/mp3/128/stream.mp3"),
    3: ("Rockantenne",   "https://s3-webradio.rockantenne.de/rockantenne/stream/mp3"),
    4: ("Absolut Relax", "https://absolut-relax.live-sm.absolutradio.de/absolut-relax/stream/mp3"),
}


# ── 4. Persistent ICY reader ─────────────────────────────────────────────────
# Same logic as IcyPersistentConnection._run / _read_loop in icy_client.py,
# but standalone (no HA, plain asyncio).

async def read_icy_persistent(url: str) -> None:
    """Connect to the stream and print StreamTitle whenever it changes."""
    import aiohttp

    print("Connecting for ICY metadata …")
    current_title: str | None = None

    try:
        timeout = aiohttp.ClientTimeout(connect=10)
        connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(
                url,
                headers={"Icy-MetaData": "1"},
                timeout=timeout,
            ) as resp:
                metaint_str = resp.headers.get("icy-metaint")
                if not metaint_str:
                    print("Stream does not support ICY metadata.")
                    return
                metaint = int(metaint_str)
                print(f"icy-metaint = {metaint} bytes  |  listening for title changes …")
                print("-" * 60)
                while True:
                    await resp.content.readexactly(metaint)          # skip audio
                    length_byte = await resp.content.readexactly(1)
                    meta_len = length_byte[0] * 16
                    if meta_len > 0:
                        raw = await resp.content.readexactly(meta_len)
                        title = _parse_stream_title(raw.decode("utf-8", errors="replace"))
                        if title != current_title:
                            current_title = title
                            print(f"  ▶  {title or '(empty title)'}")
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        print(f"\nICY connection error: {exc}")


# ── 5. Main ──────────────────────────────────────────────────────────────────

async def run(station_num: int) -> None:
    name, url = STREAMS[station_num]
    print(f"Station : {name}")
    print(f"URL     : {url}")
    print()

    if not shutil.which("ffplay"):
        print("WARNING: ffplay not found – audio playback skipped.")
        print("         Install with:  sudo apt install ffmpeg\n")
        ffplay = None
    else:
        print("Starting audio via ffplay (Ctrl+C to stop) …\n")
        ffplay = subprocess.Popen(
            ["ffplay", "-nodisp", "-loglevel", "quiet", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    try:
        await read_icy_persistent(url)
    except KeyboardInterrupt:
        pass
    finally:
        print("\nStopping.")
        if ffplay:
            ffplay.terminate()
            try:
                ffplay.wait(timeout=3)
            except subprocess.TimeoutExpired:
                ffplay.kill()


if __name__ == "__main__":
    num = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    if num not in STREAMS:
        print(f"Station {num} unknown. Choose 1, 2, 3, or 4.")
        sys.exit(1)
    try:
        asyncio.run(run(num))
    except KeyboardInterrupt:
        pass
