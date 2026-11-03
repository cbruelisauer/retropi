# retropi

This project turns an old radio into an internet radio that can also be a Bluetooth speaker. It runs on a Raspberry Pi 3B with a HiFiBerry Amp+. The radio's original controls are reused: the selector picks standby, internet radio or Bluetooth, and two potentiometers work as the station dial and the volume knob.

A small Python 3 service (`retropi`) reads the controls and drives MPD, the sound card's mixer, BlueZ and NetworkManager. It runs as user `pi` under systemd.

## Features

- **Internet radio**: streams the stations in `stations.m3u` through MPD. The station dial is split into equal bands, one per station.
- **Bluetooth speaker**: BlueALSA makes the Pi an A2DP sink. The Bluetooth adapter is powered only while the selector is on Bluetooth, so in every other position no phone can see or connect to the radio.
- **Volume knob**: the knob's full travel maps linearly in dB onto a configurable range (-80 to -38 dB by default) on the card's hardware mixer. It works for radio and Bluetooth.
- **Standby**: the Power and DAB positions stop all playback.
- **Startup sound**: a sound plays when the service starts.

## Hardware

| Part | Purpose |
| --- | --- |
| Raspberry Pi 3B | Main computer (Wi-Fi and Bluetooth share one 2.4 GHz chip) |
| HiFiBerry Amp+ | Stereo amplifier (TI TAS5713, I²S input) that drives the radio's speakers |
| MCP3008 | 10-bit ADC for reading the potentiometers |
| 2× linear potentiometer (10 kΩ) | Station dial and volume knob |
| Selector switch | Power, Internet radio, DAB, Bluetooth |
| An old radio | Case, speakers and knobs |

### Wiring (BCM numbering)

| Function | GPIO |
| --- | --- |
| Power position | 26 |
| Internet radio position | 13 |
| DAB position | 12 |
| Bluetooth position | 16 |
| Power LED *(reserved, not used yet)* | 5 |
| Status LED *(reserved, not used yet)* | 6 |
| MCP3008 CLK | 17 |
| MCP3008 MISO (DOUT) | 23 |
| MCP3008 MOSI (DIN) | 24 |
| MCP3008 CS | 25 |

The MCP3008 runs over software SPI. CH0 is the volume knob, CH1 the station dial.

The inputs use the Pi's internal pull-ups. Power, DAB and Bluetooth pull their input to GND when selected. The internet radio input is pulled to GND in every other position and reads **high** when selected.

The HiFiBerry Amp+ uses GPIO 2/3 (I²C) and 18–21 (I²S), so the pins above don't clash with it. All pins are set in `config.toml`.

## Installation

The install script turns a freshly flashed card into a working radio. Re-running it is also the update path.

1. Back up the current SD card if you have one: Wi-Fi credentials, `/etc/mpd.conf`, `/boot/config.txt` and the playlist.
2. Flash **Raspberry Pi OS Lite (Trixie)** with Raspberry Pi Imager. Set the user `pi`, Wi-Fi and SSH in the Imager settings.
3. On the Pi:

   ```sh
   sudo apt-get install -y git
   git clone https://github.com/cbruelisauer/retropi.git ~/retropi && cd ~/retropi
   sudo ./deploy/install.sh        # reboots once if the boot config changed
   ```

To update later:

```sh
cd ~/retropi && git pull && sudo ./deploy/install.sh
```

The script:

| Step | What it does |
| --- | --- |
| 1. Pre-checks | Stops unless it runs as root on Trixie; prints the board model |
| 2. Boot config | Writes a marked block into `/boot/firmware/config.txt` that turns off onboard audio and loads the `hifiberry-amp` overlay (the driver ships with the kernel) |
| 3. Packages | Installs MPD, BlueZ, BlueALSA, ALSA utilities and the Python libraries from apt |
| 4. System files | Copies the files in `system/` to their targets (see below) |
| 5. User | Adds `pi` to `gpio`, `audio`, `bluetooth`, `netdev` |
| 6. App | Installs the package into a venv in `/opt/retropi` and copies the sounds |
| 7. Config | Copies `config.toml` to `/etc/retropi/` only if missing, so your settings survive updates |
| 8. Playlist | Copies `stations.m3u` to MPD's playlist directory |
| 9. Services | Enables and restarts `mpd`, `bluetooth`, `bluealsa`, `bluealsa-aplay`, `retropi` |
| 10. Self-check | Prints the sound cards, mixer controls, Bluetooth adapter, service states and whether `pi` may switch Wi-Fi |

`sudo ./deploy/uninstall.sh` stops and removes the service and `/opt/retropi`, and keeps `/etc/retropi/`.

### Installed system files

