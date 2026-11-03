"""Wi-Fi radio control through NetworkManager's nmcli."""

import logging
import subprocess

log = logging.getLogger(__name__)


def _nmcli(*args: str) -> str | None:
    try:
        result = subprocess.run(["nmcli", *args], capture_output=True, text=True, timeout=10, check=True)
    except (OSError, subprocess.SubprocessError) as e:
        stderr = getattr(e, "stderr", None)
        log.warning("nmcli %s failed: %s", " ".join(args), (stderr or str(e)).strip())
        return None
    return result.stdout


class Wifi:
    def __init__(self, run=_nmcli):
        self._run = run

    def on(self) -> None:
        self._run("radio", "wifi", "on")

    def off(self) -> None:
        self._run("radio", "wifi", "off")

    def connected(self) -> bool:
        out = self._run("-t", "-f", "TYPE,STATE", "device")
        return out is not None and any(line == "wifi:connected" for line in out.splitlines())
