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
class Config:
    pins: Pins
    leds: Leds
    adc: Adc
    audio: Audio
    mpd: Mpd
    network: Network
    bluetooth: Bluetooth


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
    return cfg


def _build(cls, data, prefix):
    if not isinstance(data, dict):
        raise ConfigError(f"[{prefix}] must be a table")
    fields = {f.name: f.type for f in dataclasses.fields(cls)}
    unknown = data.keys() - fields.keys()
    if unknown:
        names = ", ".join(sorted(_key(prefix, k) for k in unknown))
        raise ConfigError(f"unknown config key(s): {names}")
    values = {}
    for name, typ in fields.items():
        key = _key(prefix, name)
        if name not in data:
            raise ConfigError(f"missing config key: {key}")
        values[name] = _check(typ, data[name], key)
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
