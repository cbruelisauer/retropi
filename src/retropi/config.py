"""Load config.toml into frozen dataclasses, failing early on bad keys."""

import dataclasses
import tomllib
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Pins:
    power: int
    radio: int
    dab: int
    bluetooth: int
    selector_settle_ms: int


@dataclass(frozen=True)
class Leds:
    power: int
    status: int


@dataclass(frozen=True)
class Adc:
    clk: int
    miso: int
    mosi: int
    cs: int
    volume_channel: int
    station_channel: int
    volume_tolerance: int
    station_tolerance: int


@dataclass(frozen=True)
class Audio:
    card: str
    mixer: str
    volume_min_db: float
    volume_max_db: float
    startup_volume_db: float
    startup_sound: str
    connect_sound: str
    disconnect_sound: str


@dataclass(frozen=True)
class Mpd:
    host: str
    port: int
    playlist: str


@dataclass(frozen=True)
class Network:
    wifi_connect_timeout_s: float
    play_retry_s: float


@dataclass(frozen=True)
class Bluetooth:
    name: str
    disable_wifi: bool
    pairing_window_s: float


@dataclass(frozen=True)
class Tuning:
    """Static between stations. Optional in config.toml; these are the defaults."""

    enabled: bool = True
    station_gap: float = 0.15  # share of each band, around every border, that only plays static
    tune_settle_ms: int = 300  # how long the dial must rest on a station before it tunes in
    static_level_db: float = -6.0  # static level against the clip's own level
    static_fade_ms: int = 300
    static_sound: str = "sounds/static.wav"


@dataclass(frozen=True)
class Config:
    pins: Pins
    leds: Leds
    adc: Adc
    audio: Audio
    mpd: Mpd
    network: Network
    bluetooth: Bluetooth
    tuning: Tuning = dataclasses.field(default_factory=Tuning)


SOUND_KEYS = ("startup_sound", "connect_sound", "disconnect_sound")


def load(path: Path) -> Config:
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except OSError as e:
        raise ConfigError(f"cannot read {path}: {e.strerror}") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e
    cfg = _build(Config, data, "")
    if cfg.audio.volume_min_db >= cfg.audio.volume_max_db:
        raise ConfigError("audio.volume_min_db must be below audio.volume_max_db")
    if not 0.0 <= cfg.tuning.station_gap < 1.0:
        raise ConfigError("tuning.station_gap must be at least 0 and below 1")
    # lgpio changes the working directory to LG_WD when it opens the pins, so
    # relative sound paths are made absolute now, against the start directory.
    audio = dataclasses.replace(
        cfg.audio,
        **{name: str(Path.cwd() / getattr(cfg.audio, name)) for name in SOUND_KEYS},
    )
    tuning = dataclasses.replace(cfg.tuning, static_sound=str(Path.cwd() / cfg.tuning.static_sound))
    return dataclasses.replace(cfg, audio=audio, tuning=tuning)


def _build(cls, data, prefix):
    if not isinstance(data, dict):
        raise ConfigError(f"[{prefix}] must be a table")
    fields = {f.name: f for f in dataclasses.fields(cls)}
    unknown = data.keys() - fields.keys()
    if unknown:
        names = ", ".join(sorted(_key(prefix, k) for k in unknown))
        raise ConfigError(f"unknown config key(s): {names}")
    values = {}
    for name, field in fields.items():
        key = _key(prefix, name)
        if name in data:
            values[name] = _check(field.type, data[name], key)
        elif field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING:
            raise ConfigError(f"missing config key: {key}")
    return cls(**values)


def _check(typ, value, key):
    if dataclasses.is_dataclass(typ):
        return _build(typ, value, key)
    # bool is a subclass of int, so it must not pass as a number.
    if typ is float and isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, typ) and (typ is bool or not isinstance(value, bool)):
        return value
    raise ConfigError(f"{key} must be {typ.__name__}, got {value!r}")


def _key(prefix, name):
    return f"{prefix}.{name}" if prefix else name
