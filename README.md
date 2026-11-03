# retropi

This project turns an old radio into an internet radio that can also be a Bluetooth speaker. It runs on a Raspberry Pi with a [HiFiBerry Amp2](https://www.hifiberry.com/shop/boards/hifiberry-amp2/). The radio's original controls are reused: the mode buttons pick internet radio, DAB or Bluetooth, and two potentiometers work as the station dial and the volume knob.

## Features

- **Internet radio**: streams from a playlist through MPD/`mpc`. The station knob picks a station.
- **Bluetooth speaker**: the Pi becomes a discoverable Bluetooth audio sink through [bt-speaker](https://github.com/lukasjapan/bt-speaker). Wi-Fi is turned off while Bluetooth is active.
- **Analog volume knob**: a potentiometer read through an MCP3008 ADC sets the ALSA volume.
- **Power / standby button**: stops all playback.
- **Wake-up alarm**: in standby, the radio starts playing at 06:55.
- **Startup sound**: a sound plays when the radio starts.

## Hardware

| Part | Purpose |
| --- | --- |
| Raspberry Pi (with Wi-Fi and Bluetooth, e.g. Pi 3) | Main computer |
| HiFiBerry Amp2 | DAC and stereo amplifier that drives the radio's speakers |
| MCP3008 | 10-bit ADC for reading the potentiometers |
| 2× linear potentiometer (10 kΩ) | Station dial and volume knob |
| Push buttons / selector switch | Power, Internet radio, DAB, Bluetooth |
| An old radio | Case, speakers and knobs |

### Wiring (BCM numbering)

| Function | GPIO |
| --- | --- |
| Power button | 26 |
| Internet radio button | 13 |
| DAB button | 12 |
| Bluetooth button | 16 |
| Power LED *(defined, not used yet)* | 5 |
| Status LED *(defined, not used yet)* | 6 |
| MCP3008 CLK | 17 |
| MCP3008 MISO (DOUT) | 23 |
| MCP3008 MOSI (DIN) | 24 |
| MCP3008 CS | 25 |

The MCP3008 runs over software SPI. Its channels:

| MCP3008 channel | Potentiometer |
| --- | --- |
| CH0 | Volume |
| CH1 | Station |

The buttons use the Pi's internal pull-ups. Wire the Power, DAB and Bluetooth inputs so they are pulled to GND when active. The internet radio input counts as active when it is **high**.

The HiFiBerry Amp2 uses GPIO 2/3 (I²C) and 18–21 (I²S), so the pins above don't clash with it.

## Repository contents

| File | Description |
| --- | --- |
| `buttons_gpio_volume.py` | **Main script.** Reads the buttons and both potentiometers, switches between modes, sets the volume and runs the alarm. |
| `buttons_gpio.py` | Older version that uses interrupt callbacks and only has the station knob. |
| `radio_stations.m3u` | Playlist of internet radio stations. |
| `bl_start` | Turns on the Bluetooth adapter and makes it discoverable. |
| `bt_speaker/config.ini` | Configuration for bt-speaker. |
| `monitor-volume/` | Stand-alone volume-knob daemon and systemd unit, with its own [README](monitor-volume/README.md). |
| `connect_sound.wav`, `disconnect_sound.wav`, `radio_changing.mp3` | Sound effects. |

## Installation

### 1. Set up the HiFiBerry Amp2

In `/boot/config.txt` (`/boot/firmware/config.txt` on newer Raspberry Pi OS), turn off the onboard audio and load the HiFiBerry overlay:

```ini
#dtparam=audio=on
dtoverlay=hifiberry-dacplus
```

Reboot. Then check that the card shows up and find its mixer control name:

```sh
aplay -l
amixer scontrols
```

The scripts use the mixer control `Master`. If your card uses a different name (for example `Digital`), change `DEVICE_NAME` in `buttons_gpio_volume.py` and `mixer` in `bt_speaker/config.ini`.

### 2. Install the dependencies

```sh
sudo apt-get install mpd mpc mplayer alsa-utils python-rpi.gpio python-pip
sudo pip install adafruit-mcp3008
```

The scripts are written for **Python 2**.

### 3. Set up the internet radio

Copy the playlist into MPD's playlist directory and load it:

```sh
sudo cp radio_stations.m3u /var/lib/mpd/playlists/
mpc clear
mpc load radio_stations
```

The station knob maps the ADC value (0–1023) to a playlist position (`mpc play <n>`). To change stations, edit `radio_stations.m3u`. Positions follow the order of the file.

### 4. Set up the Bluetooth speaker

Install [bt-speaker](https://github.com/lukasjapan/bt-speaker) by following its instructions. Then copy the configuration and the start script:

```sh
sudo cp bt_speaker/config.ini /etc/bt_speaker/config.ini
cp bl_start /home/pi/bl_start
chmod +x /home/pi/bl_start
```

Turn off the `bluetooth` and `bt_speaker` services at boot. The main script starts them when Bluetooth mode is selected:

```sh
sudo systemctl disable bluetooth bt_speaker
```

### 5. Copy the scripts and sounds

The main script expects its files in `/home/pi`:

```sh
cp buttons_gpio_volume.py connect_sound.wav disconnect_sound.wav radio_changing.mp3 /home/pi/
```

### 6. Run it

```sh
sudo python /home/pi/buttons_gpio_volume.py
```

To start it at boot, you can add a systemd unit such as `/etc/systemd/system/retropi.service`:

```ini
[Unit]
Description=Retro radio controller
After=sound.target mpd.service

[Service]
ExecStart=/usr/bin/python /home/pi/buttons_gpio_volume.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```sh
sudo systemctl enable --now retropi
```

## Usage

| Mode | What happens |
| --- | --- |
| **Internet radio** | Stops Bluetooth, turns on Wi-Fi and starts `mpc play`. The station knob and the volume knob are both active. |
| **Bluetooth** | Stops MPD, turns off Wi-Fi, starts Bluetooth and bt-speaker, and makes the Pi discoverable. Pair your phone and play. The volume knob is active. |
| **DAB** | Stops the other sources. The volume knob is active. DAB reception is not implemented yet. |
| **Power** | Stops all playback (standby). At 06:55 the internet radio starts as an alarm. |

The volume is held between 15 % and 50 % (`VOLUME_MIN` / `VOLUME_MAX`). The alarm time is set by `alarm_time` in `buttons_gpio_volume.py`.

Pressing `Ctrl+C` stops the script cleanly: the volume goes to 0, MPD and Bluetooth stop, and the GPIO pins are reset.
