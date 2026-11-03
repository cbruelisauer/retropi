"""retropi: front-panel controller for the retro internet radio."""

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

from . import config, sounds
from .controls import Mode

log = logging.getLogger("retropi")

LOOP_S = 0.05


class Controller:
    """The mode state machine and main loop.

    Enter/exit actions run only when the selector settles on a new mode.
    Everything it drives is passed in, so tests can use fakes.
    """

    def __init__(
        self,
        selector,
        volume_knob,
        station_knob,
        mixer,
        radio,
        bt,
        wifi,
        *,
        disable_wifi: bool,
        wifi_connect_timeout_s: float,
        play_retry_s: float,
        clock=time.monotonic,
    ):
        self.selector = selector
        self.volume_knob = volume_knob
        self.station_knob = station_knob
        self.mixer = mixer
        self.radio = radio
        self.bt = bt
        self.wifi = wifi
        self.disable_wifi = disable_wifi
        self.wifi_connect_timeout_s = wifi_connect_timeout_s
        self.play_retry_s = play_retry_s
        self.clock = clock
        self.mode = None
        self.pending_since = None  # when radio mode was entered, until a stream plays
        self.next_try = 0.0
        self.running = True

    def start(self, startup_volume_db: float, startup_sound: str, play_sound=sounds.play) -> None:
        # Known state, even after a crash in Bluetooth mode.
        self.wifi.on()
        self.bt.disable()
        self.radio.stop()
        self.mixer.set_db(startup_volume_db)
        play_sound(startup_sound, wait=True)

    def run(self, sleep=time.sleep) -> None:
        try:
            while self.running:
                self.step()
                sleep(LOOP_S)
        finally:
            self.shutdown()

    def stop(self, signum=None, frame=None) -> None:
        self.running = False

    def step(self) -> None:
        now = self.clock()
        new = self.selector.read()
        if new is not None and new != self.mode:
            log.info("mode %s -> %s", self.mode.value if self.mode else "none", new.value)
            self._exit(self.mode)
            self._enter(new, now)
            self.mode = new
            if new is not Mode.STANDBY:
                self.mixer.set_db(self.volume_knob.position())  # apply the knob now, not on its next move

        if self.mode is Mode.RADIO and self.pending_since is not None and now >= self.next_try:
            connected = self.wifi.connected()
            if connected or now - self.pending_since > self.wifi_connect_timeout_s:
                if not connected:
                    log.info("Wi-Fi not connected after %.0f s, trying anyway", self.wifi_connect_timeout_s)
                # position() also resets the knob's baseline, so the next
                # changed() does not restart the stream that is playing.
                if self.radio.play(self.station_knob.position()):
                    self.pending_since = None
                else:
                    log.warning("no stream yet, retrying in %.0f s", self.play_retry_s)
                    self.next_try = now + self.play_retry_s

        if self.mode is not None and self.mode is not Mode.STANDBY:
            v = self.volume_knob.changed()
            if v is not None:
                self.mixer.set_db(v)

        if self.mode is Mode.RADIO and self.pending_since is None:
            s = self.station_knob.changed()
            if s is not None:
                self.radio.play(s)

        self.bt.tick()

    def shutdown(self) -> None:
        log.info("shutting down")
        self.mixer.mute()
        self.radio.stop()
        self.bt.disable()
        self.wifi.on()

    def _exit(self, mode) -> None:
        if mode is Mode.RADIO:
            self.radio.stop()
            self.pending_since = None
        elif mode is Mode.BLUETOOTH:
            self.bt.disable()
            if self.disable_wifi:
                self.wifi.on()

    def _enter(self, mode, now: float) -> None:
        if mode is Mode.RADIO:
            self.pending_since = now
            self.next_try = now
        elif mode is Mode.BLUETOOTH:
            if self.disable_wifi:
                self.wifi.off()
            self.bt.enable()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="retropi", description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("/etc/retropi/config.toml"))
    parser.add_argument("--debug", action="store_true", help="log debug messages")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        cfg = config.load(args.config)
    except config.ConfigError as e:
        print(f"retropi: config error: {e}", file=sys.stderr)
        return 2

    from .bluetooth import open_bluetooth
    from .controls import open_hardware
    from .mixer import open_mixer
    from .network import Wifi
    from .radio import open_radio

    radio = open_radio(cfg)
    station_count = radio.load()
    selector, volume_knob, station_knob = open_hardware(cfg, station_count)
    bt = open_bluetooth(cfg, sounds.play)
    controller = Controller(
        selector,
        volume_knob,
        station_knob,
        open_mixer(cfg),
        radio,
        bt,
        Wifi(),
        disable_wifi=cfg.bluetooth.disable_wifi,
        wifi_connect_timeout_s=cfg.network.wifi_connect_timeout_s,
        play_retry_s=cfg.network.play_retry_s,
    )
    signal.signal(signal.SIGTERM, controller.stop)
    signal.signal(signal.SIGINT, controller.stop)
    try:
        controller.start(cfg.audio.startup_volume_db, cfg.audio.startup_sound)
        controller.run()
    finally:
        bt.close()
        radio.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
