import signal

import pytest

from retropi.__main__ import Controller
from retropi.controls import Mode


class Calls(list):
    """Shared, ordered log of what the controller did."""


class FakeSelector:
    def __init__(self):
        self.mode = None

    def read(self):
        return self.mode


class FakeKnob:
    def __init__(self, value):
        self.value = value
        self.moved = None

    def position(self):
        self.moved = None
        return self.value

    def changed(self):
        moved, self.moved = self.moved, None
        return moved

    def turn(self, value):
        self.value = self.moved = value


class FakeMixer:
    def __init__(self, calls):
        self.calls = calls
        self.db = None

    def set_db(self, db):
        self.db = db
        self.calls.append(("mixer.set_db", db))

    def mute(self):
        self.db = "muted"
        self.calls.append(("mixer.mute",))


class FakeRadio:
    def __init__(self, calls):
        self.calls = calls
        self.streams_up = True  # whether a stream started now would play
        self.is_playing = False

    def play(self, index):
        self.calls.append(("radio.play", index))
        self.is_playing = self.streams_up
        return self.streams_up

    def playing(self):
        return self.is_playing

    def stop(self):
        self.calls.append(("radio.stop",))
        self.is_playing = False


class FakeBluetooth:
    def __init__(self, calls):
        self.calls = calls

    def enable(self):
        self.calls.append(("bt.enable",))

    def disable(self):
        self.calls.append(("bt.disable",))

    def tick(self):
        pass


class FakeWifi:
    def __init__(self, calls):
        self.calls = calls
        self.is_connected = True
        self.polls = 0

    def on(self):
        self.calls.append(("wifi.on",))

    def off(self):
        self.calls.append(("wifi.off",))

    def connected(self):
        self.polls += 1
        return self.is_connected


@pytest.fixture
def calls():
    return Calls()


@pytest.fixture
def ctl(calls, clock):
    return Controller(
        FakeSelector(),
        FakeKnob(-20.0),
        FakeKnob(3),
        FakeMixer(calls),
        FakeRadio(calls),
        FakeBluetooth(calls),
        FakeWifi(calls),
        disable_wifi=True,
        wifi_connect_timeout_s=30,
        play_retry_s=5,
        clock=clock,
    )


def switch(ctl, calls, mode):
    ctl.selector.mode = mode
    calls.clear()
    ctl.step()
    return [c for c in calls if c[0] != "mixer.set_db"]


EXPECTED = {
    # (from, to): exit actions + enter actions (+ radio start, which runs in the same step)
    (Mode.STANDBY, Mode.RADIO): [("radio.play", 3)],
    (Mode.STANDBY, Mode.BLUETOOTH): [("wifi.off",), ("bt.enable",)],
    (Mode.RADIO, Mode.STANDBY): [("radio.stop",)],
    (Mode.RADIO, Mode.BLUETOOTH): [("radio.stop",), ("wifi.off",), ("bt.enable",)],
    (Mode.BLUETOOTH, Mode.STANDBY): [("bt.disable",), ("wifi.on",)],
    (Mode.BLUETOOTH, Mode.RADIO): [("bt.disable",), ("wifi.on",), ("radio.play", 3)],
}


@pytest.mark.parametrize(("old", "new"), EXPECTED)
def test_mode_transition_actions_run_once(ctl, calls, old, new):
    switch(ctl, calls, old)
    assert switch(ctl, calls, new) == EXPECTED[old, new]
    # Staying in the mode repeats nothing.
    assert switch(ctl, calls, new) == []


def test_unsettled_selector_keeps_mode(ctl, calls):
    switch(ctl, calls, Mode.RADIO)
    assert switch(ctl, calls, None) == []
    assert ctl.mode is Mode.RADIO


@pytest.mark.parametrize("mode", [Mode.RADIO, Mode.BLUETOOTH])
def test_entering_mode_applies_volume_knob(ctl, calls, mode):
    switch(ctl, calls, Mode.STANDBY)
    ctl.volume_knob.value = -12.5
    switch(ctl, calls, mode)
    assert ctl.mixer.db == -12.5


def test_entering_radio_does_not_restart_stream(ctl, calls):
    ctl.station_knob.turn(5)  # moved while in standby
    switch(ctl, calls, Mode.STANDBY)
    assert switch(ctl, calls, Mode.RADIO) == [("radio.play", 5)]
    assert ctl.station_knob.changed() is None
    calls.clear()
    ctl.step()
    assert calls == []


