AIO ESPHome Server
==================

Allow your Python program to show up to Home Assistant as an ESPHome device.

## Features

* Compatibility with ESPHome by using the official protocol definitions from the official `aioesphomeapi` library
* Serves the ESPHome native API as well as an HTTP server that is compatible with the official on-device web server, including the dashboard
* Fully async using asyncio
* Easy to use interface for hooking in your own entities
* Implemented ESPHome components:
  - Switch
  - Binary sensor
  - Light
  - Sensor
  - Number
  - Select
  - Climate
  - Button, Text, Text sensor
  - Cover, Fan, Lock, Media player, Siren, Valve, Water heater
  - Alarm control panel, Date, DateTime, Time, Update, Event
  - Camera, Infrared, Radio frequency
* Bluetooth proxy abstraction with an optional Bleak backend example
* Backend-neutral serial and Z-Wave proxy support for Native API 1.18 clients
* Action and argument descriptions/examples in service discovery
* Backend-neutral ESPHome Voice Assistant protocol support
* Optional ESPHome-compatible Noise encryption for the native API

## Usage

```python
import asyncio

from aioesphomeserver import (
    Device,
    SwitchEntity,
)

device = Device(
    name = "test-device",
    friendly_name = "Test Device",
    mac_address = "AC:BC:32:89:0E:C9",
    model = "Test Device",
    esphome_version = "0.0.1",
    project_name = "aioesphomeserver.test-device",
    project_version = "1.0.0",
)

device.add_entity(
    SwitchEntity(
        name = "Test Switch",
    )
)

asyncio.run(device.run())
```

Now you can visit `localhost:8080` to view the web interface or add your device to Home Assistant through the ESPHome integration.

`name` is the ESPHome node/hostname and should use lowercase letters, digits,
hyphens, or underscores. Human-readable text belongs in `friendly_name`. The
library normalizes legacy names containing spaces so the mDNS hostname,
`HelloResponse.name`, and `DeviceInfoResponse.name` remain identical.
`esphome_version` controls the version reported in `DeviceInfoResponse` and the
mDNS `version` TXT record; it defaults to `0.0.1`.
`project_name` is optional; if you set it, use the ESPHome-compatible
`vendor.project` format such as `aioesphomeserver.test-device`. Home Assistant
expects a dotted project name when the field is present, so this library omits
non-dotted values from `DeviceInfoResponse` and mDNS to avoid aborting device
registration.

## Native API encryption

Set `encryption_key` to the same base64-encoded 32-byte key that you enter in
Home Assistant:

```python
device = Device(
    name="test-device",
    friendly_name="Test Device",
    encryption_key="AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=",
)
```

Generate a new key with Python:

```python
import base64
import secrets

print(base64.b64encode(secrets.token_bytes(32)).decode("ascii"))
```

When a key is configured, the native API accepts only the ESPHome Noise
protocol (`Noise_NNpsk0_25519_ChaChaPoly_SHA256`). With no key, it retains the
plaintext behavior. Raw 32-byte values are also accepted. Keep the key secret;
changing it requires updating the Home Assistant integration entry as well.
Runtime key provisioning is not implemented, so the key must be configured on
both sides before connecting.

## Windows firewall

Home Assistant discovery uses mDNS/UDP, while adding the integration opens a
separate Native API TCP connection. A device can therefore be discovered but
remain stuck on the add screen when Windows Firewall blocks Python or port
`6053/TCP`.

Allow Python on private networks in the Windows Security prompt, or run this in
an elevated PowerShell session (adjust the port if needed):

```powershell
New-NetFirewallRule `
  -DisplayName "aioesphomeserver ESPHome API" `
  -Direction Inbound `
  -Profile Private `
  -Protocol TCP `
  -LocalPort 6053 `
  -Action Allow
```

If the web server is enabled, add a corresponding private-network rule for its
port (by default `8080/TCP`). Do not expose either port to public networks
unless the network design explicitly requires it.

## Development

This project is managed with [uv](https://docs.astral.sh/uv/) and supports Python 3.12+.

```bash
uv sync
uv run pytest
uv lock --upgrade
uv export --format requirements.txt --no-dev --no-emit-project --no-hashes --output-file requirements.txt
```

## Interfacing with your own code

Implement a listener:

```python
from aioesphomeserver import EntityListener

class MyCoolListener(EntityListener):
    async def handle(self, key, message):
        # handle receives every message destined for the the `entity_id` specified at object creation
        # so you can basically do whatever you want

    async def modify_something(self, value):
        entity = self.device.get_entity(self.entity_id)
        if entity is not None:
            await entity.set_state(value)

#...
device.add_entity(
    MyCoolListener(
        name="some cool listener",
        entity_id="whatever_thing"
    )
)
```

You can define methods on your listener to talk to other entities or you can retain a reference to `device` where you
have direct access to other entities as well as the ability to publish internal events.

## Status

_This is alpha quality at best._ Expect bugs, both striking and subtle. Use at your own risk.

`aioesphomeserver` supports plaintext and fixed-PSK Noise transport. On a
general-purpose host, network isolation or a VPN such as WireGuard/Tailscale can
still provide useful defense in depth.

See [API.md](API.md) for Native API, custom services, Home Assistant actions, Bluetooth proxy, camera, and Voice Assistant details. Runnable examples are in `examples/basic.py`, `examples/entity_showcase.py`, `examples/custom_services.py`, `examples/homeassistant_actions.py`, `examples/external_data_entities.py`, `examples/bleak_proxy.py`, `examples/camera.py`, and `examples/voice_assistant.py`.

The Bleak proxy example advertises runtime scanning-mode support. On Linux it
passes BlueZ `or_patterns` for passive scanning and falls back to active
scanning if Advertisement Monitor is unavailable. To use passive scanning on an
Orange Pi or Raspberry Pi, run BlueZ >= 5.56 with `bluetoothd --experimental`
and Linux kernel >= 5.10. The example reads the real `hci0` adapter MAC when
available, and otherwise derives stable, host-specific fallback identities.
Keep the device and adapter MACs stable and unique for each proxy so Home
Assistant can retain the remote adapter entry.

Bleak exposes parsed advertisement fields rather than the original HCI packet.
The example still advertises `RAW_ADVERTISEMENTS` because current ESPHome/HA
Bluetooth proxy paths prefer the raw advertisement message; when Bleak does not
provide original bytes, the library reconstructs a valid ADV payload from the
parsed name, UUID, service data and manufacturer data. Custom backends that can
forward real ADV/SCAN_RSP bytes should pass those bytes as `raw_data`.

## TODO

In rough priority order:

* [x] Finish Light web API
* [ ] Configurable ports and listening IPs
* [x] Button
* [x] Sensor
* [x] Cover
* [x] Zeroconf
* [x] Fan
* [x] Device-defined services
* [x] Call HA defined services
* [x] Event
* [x] TextSensor
* [x] Number
* [x] Select
* [x] Date & Time & DateTime
* [x] Valve
* [x] MediaPlayer
* [x] Siren
* [x] Alarm control panel
* [x] Camera
