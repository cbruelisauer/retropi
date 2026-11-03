"""Bluetooth speaker mode: BlueZ adapter power, pairing window and sounds.

BlueALSA does the audio; this module only decides when phones may see,
pair with and connect to the radio. The adapter is powered only while the
selector is on Bluetooth.
"""

import asyncio
import logging
import threading
import time
from collections.abc import Callable

log = logging.getLogger(__name__)

RETRY_S = 10  # how often Bluetooth mode retries reaching BlueZ after a failure


class BluetoothError(Exception):
    pass


class Bluetooth:
    """Mode logic on top of a backend (BluezBackend, or a fake in tests).

    BlueZ may be missing at startup or restart later. Neither stops the
    radio: while the selector is on Bluetooth, tick() registers the agent
    and powers the adapter again until it works.
    """

    def __init__(
        self,
        backend,
        pairing_window_s: float,
        play_sound: Callable[[str], None],
        connect_sound: str,
        disconnect_sound: str,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._backend = backend
        self._pairing_window_s = pairing_window_s
        self._play_sound = play_sound
        self._connect_sound = connect_sound
        self._disconnect_sound = disconnect_sound
        self._clock = clock
        self._enabled = False  # the selector is on Bluetooth
        self._ready = False  # our agent is registered with the running bluetoothd
        self._active = False  # the adapter is powered and set up for this enable()
        self._next_try = 0.0
        self._window_ends = None
        backend.attach(
            on_connected=self._on_connected, may_pair=self.pairing_open, on_bluez_restart=self._on_bluez_restart
        )

    def start(self) -> None:
        """Register with BlueZ now, so disable() can switch the adapter off at startup."""
        try:
            self._backend.start()
        except BluetoothError as e:
            log.error("bluetooth unavailable, retrying in Bluetooth mode: %s", e)
            return
        self._ready = True

    def enable(self) -> None:
        self._enabled = True
        self._window_ends = self._clock() + self._pairing_window_s
        log.info("bluetooth on, pairing open for %.0f s", self._pairing_window_s)
        self._activate()

    def tick(self) -> None:
        """Close the pairing window once it has run out, and retry a failed
        enable(); call from the main loop."""
        now = self._clock()
        if self._window_ends is not None and now >= self._window_ends:
            self._window_ends = None
            if self._active:
                self._try(self._backend.set_visible, False)
            log.info("pairing window closed")
        if self._enabled and not self._active and now >= self._next_try:
            self._activate()

    def disable(self) -> None:
        was_enabled = self._enabled
        # Cleared first, so the disconnect caused by powering off plays no sound.
        self._enabled = False
        self._active = False
        self._window_ends = None
        # Without BlueZ there is nothing to switch off; a bluetoothd that
        # starts later leaves the adapter off (AutoEnable=false).
        if self._ready:
            if was_enabled and self._try(self._backend.connected):
                self._play_sound(self._disconnect_sound)
            self._try(self._backend.power, False)
        if was_enabled:
            log.info("bluetooth off")

    def pairing_open(self) -> bool:
        return self._enabled and self._window_ends is not None

    def close(self) -> None:
        self._backend.close()

    def _on_connected(self, connected: bool) -> None:
        if not self._enabled:
            return
        log.info("phone %s", "connected" if connected else "disconnected")
        self._play_sound(self._connect_sound if connected else self._disconnect_sound)

    def _on_bluez_restart(self) -> None:
        # Runs on the backend's thread. A new bluetoothd has no agent and an
        # unpowered adapter, so tick() sets both up again in Bluetooth mode.
        self._ready = False
        self._active = False
        self._next_try = self._clock()

    def _activate(self) -> None:
        """Register the agent if needed and power the adapter; on failure,
        tick() tries again after RETRY_S."""
        try:
            if not self._ready:
                self._backend.start()
                self._ready = True
            self._backend.power(True)
            self._backend.set_visible(self.pairing_open())
            self._backend.reconnect_trusted()
        except BluetoothError as e:
            log.error("bluetooth: %s; retrying in %.0f s", e, RETRY_S)
            self._next_try = self._clock() + RETRY_S
            return
        self._active = True

    def _try(self, fn, *args):
        try:
            return fn(*args)
        except BluetoothError as e:
            log.error("bluetooth: %s", e)
            return None


BLUEZ = "org.bluez"
DBUS = "org.freedesktop.DBus"
ADAPTER = "org.bluez.Adapter1"
DEVICE = "org.bluez.Device1"
PROPERTIES = "org.freedesktop.DBus.Properties"
AGENT_PATH = "/org/retropi/agent"


class BluezBackend:
    """Talks to BlueZ over the system D-Bus.

    dbus-next is asyncio-based, so its event loop runs in a background
    thread and the blocking methods below wait for it with a timeout.
    """

    def __init__(self, name: str, adapter_path: str = "/org/bluez/hci0"):
        self._name = name
        self._adapter = adapter_path
        self._on_connected = lambda connected: None
        self._may_pair = lambda: False
        self._on_bluez_restart = lambda: None
        self._bus = None
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="bluez", daemon=True)
        self._thread.start()

    def attach(
        self,
        on_connected: Callable[[bool], None],
        may_pair: Callable[[], bool],
        on_bluez_restart: Callable[[], None] = lambda: None,
    ) -> None:
        self._on_connected = on_connected
        self._may_pair = may_pair
        self._on_bluez_restart = on_bluez_restart

    def start(self) -> None:
        """Connect to the bus and register the agent; safe to call again,
        e.g. after bluetoothd restarted."""
        self._run(self._start())

    def power(self, on: bool) -> None:
        self._run(self._power(on))

    def set_visible(self, on: bool) -> None:
        self._run(self._set_visible(on))

    def connected(self) -> bool:
        return any(props.get("Connected") for props in self._run(self._devices()).values())

    def reconnect_trusted(self) -> None:
        # Connecting takes seconds; don't block the main loop on it.
        asyncio.run_coroutine_threadsafe(self._reconnect_trusted(), self._loop)

    def close(self) -> None:
        if self._bus is not None:
            self._loop.call_soon_threadsafe(self._bus.disconnect)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2)

    def _run(self, coro, timeout: float = 10):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout)
        except TimeoutError as e:
            future.cancel()
            raise BluetoothError("BlueZ did not answer") from e
        except Exception as e:
            # D-Bus and BlueZ errors come in many types (DBusError, OSError,
            # AuthError, ...); none of them may stop the radio.
            raise BluetoothError(f"{type(e).__name__}: {e}") from e

    async def _start(self):
        from dbus_next import BusType, DBusError, Message
        from dbus_next.aio import MessageBus

        if self._bus is None:
            # Kept only once fully set up, so a failed start() redoes all of it.
            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            bus.export(AGENT_PATH, _make_agent(self))
            rules = (
                f"type='signal',sender='{BLUEZ}',interface='{PROPERTIES}',member='PropertiesChanged',arg0='{DEVICE}'",
                f"type='signal',sender='{DBUS}',interface='{DBUS}',member='NameOwnerChanged',arg0='{BLUEZ}'",
            )
            for rule in rules:
                await bus.call(
                    Message(
                        destination=DBUS,
                        path="/org/freedesktop/DBus",
                        interface=DBUS,
                        member="AddMatch",
                        signature="s",
                        body=[rule],
                    )
                )
            bus.add_message_handler(self._on_message)
            self._bus = bus
        try:
            await self._call(
                "/org/bluez", "org.bluez.AgentManager1", "RegisterAgent", "os", [AGENT_PATH, "NoInputNoOutput"]
            )
        except DBusError as e:
            if e.type != "org.bluez.Error.AlreadyExists":  # an earlier start() got this far
                raise
        await self._call("/org/bluez", "org.bluez.AgentManager1", "RequestDefaultAgent", "o", [AGENT_PATH])

    async def _power(self, on: bool):
        if on:
            await self._set(self._adapter, ADAPTER, "Alias", "s", self._name)
        await self._set(self._adapter, ADAPTER, "Powered", "b", on)

    async def _set_visible(self, on: bool):
        await self._set(self._adapter, ADAPTER, "Pairable", "b", on)
        await self._set(self._adapter, ADAPTER, "Discoverable", "b", on)

    async def _devices(self) -> dict[str, dict]:
        """Devices known to our adapter: path -> plain property values."""
        (objects,) = await self._call("/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects")
        return {
            path: {key: variant.value for key, variant in interfaces[DEVICE].items()}
            for path, interfaces in objects.items()
            if DEVICE in interfaces and path.startswith(self._adapter + "/")
        }

    async def _reconnect_trusted(self):
        from dbus_next import DBusError

        try:
            devices = await self._devices()
            if any(props.get("Connected") for props in devices.values()):
                return
            for path, props in devices.items():
                if props.get("Trusted") and props.get("Paired"):
                    try:
                        await self._call(path, DEVICE, "Connect")
                        log.info("reconnected %s", props.get("Alias", path))
                        return
                    except DBusError as e:
                        log.debug("cannot reconnect %s: %s", props.get("Alias", path), e)
        except Exception:
            log.exception("reconnecting trusted phones failed")

    async def _authorize(self, device: str):
        from dbus_next import DBusError

        if not self._may_pair():
            raise DBusError("org.bluez.Error.Rejected", "pairing window closed")
        await self._set(device, DEVICE, "Trusted", "b", True)
        log.info("paired %s", device)

    async def _authorize_service(self, device: str):
        from dbus_next import DBusError

        (trusted,) = await self._call(device, PROPERTIES, "Get", "ss", [DEVICE, "Trusted"])
        if trusted.value:
            return
        if not self._may_pair():
            raise DBusError("org.bluez.Error.Rejected", "device not trusted")
        # With NoInputNoOutput the kernel accepts Just Works pairing without
        # asking the agent, so this is the first call a new phone makes.
        await self._set(device, DEVICE, "Trusted", "b", True)
        log.info("trusted %s", device)

    def _on_message(self, msg):
        from dbus_next import MessageType

        if (
            msg.message_type == MessageType.SIGNAL
            and msg.sender == DBUS
            and msg.interface == DBUS
            and msg.member == "NameOwnerChanged"
            and msg.body[0] == BLUEZ
        ):
            # bluetoothd stopped or started; either way our agent is gone.
            log.warning("bluetoothd %s", "started" if msg.body[2] else "stopped")
            self._on_bluez_restart()
        elif (
            msg.message_type == MessageType.SIGNAL
            and msg.interface == PROPERTIES
            and msg.member == "PropertiesChanged"
            and msg.path.startswith(self._adapter + "/")
        ):
            interface, changed, _ = msg.body
            if interface == DEVICE and "Connected" in changed:
                self._on_connected(bool(changed["Connected"].value))

    async def _set(self, path, interface, prop, signature, value):
        from dbus_next import Variant

        await self._call(path, PROPERTIES, "Set", "ssv", [interface, prop, Variant(signature, value)])

    async def _call(self, path, interface, member, signature="", body=()):
        from dbus_next import DBusError, Message, MessageType

        reply = await self._bus.call(
            Message(
                destination=BLUEZ, path=path, interface=interface, member=member, signature=signature, body=list(body)
            )
        )
        if reply.message_type == MessageType.ERROR:
            raise DBusError(reply.error_name, reply.body[0] if reply.body else "")
        return reply.body


