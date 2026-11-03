"""BluezBackend pieces that run without a system bus (needs dbus-next)."""

import asyncio

import pytest

dbus_next = pytest.importorskip("dbus_next")

from dbus_next import DBusError, Message, MessageType, Variant

from retropi.bluetooth import DBUS, DEVICE, PROPERTIES, BluetoothError, BluezBackend, _make_agent


@pytest.fixture
def backend():
    b = BluezBackend("RetroPi")
    yield b
    b.close()


def test_agent_exports_bluez_methods(backend):
    agent = _make_agent(backend)
    names = {m.name: m.in_signature for m in agent.introspect().methods}
    assert names["RequestConfirmation"] == "ou"
    assert names["RequestAuthorization"] == "o"
    assert names["AuthorizeService"] == "os"


def test_agent_rejects_pairing_when_window_closed(backend):
    backend.attach(on_connected=lambda c: None, may_pair=lambda: False)
    with pytest.raises(DBusError, match="pairing window closed"):
        asyncio.run(backend._authorize("/org/bluez/hci0/dev_00_11_22_33_44_55"))


def test_agent_trusts_device_while_window_open(backend):
    sets = []

    async def fake_set(path, interface, prop, signature, value):
        sets.append((path, prop, value))

    backend._set = fake_set
    backend.attach(on_connected=lambda c: None, may_pair=lambda: True)
    asyncio.run(backend._authorize("/org/bluez/hci0/dev_AA"))
    assert sets == [("/org/bluez/hci0/dev_AA", "Trusted", True)]


def signal_msg(path, interface, changed):
    return Message(
        message_type=MessageType.SIGNAL,
        path=path,
        interface=PROPERTIES,
        member="PropertiesChanged",
        signature="sa{sv}as",
        body=[interface, changed, []],
    )


def test_connected_signal_reaches_callback(backend):
    seen = []
    backend.attach(on_connected=seen.append, may_pair=lambda: False)
    backend._on_message(signal_msg("/org/bluez/hci0/dev_AA", DEVICE, {"Connected": Variant("b", True)}))
    backend._on_message(signal_msg("/org/bluez/hci0/dev_AA", DEVICE, {"RSSI": Variant("n", -40)}))
    backend._on_message(signal_msg("/org/bluez/hci0", "org.bluez.Adapter1", {"Powered": Variant("b", False)}))
    backend._on_message(signal_msg("/org/bluez/hci0/dev_AA", DEVICE, {"Connected": Variant("b", False)}))
    assert seen == [True, False]


def name_owner_msg(name, new_owner, sender=DBUS):
    return Message(
        message_type=MessageType.SIGNAL,
        sender=sender,
        path="/org/freedesktop/DBus",
        interface=DBUS,
        member="NameOwnerChanged",
        signature="sss",
        body=[name, ":1.5", new_owner],
    )


def test_bluez_restart_reaches_callback(backend):
    restarts = []
    backend.attach(on_connected=lambda c: None, may_pair=lambda: False, on_bluez_restart=lambda: restarts.append(1))
    backend._on_message(name_owner_msg("org.bluez", ""))
    backend._on_message(name_owner_msg("org.bluez", ":1.9"))
    backend._on_message(name_owner_msg("org.freedesktop.NetworkManager", ":1.9"))
    backend._on_message(name_owner_msg("org.bluez", ":1.9", sender=":1.42"))  # not from the bus daemon
    assert len(restarts) == 2


def test_start_again_accepts_agent_already_registered(backend):
    calls = []

    async def fake_call(path, interface, member, signature="", body=()):
        calls.append(member)
        if member == "RegisterAgent":
            raise DBusError("org.bluez.Error.AlreadyExists", "Already Exists")
        return []

    backend._bus = object()  # connected and set up by an earlier start()
    backend._call = fake_call
    try:
        backend.start()
    finally:
        backend._bus = None
    assert calls == ["RegisterAgent", "RequestDefaultAgent"]


def test_start_errors_become_bluetooth_errors(backend):
    async def fake_call(path, interface, member, signature="", body=()):
        raise DBusError("org.freedesktop.DBus.Error.ServiceUnknown", "org.bluez was not provided")

    backend._bus = object()
    backend._call = fake_call
    try:
        with pytest.raises(BluetoothError, match="ServiceUnknown|not provided"):
            backend.start()
    finally:
        backend._bus = None


@pytest.fixture
def service_backend(backend):
    """A backend whose Get Trusted answers ``backend.trusted`` and that records Set calls."""
    backend.trusted = False
    backend.sets = []

    async def fake_call(path, interface, member, signature="", body=()):
        assert (interface, member, list(body)) == (PROPERTIES, "Get", [DEVICE, "Trusted"])
        return [Variant("b", backend.trusted)]

    async def fake_set(path, interface, prop, signature, value):
        backend.sets.append((path, prop, value))

    backend._call = fake_call
    backend._set = fake_set
    return backend


def test_service_trusts_new_phone_while_window_open(service_backend):
    # Just Works pairing never reaches the agent, so AuthorizeService must trust the phone.
    service_backend.attach(on_connected=lambda c: None, may_pair=lambda: True)
    asyncio.run(service_backend._authorize_service("/org/bluez/hci0/dev_AA"))
    assert service_backend.sets == [("/org/bluez/hci0/dev_AA", "Trusted", True)]


def test_service_rejects_untrusted_phone_when_window_closed(service_backend):
    service_backend.attach(on_connected=lambda c: None, may_pair=lambda: False)
    with pytest.raises(DBusError, match="device not trusted"):
        asyncio.run(service_backend._authorize_service("/org/bluez/hci0/dev_AA"))
    assert service_backend.sets == []


def test_service_accepts_trusted_phone_when_window_closed(service_backend):
    service_backend.trusted = True
    service_backend.attach(on_connected=lambda c: None, may_pair=lambda: False)
    asyncio.run(service_backend._authorize_service("/org/bluez/hci0/dev_AA"))
    assert service_backend.sets == []
