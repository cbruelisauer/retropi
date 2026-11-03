import pytest

from retropi.bluetooth import RETRY_S, Bluetooth, BluetoothError


class FakeBackend:
    """Stands in for BlueZ: tracks adapter state and phone connections."""

    def __init__(self):
        self.powered = False
        self.visible = False
        self.phone_connected = False
        self.reconnects = 0
        self.starts = 0
        self.fail = False

    def attach(self, on_connected, may_pair, on_bluez_restart):
        self.on_connected = on_connected
        self.may_pair = may_pair
        self.on_bluez_restart = on_bluez_restart

    def start(self):
        if self.fail:
            raise BluetoothError("bluetoothd not running")
        self.starts += 1

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

    def restart_bluez(self):
        """bluetoothd restarted: the adapter is off and the agent is gone."""
        self.powered = self.visible = self.phone_connected = False
        self.on_bluez_restart()


@pytest.fixture
def backend():
    return FakeBackend()


@pytest.fixture
def played():
    return []


def make_bt(backend, played, clock):
    bt = Bluetooth(backend, 120, played.append, "connect.wav", "disconnect.wav", clock=clock)
    bt.start()  # as open_bluetooth() does
    return bt


@pytest.fixture
def bt(backend, played, clock):
    return make_bt(backend, played, clock)


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


def test_bluez_missing_at_startup_is_retried_in_bluetooth_mode(backend, played, clock, caplog):
    backend.fail = True
    bt = make_bt(backend, played, clock)  # must not raise
    bt.disable()
    bt.enable()
    assert not backend.powered
    assert "bluetoothd not running" in caplog.text

    backend.fail = False
    clock.advance(RETRY_S - 1)
    bt.tick()
    assert not backend.powered
    clock.advance(1)
    bt.tick()
    assert backend.starts == 1
    assert backend.powered and backend.visible and bt.pairing_open()
    assert backend.reconnects == 1


def test_retry_after_window_closed_keeps_radio_hidden(backend, played, clock):
    backend.fail = True
    bt = make_bt(backend, played, clock)
    bt.enable()
    backend.fail = False
    clock.advance(200)
    bt.tick()
    assert backend.powered and not backend.visible
    assert not backend.connect(trusted=False)
    assert backend.connect(trusted=True)


def test_bluez_restart_in_bluetooth_mode_sets_up_again(bt, backend):
    bt.enable()
    backend.restart_bluez()
    bt.tick()
    assert backend.starts == 2  # agent registered with the new bluetoothd
    assert backend.powered and backend.visible
    assert backend.reconnects == 2


def test_bluez_restart_while_off_waits_for_bluetooth_mode(bt, backend):
    backend.restart_bluez()
    bt.tick()
    assert backend.starts == 1 and not backend.powered
    bt.enable()
    assert backend.starts == 2 and backend.powered


def test_no_retry_after_leaving_bluetooth_mode(bt, backend, clock):
    backend.fail = True
    bt.enable()
    bt.disable()
    backend.fail = False
    clock.advance(RETRY_S)
    bt.tick()
    assert not backend.powered
