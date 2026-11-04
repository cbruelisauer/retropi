"""Front-panel controls: the mode selector and the two potentiometer knobs."""

import enum
import time
from collections.abc import Callable, Mapping


class Mode(enum.Enum):
    STANDBY = "standby"
    RADIO = "radio"
    BLUETOOTH = "bluetooth"


# Selector position -> mode. The DAB position behaves like Power.
POSITION_MODES = {
    "power": Mode.STANDBY,
    "radio": Mode.RADIO,
    "dab": Mode.STANDBY,
    "bluetooth": Mode.BLUETOOTH,
}


class Selector:
    """Debounces the selector's inputs into a Mode.

    A position counts once its input has been the only active one for
    ``settle_s``. Between positions, or with two inputs active, ``read()``
    returns None and the caller keeps its last mode.
    """

    def __init__(
        self,
        inputs: Mapping[str, Callable[[], bool]],
        settle_s: float,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._inputs = inputs
        self._settle_s = settle_s
        self._clock = clock
        self._candidate = None
        self._since = 0.0

    def read(self) -> Mode | None:
        now = self._clock()
        active = [name for name, is_active in self._inputs.items() if is_active()]
        candidate = active[0] if len(active) == 1 else None
        if candidate != self._candidate:
            self._candidate = candidate
            self._since = now
        if candidate is None or now - self._since < self._settle_s:
            return None
        return POSITION_MODES[candidate]


class Knob:
    """A potentiometer with hysteresis, mapped from raw ADC counts to a value."""

    def __init__(self, read_raw: Callable[[], int], mapping: Callable[[int], object], tolerance: int):
        self._read_raw = read_raw
        self._mapping = mapping
        self._tolerance = tolerance
        self._baseline = None
        self._value = None
        self.moving = False  # whether the last changed() saw the knob move past the tolerance

    def position(self):
        """Return the current value and make it the baseline for ``changed()``."""
        raw = self._read_raw()
        self._baseline = raw
        self._value = self._mapping(raw)
        return self._value

    def changed(self):
        """Return the new value if the knob moved past the tolerance, else None."""
        raw = self._read_raw()
        if self._baseline is not None and abs(raw - self._baseline) <= self._tolerance:
            self.moving = False
            return None
        self.moving = True
        self._baseline = raw
        value = self._mapping(raw)
        if value == self._value:
            return None
        self._value = value
        return value


ADC_MAX = 1023


class _Gap:
    def __repr__(self):
        return "GAP"


GAP = _Gap()  # the station dial is between two stations


def station_index(raw: int, count: int, gap: float = 0.0):
    """Split the dial into ``count`` equal bands; returns a 0-based index.

    ``gap`` is the share of a band, centred on each border between two
    stations, that belongs to no station: there it returns ``GAP``. The two
    ends of the dial have no gap.
    """
    raw = max(0, min(raw, ADC_MAX))
    index = min(raw * count // (ADC_MAX + 1), count - 1)
    width = (ADC_MAX + 1) / count
    half_gap = gap * width / 2
    offset = raw - index * width
    if (index > 0 and offset < half_gap) or (index < count - 1 and offset >= width - half_gap):
        return GAP
    return index


def volume_db(raw: int, min_db: float, max_db: float) -> float:
    """Map the knob's full travel linearly in dB onto min_db..max_db."""
    raw = max(0, min(raw, ADC_MAX))
    return round(min_db + (max_db - min_db) * raw / ADC_MAX, 1)


def open_hardware(cfg, station_count: int, station_gap: float = 0.0):
    """Create the selector and knobs on the real GPIO pins and MCP3008."""
    from gpiozero import MCP3008, DigitalInputDevice

    pins = cfg.pins
    # All inputs use the internal pull-up. Power, DAB and Bluetooth pull
    # their input to GND when selected; the radio input reads high.
    power, radio, dab, bluetooth = (
        DigitalInputDevice(pin, pull_up=True) for pin in (pins.power, pins.radio, pins.dab, pins.bluetooth)
    )
    selector = Selector(
        {
            "power": lambda: power.is_active,
            "radio": lambda: not radio.is_active,
            "dab": lambda: dab.is_active,
            "bluetooth": lambda: bluetooth.is_active,
        },
        settle_s=pins.selector_settle_ms / 1000,
    )

    adc = cfg.adc
    spi = {"clock_pin": adc.clk, "mosi_pin": adc.mosi, "miso_pin": adc.miso, "select_pin": adc.cs}
    volume_adc = MCP3008(channel=adc.volume_channel, **spi)
    station_adc = MCP3008(channel=adc.station_channel, **spi)
    audio = cfg.audio
    volume_knob = Knob(
        lambda: volume_adc.raw_value,
        lambda raw: volume_db(raw, audio.volume_min_db, audio.volume_max_db),
        adc.volume_tolerance,
    )
    station_knob = Knob(
        lambda: station_adc.raw_value,
        lambda raw: station_index(raw, station_count, station_gap),
        adc.station_tolerance,
    )
    return selector, volume_knob, station_knob
