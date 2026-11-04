"""retropi: front-panel controller for the retro internet radio."""

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

from . import config, sounds
from .controls import GAP, Mode
from .static import NoStatic

log = logging.getLogger("retropi")

LOOP_S = 0.05
WIFI_POLL_S = 1.0  # how often radio mode asks nmcli whether Wi-Fi is up
STREAM_POLL_S = 0.5  # how often a starting stream is checked, to end the static once it plays


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
        static=None,
        tune_settle_s: float = 0.0,
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
        self.static = static if static is not None else NoStatic()
        self.tune_settle_s = tune_settle_s
        self.clock = clock
        self.mode = None
        self.pending_since = None  # when radio mode was entered, until Wi-Fi is up or timed out
        self.next_try = 0.0  # next Wi-Fi poll, or next check that the stream plays
        self.station = None  # the station the dial points at, or GAP
        self.tune_at = None  # when the dial has rested long enough to tune in
        self.play_started = 0.0
        self.starting = False  # a stream was started and is not audible yet
        self.static_on = False
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

        if self.mode is Mode.RADIO:
            self._radio_step(now)

        if self.mode is not None and self.mode is not Mode.STANDBY:
            v = self.volume_knob.changed()
            if v is not None:
                self.mixer.set_db(v)

        self.bt.tick()

    def _radio_step(self, now: float) -> None:
        if self.pending_since is not None:
            if now < self.next_try:
                return
            connected = self.wifi.connected()
            if connected or now - self.pending_since > self.wifi_connect_timeout_s:
                if not connected:
                    log.info("Wi-Fi not connected after %.0f s, trying anyway", self.wifi_connect_timeout_s)
                self.pending_since = None
                # position() also resets the knob's baseline, so the next
                # changed() does not restart the stream that is playing.
                self._tune(self.station_knob.position(), now, settle=False)
            else:
                self.next_try = now + WIFI_POLL_S
            return

        s = self.station_knob.changed()
        if s is not None:
            self._tune(s, now, settle=True)
        elif self.tune_at is not None and self.station_knob.moving:
            # Still turning inside the band: the dial has not come to rest yet.
            self.tune_at = now + self.tune_settle_s
        if self.tune_at is not None:
            if now >= self.tune_at:
                self.tune_at = None
                self._play(self.station, now)
            return
        if self.station is GAP or now < self.next_try:
            return

        if self.starting:
            if self.radio.audible():
                self.starting = False
                self._set_static(False)
                self.next_try = now + self.play_retry_s
            elif now - self.play_started >= self.play_retry_s and not self.radio.playing():
                log.warning("no stream, retrying")
                self._play(self.station, now)
            else:
                self.next_try = now + STREAM_POLL_S
        elif not self.radio.playing():
            log.warning("no stream, retrying")
            self._play(self.station, now)
        else:
            self.next_try = now + self.play_retry_s

    def _tune(self, station, now: float, settle: bool) -> None:
        """Point the radio at a station, or at the static between two."""
        was_gap, self.station = self.station is GAP, station
        if station is GAP or (settle and self.tune_settle_s > 0):
            # Static while the dial moves; the stream starts once it rests.
            if not was_gap:
                self.radio.stop()
            self.starting = False
            self._set_static(True)
            self.tune_at = None if station is GAP else now + self.tune_settle_s
        else:
            self.tune_at = None
            self._play(station, now)

    def _play(self, station: int, now: float) -> None:
        # The static plays until the stream is audible. MPD reports a stream
        # that fails to open only after play(), so it is restarted if it is
        # still not playing after play_retry_s.
        self.radio.play(station)
        self.play_started = now
        self.starting = True
        self._set_static(True)
        self.next_try = now + STREAM_POLL_S

    def _set_static(self, on: bool) -> None:
        if on != self.static_on:
            self.static_on = on
            if on:
                self.static.on()
            else:
                self.static.off()

    def _stop_static(self) -> None:
        self.static_on = False
        self.static.stop()

    def shutdown(self) -> None:
        log.info("shutting down")
        self._stop_static()
        self.mixer.mute()
        self.radio.stop()
        self.bt.disable()
        self.wifi.on()

    def _exit(self, mode) -> None:
        if mode is Mode.RADIO:
            self._stop_static()
            self.radio.stop()
            self.pending_since = None
            self.tune_at = None
            self.starting = False
        elif mode is Mode.BLUETOOTH:
            self.bt.disable()
            if self.disable_wifi:
                self.wifi.on()

    def _enter(self, mode, now: float) -> None:
        if mode is Mode.RADIO:
            self.pending_since = now
            self.next_try = now
            self._set_static(True)  # warming up until Wi-Fi and the stream are there
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
    from .static import open_static

    radio = open_radio(cfg)
    station_count = radio.load()
    tuning = cfg.tuning
    selector, volume_knob, station_knob = open_hardware(
        cfg, station_count, tuning.station_gap if tuning.enabled else 0.0
    )
    static = open_static(cfg) if tuning.enabled else NoStatic()
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
        static=static,
        tune_settle_s=tuning.tune_settle_ms / 1000 if tuning.enabled else 0.0,
    )
    signal.signal(signal.SIGTERM, controller.stop)
    signal.signal(signal.SIGINT, controller.stop)
    try:
        controller.start(cfg.audio.startup_volume_db, cfg.audio.startup_sound)
        controller.run()
    finally:
        static.close()
        bt.close()
        radio.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