| File in `system/` | Installed as | Why |
| --- | --- | --- |
| `asound.conf` | `/etc/asound.conf` | A shared `dmix` on the HiFiBerry card as the default device, so MPD, Bluetooth audio and the sounds can play at the same time |
| `mpd.conf` | `/etc/mpd.conf` | MPD plays to that `dmix` with `mixer_type "none"`, so only the volume knob sets the level |
| `bluetooth-main.conf` | `/etc/bluetooth/main.conf` | `AutoEnable=false` keeps the adapter off until the radio powers it |
| `bluealsa-a2dp-sink.conf` | `bluealsa.service` drop-in | BlueALSA runs as an A2DP sink only |
| `bluealsa-aplay-dmix.conf` | `bluealsa-aplay.service` drop-in | Phone audio plays to the shared `dmix` |
| `50-retropi-wifi.rules` | `/etc/polkit-1/rules.d/` | Lets group `netdev` run `nmcli radio wifi on/off` |
| `retropi.service` | `/etc/systemd/system/` | Runs the radio as `pi` |

## Configuration

All settings live in `/etc/retropi/config.toml` (the repo's [`config.toml`](config.toml) is the template): pins, ADC channels, knob tolerances, mixer name, volume range, MPD connection, Wi-Fi timeouts and Bluetooth options. Missing, unknown or mistyped keys stop the service at startup with a message in the journal.

Check the mixer name after the first boot and set `audio.mixer` to match:

```sh
amixer -c sndrpihifiberry scontrols
```

Tune `volume_min_db`, `volume_max_db` and `startup_volume_db` by ear, then restart the service:

```sh
sudo systemctl restart retropi
```

To change stations, edit `stations.m3u` and re-run the install script. Positions on the dial follow the order of the file.

## Usage

| Selector | What happens |
| --- | --- |
| **Internet radio** | Waits for Wi-Fi, then plays the station the dial points at. Station dial and volume knob are active. |
| **Bluetooth** | Turns Wi-Fi off, powers the Bluetooth adapter and opens the pairing window. Volume knob is active. |
| **Power** / **DAB** | Standby: stops playback and turns Bluetooth off. |

The selector is debounced: a new position counts once its input has been the only active one for 100 ms (`selector_settle_ms`). Between positions the radio keeps its last mode.

If Wi-Fi is not connected after `wifi_connect_timeout_s`, the radio tries anyway (Ethernet may be up) and checks every `play_retry_s` that the stream plays, restarting it if it failed to open or dropped.

`sudo systemctl stop retropi` sets the volume to 0, stops playback, powers Bluetooth off and turns Wi-Fi back on.

### Pairing a phone

1. Turn the selector to Bluetooth. The radio appears as "RetroPi".
2. On the phone, tap RetroPi in the Bluetooth settings. No PIN is needed.
3. The connect sound plays. Play music and use the volume knob.
4. Next time the phone reconnects by itself. The radio also tries to reconnect the last trusted phone when you turn to Bluetooth.
5. Turning the selector away powers the adapter off and drops the phone. The disconnect sound plays if a phone was connected.

New phones can pair only during the first 2 minutes after turning to Bluetooth (`pairing_window_s`). Trusted phones can reconnect at any time while in that position.

While on Bluetooth, Wi-Fi is off (`disable_wifi = true`) because Wi-Fi traffic makes A2DP audio stutter on the Pi 3B. SSH over Wi-Fi is not available in that position; Ethernet still works.

### Logs

```sh
journalctl -u retropi -f
```

## Development

The code is in `src/retropi/`, one module per concern:

| Module | Responsibility |
| --- | --- |
| `__main__.py` | Wiring, main loop, mode transitions, SIGINT/SIGTERM |
| `config.py` | Loads `config.toml` into frozen dataclasses |
| `controls.py` | Debounced selector, potentiometer knobs with hysteresis |
| `mixer.py` | Sets the card's mixer in dB |
| `sounds.py` | Plays the sound effects with `aplay` |
| `radio.py` | MPD playlist and playback, with reconnect |
| `bluetooth.py` | Adapter power, pairing window and agent, connect sounds (BlueZ over D-Bus) |
| `network.py` | Wi-Fi on/off and "connected?" through `nmcli` |

The unit tests use fakes for GPIO, MPD, ALSA and D-Bus, so they run on any machine with Python 3.11+:

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e '.[test]'
pytest
```

The BlueZ tests also need `pip install dbus-next`; without it they are skipped.

To run against the real hardware from a checkout on the Pi:

```sh
sudo systemctl stop retropi
cd ~/retropi && PYTHONPATH=src /opt/retropi/venv/bin/python -m retropi --config config.toml --debug
```
