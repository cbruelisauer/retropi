import pytest

from retropi.radio import Radio


class LostConnection(Exception):
    pass


class CommandError(Exception):
    pass


class FakeMPDClient:
    def __init__(self):
        self.connected = False
        self.connects = 0
        self.drop_next = False
        self.state = "stop"
        self.queue = []
        self.played = []

    def connect(self, host, port):
        self.connected = True
        self.connects += 1

    def disconnect(self):
        self.connected = False

    def _check(self):
        assert self.connected
        if self.drop_next:
            self.drop_next = False
            raise LostConnection("Connection lost while reading line")

    def clear(self):
        self._check()
        self.queue = []

    def load(self, name):
        self._check()
        if name != "stations":
            raise CommandError("No such playlist")
        self.queue = [f"http://station/{i}" for i in range(10)]

    def playlistinfo(self):
        self._check()
        return [{"file": f} for f in self.queue]

    def clearerror(self):
        self._check()

    def play(self, index):
        self._check()
        self.played.append(index)
        self.state = "play"

    def stop(self):
        self._check()
        self.state = "stop"

    def status(self):
        self._check()
        return {"state": self.state}


@pytest.fixture
def client():
    return FakeMPDClient()


@pytest.fixture
def radio(client):
    return Radio(
        client, "localhost", 6600, "stations", (LostConnection, OSError), (LostConnection, CommandError, OSError)
    )


def test_load_returns_station_count(radio):
    assert radio.load() == 10


def test_load_missing_playlist_raises(client):
    radio = Radio(client, "localhost", 6600, "nope", (LostConnection,), (LostConnection, CommandError))
    with pytest.raises(CommandError):
        radio.load()


def test_play_uses_zero_based_index(radio, client):
    radio.load()
    assert radio.play(0)
    assert client.played == [0]


def test_dropped_connection_is_reopened_and_retried_once(radio, client):
    radio.load()
    client.drop_next = True
    assert radio.play(4)
    assert client.connects == 2
    assert client.played == [4]


def test_connection_down_twice_fails_without_raising(radio, client):
    radio.load()

    def always_lost(host, port):
        raise ConnectionRefusedError("MPD not running")

    client.connect = always_lost
    client.drop_next = True
    assert not radio.play(1)
    radio.stop()  # logs, does not raise


def test_play_reports_failed_stream(radio, client):
    radio.load()
    client.status = lambda: {"state": "stop", "error": "Failed to open stream"}
    assert not radio.play(2)


def test_playing_sees_stream_that_failed_after_play(radio, client):
    radio.load()
    assert radio.play(2)
    client.status = lambda: {"state": "stop", "error": "Failed to open stream"}
    assert not radio.playing()


def test_playing_false_when_mpd_unreachable(radio, client):
    radio.load()

    def always_lost(host, port):
        raise ConnectionRefusedError("MPD not running")

    client.connect = always_lost
    client.drop_next = True
    assert not radio.playing()