def test_station_knob_changes_station(ctl, calls):
    switch(ctl, calls, Mode.RADIO)
    ctl.station_knob.turn(7)
    calls.clear()
    ctl.step()
    assert calls == [("radio.play", 7)]


def test_volume_knob_ignored_in_standby(ctl, calls):
    switch(ctl, calls, Mode.STANDBY)
    ctl.volume_knob.turn(-11.0)
    calls.clear()
    ctl.step()
    assert calls == []


def test_radio_waits_for_wifi_then_plays(ctl, calls, clock):
    switch(ctl, calls, Mode.BLUETOOTH)
    ctl.wifi.is_connected = False
    assert switch(ctl, calls, Mode.RADIO) == [("bt.disable",), ("wifi.on",)]
    clock.advance(3)
    ctl.step()
    assert ("radio.play", 3) not in calls
    ctl.wifi.is_connected = True
    clock.advance(1)
    ctl.step()
    assert calls[-1] == ("radio.play", 3)


def test_wifi_polled_once_a_second_while_waiting(ctl, calls, clock):
    ctl.wifi.is_connected = False
    switch(ctl, calls, Mode.RADIO)
    for _ in range(200):  # 10 s of 50 ms loop iterations
        clock.advance(0.05)
        ctl.step()
    assert 10 <= ctl.wifi.polls <= 11


def test_stream_that_fails_after_play_is_restarted(ctl, calls, clock):
    switch(ctl, calls, Mode.RADIO)
    assert calls.count(("radio.play", 3)) == 1
    ctl.radio.is_playing = False  # MPD failed to open the stream after play()
    clock.advance(4)
    ctl.step()
    assert calls.count(("radio.play", 3)) == 1
    clock.advance(1)
    ctl.step()
    assert calls.count(("radio.play", 3)) == 2


def test_failed_station_change_is_retried(ctl, calls, clock):
    switch(ctl, calls, Mode.RADIO)
    ctl.radio.streams_up = False
    ctl.station_knob.turn(7)
    clock.advance(1)
    ctl.step()
    assert calls.count(("radio.play", 7)) == 1
    ctl.radio.streams_up = True
    clock.advance(5)
    ctl.step()
    assert calls.count(("radio.play", 7)) == 2
    clock.advance(10)
    ctl.step()
    assert calls.count(("radio.play", 7)) == 2


def test_radio_tries_after_timeout_and_retries(ctl, calls, clock):
    ctl.wifi.is_connected = False
    ctl.radio.streams_up = False
    switch(ctl, calls, Mode.RADIO)
    assert ("radio.play", 3) not in calls
    clock.advance(31)
    ctl.step()
    assert calls.count(("radio.play", 3)) == 1
    clock.advance(4)
    ctl.step()
    assert calls.count(("radio.play", 3)) == 1
    clock.advance(1)
    ctl.radio.streams_up = True
    ctl.step()
    assert calls.count(("radio.play", 3)) == 2
    clock.advance(10)
    ctl.step()
    assert calls.count(("radio.play", 3)) == 2


def test_start_sets_known_state_and_plays_startup_sound(ctl, calls):
    played = []
    ctl.start(-30.0, "sounds/connect.wav", play_sound=lambda path, wait: played.append((path, wait)))
    assert calls == [("wifi.on",), ("bt.disable",), ("radio.stop",), ("mixer.set_db", -30.0)]
    assert played == [("sounds/connect.wav", True)]


def test_sigterm_in_bluetooth_mode_shuts_down(ctl, calls):
    switch(ctl, calls, Mode.BLUETOOTH)
    old = signal.signal(signal.SIGTERM, ctl.stop)
    try:
        calls.clear()
        ctl.run(sleep=lambda s: signal.raise_signal(signal.SIGTERM))
    finally:
        signal.signal(signal.SIGTERM, old)
    assert ctl.mixer.db == "muted"
    assert calls[-4:] == [("mixer.mute",), ("radio.stop",), ("bt.disable",), ("wifi.on",)]


def test_crash_still_shuts_down(ctl, calls):
    switch(ctl, calls, Mode.BLUETOOTH)
    ctl.selector.read = lambda: 1 / 0
    calls.clear()
    with pytest.raises(ZeroDivisionError):
        ctl.run(sleep=lambda s: None)
    assert calls == [("mixer.mute",), ("radio.stop",), ("bt.disable",), ("wifi.on",)]
