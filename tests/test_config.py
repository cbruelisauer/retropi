import re
import tomllib
from pathlib import Path

import pytest

from retropi import config

REPO_CONFIG = Path(__file__).parent.parent / "config.toml"


def write(tmp_path, text):
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def repo_config_with(tmp_path, old, new):
    text = REPO_CONFIG.read_text(encoding="utf-8")
    assert old in text
    return write(tmp_path, text.replace(old, new, 1))


def test_repo_config_loads():
    cfg = config.load(REPO_CONFIG)
    assert cfg.pins.radio == 13
    assert cfg.adc.station_channel == 1
    assert cfg.audio.mixer == "Master"
    assert cfg.network.play_retry_s == 5.0
    assert isinstance(cfg.network.play_retry_s, float)
    assert cfg.bluetooth.disable_wifi is True


def test_config_is_frozen():
    cfg = config.load(REPO_CONFIG)
    with pytest.raises(AttributeError):
        cfg.pins.radio = 1


def test_missing_key(tmp_path):
    path = repo_config_with(tmp_path, "pairing_window_s = 120\n", "")
    with pytest.raises(config.ConfigError, match="missing config key: bluetooth.pairing_window_s"):
        config.load(path)


def test_missing_section(tmp_path):
    text = re.sub(r"\[leds\][^\[]*", "", REPO_CONFIG.read_text(encoding="utf-8"))
    assert "leds" not in tomllib.loads(text)
    with pytest.raises(config.ConfigError, match="missing config key: leds"):
        config.load(write(tmp_path, text))


def test_wrong_type(tmp_path):
    path = repo_config_with(tmp_path, "power = 26", 'power = "26"')
    with pytest.raises(config.ConfigError, match=r"pins.power must be int, got '26'"):
        config.load(path)


def test_bool_is_not_a_number(tmp_path):
    path = repo_config_with(tmp_path, "port = 6600", "port = true")
    with pytest.raises(config.ConfigError, match="mpd.port must be int"):
        config.load(path)


def test_unknown_key(tmp_path):
    path = repo_config_with(tmp_path, "[mpd]\n", "[mpd]\nhots = 1\n")
    with pytest.raises(config.ConfigError, match="unknown config key.*mpd.hots"):
        config.load(path)


def test_volume_range_must_be_ordered(tmp_path):
    path = repo_config_with(tmp_path, "volume_max_db = -38.0", "volume_max_db = -90.0")
    with pytest.raises(config.ConfigError, match="volume_min_db must be below"):
        config.load(path)


def test_bad_toml(tmp_path):
    with pytest.raises(config.ConfigError, match="config.toml"):
        config.load(write(tmp_path, "[pins\n"))


def test_missing_file(tmp_path):
    with pytest.raises(config.ConfigError, match="cannot read"):
        config.load(tmp_path / "nope.toml")


def test_main_reports_config_error(tmp_path, capsys):
    from retropi.__main__ import main

    assert main(["--config", str(tmp_path / "nope.toml")]) == 2
    assert "config error" in capsys.readouterr().err
