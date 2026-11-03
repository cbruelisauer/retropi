import pytest

from retropi.bluetooth import Bluetooth, BluetoothError


class FakeBackend:
    """Stands in for BlueZ: tracks adapter state and phone connections."""

    def __init__(self):
        self.powered = False
        self.visible = False
        self.phone_connected = False
        self.reconnects = 0
        self.fail = False

    def attach(self, on_connected, may_pair):
        self.on_connected = on_connected
        self.may_pair = may_pair

    def power(self, on):
        if self.fail:
            raise BluetoothError("bluetoothd not running")
        self.powered = on
        if not on:
            self.visible = False
            self.disconnect()

    def set_visible(self, on):
        self.visible = on

    def connected(self):
        return self.phone_connected

    def reconnect_trusted(self):
        self.reconnects += 1

    def close(self):
        pass

    # Phone-side events
    def connect(self, trusted):
        if not self.powered or not (trusted or self.may_pair()):
            return False
        self.phone_connected = True
        self.on_connected(True)
        return True

    def disconnect(self):
        if self.phone_connected:
            self.phone_connected = False
            self.on_connected(False)


@pytest.fixture
def backend():
    return FakeBackend()


@pytest.fixture
def played():
    return []


@pytest.fixture
def bt(backend, played, clock):
    return Bluetooth(backend, 120, played.append, "connect.wav", "disconnect.wav", clock=clock)


def test_adapter_off_until_enabled(bt, backend):
    bt.disable()
    assert not backend.powered
    assert not backend.connect(trusted=True)


def test_enable_powers_and_opens_pairing(bt, backend):
    bt.enable()
    assert backend.powered and backend.visible
    assert bt.pairing_open()
    assert backend.reconnects == 1


def test_pairing_window_closes(bt, backend, clock):
    bt.enable()
    clock.advance(119)
    bt.tick()
    assert backend.visible and bt.pairing_open()
    clock.advance(1)
    bt.tick()
    assert not backend.visible
    assert not bt.pairing_open()
    assert not backend.connect(trusted=False)
    assert backend.connect(trusted=True)


def test_window_reopens_on_next_entry(bt, backend, clock):
    bt.enable()
    clock.advance(200)
    bt.tick()
    bt.disable()
    bt.enable()
    assert backend.visible and bt.pairing_open()


def test_connect_and_disconnect_sounds(bt, backend, played):
    bt.enable()
    backend.connect(trusted=False)
    backend.disconnect()
    assert played == ["connect.wav", "disconnect.wav"]


def test_leaving_mode_plays_disconnect_once(bt, backend, played):
    bt.enable()
    backend.connect(trusted=True)
    played.clear()
    bt.disable()
    assert played == ["disconnect.wav"]
    assert not backend.powered and not backend.phone_connected


def test_leaving_mode_without_phone_is_silent(bt, played):
    bt.enable()
    bt.disable()
    assert played == []


def test_startup_disable_is_silent(bt, backend, played):
    backend.powered = backend.phone_connected = True  # left over from a crash
    bt.disable()
    assert played == []
    assert not backend.powered


def test_backend_errors_are_logged_not_raised(bt, backend, caplog):
    backend.fail = True
    bt.enable()
    bt.disable()
    assert "bluetoothd not running" in caplog.text
