import itertools

import pytest

from retropi.controls import Knob, Mode, Selector, station_index, volume_db


def test_station_ends_of_dial():
    assert station_index(0, 10) == 0
    assert station_index(1023, 10) == 9


def test_station_equal_bands():
    counts = [0] * 10
    for raw in range(1024):
        counts[station_index(raw, 10)] += 1
    assert set(counts) <= {102, 103}


def test_volume_ends_and_linear_in_db():
    assert volume_db(0, -45.0, -10.0) == -45.0
    assert volume_db(1023, -45.0, -10.0) == -10.0
    assert volume_db(512, -45.0, -10.0) == pytest.approx(-27.5, abs=0.1)
    steps = [volume_db(raw, -45.0, -10.0) for raw in range(0, 1024, 93)]
    diffs = {round(b - a, 1) for a, b in itertools.pairwise(steps)}
    assert max(diffs) - min(diffs) <= 0.2


class FakeAdc:
    def __init__(self, raw=0):
        self.raw = raw

    def __call__(self):
        return self.raw


def test_knob_jitter_below_tolerance_returns_none():
    adc = FakeAdc(500)
    knob = Knob(adc, lambda raw: raw, tolerance=5)
    assert knob.position() == 500
    for raw in (495, 505, 503, 497):
        adc.raw = raw
        assert knob.changed() is None
    adc.raw = 506
    assert knob.changed() == 506


def test_knob_first_changed_without_position_reports_value():
    knob = Knob(FakeAdc(300), lambda raw: raw, tolerance=5)
    assert knob.changed() == 300


def test_knob_same_mapped_value_returns_none():
    adc = FakeAdc(0)
    knob = Knob(adc, lambda raw: station_index(raw, 10), tolerance=7)
    knob.position()
    adc.raw = 50  # past the tolerance, still in the first band
    assert knob.changed() is None
    adc.raw = 150
    assert knob.changed() == 1


class FakeInputs(dict):
    def set(self, *active):
        for name in self:
            self[name] = name in active

    def callables(self):
        return {name: (lambda n=name: self[n]) for name in self}


@pytest.fixture
def inputs():
    return FakeInputs(power=False, radio=False, dab=False, bluetooth=False)


def test_selector_needs_settle_time(inputs, clock):
    selector = Selector(inputs.callables(), settle_s=0.1, clock=clock)
    inputs.set("radio")
    assert selector.read() is None
    clock.advance(0.05)
    assert selector.read() is None
    clock.advance(0.05)
    assert selector.read() is Mode.RADIO


def test_selector_no_input_or_two_inputs_keep_last_mode(inputs, clock):
    selector = Selector(inputs.callables(), settle_s=0.1, clock=clock)
    inputs.set("power")
    selector.read()
    clock.advance(0.1)
    assert selector.read() is Mode.STANDBY
    inputs.set()
    clock.advance(1)
    assert selector.read() is None
    inputs.set("power", "radio")
    clock.advance(1)
    assert selector.read() is None


def test_selector_flapping_resets_settle_time(inputs, clock):
    selector = Selector(inputs.callables(), settle_s=0.1, clock=clock)
    for _ in range(5):
        inputs.set("radio")
        selector.read()
        clock.advance(0.06)
        inputs.set("bluetooth")
        assert selector.read() is None
        clock.advance(0.06)
    assert selector.read() is None
    clock.advance(0.1)
    assert selector.read() is Mode.BLUETOOTH


def test_dab_is_standby(inputs, clock):
    selector = Selector(inputs.callables(), settle_s=0.1, clock=clock)
    inputs.set("dab")
    selector.read()
    clock.advance(0.1)
    assert selector.read() is Mode.STANDBY