def _make_agent(backend: BluezBackend):
    """A NoInputNoOutput pairing agent: accepts pairing without a PIN while
    the pairing window is open and marks the phone trusted."""
    from dbus_next.service import ServiceInterface, method

    # dbus-next reads D-Bus signatures from the string annotations.
    class Agent(ServiceInterface):
        def __init__(self):
            super().__init__("org.bluez.Agent1")

        @method()
        def Release(self):
            pass

        @method()
        async def RequestPinCode(self, device: "o") -> "s":
            await backend._authorize(device)
            return "0000"

        @method()
        async def RequestPasskey(self, device: "o") -> "u":
            await backend._authorize(device)
            return 0

        @method()
        async def RequestConfirmation(self, device: "o", passkey: "u"):
            await backend._authorize(device)

        @method()
        async def RequestAuthorization(self, device: "o"):
            await backend._authorize(device)

        @method()
        async def AuthorizeService(self, device: "o", uuid: "s"):
            await backend._authorize_service(device)

        @method()
        def Cancel(self):
            pass

    return Agent()


def open_bluetooth(cfg, play_sound) -> Bluetooth:
    backend = BluezBackend(cfg.bluetooth.name)
    bt = Bluetooth(
        backend,
        cfg.bluetooth.pairing_window_s,
        play_sound,
        cfg.audio.connect_sound,
        cfg.audio.disconnect_sound,
    )
    bt.start()
    return bt
