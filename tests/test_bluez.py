"""BluezBackend pieces that run without a system bus (needs dbus-next)."""

import asyncio

import pytest

dbus_next = pytest.importorskip("dbus_next")

from dbus_next import DBusError, Message, MessageType, Variant

from retropi.bluetooth import DEVICE, PROPERTIES, BluezBackend, _make_agent


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
