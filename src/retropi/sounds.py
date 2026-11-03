"""Short sound effects, played through the shared dmix default device."""

import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


def play(path: str | Path, wait: bool = False) -> None:
    try:
        proc = subprocess.Popen(["aplay", "-q", str(path)], stdin=subprocess.DEVNULL)
    except OSError as e:
        log.warning("cannot play %s: %s", path, e)
        return
    if wait:
        proc.wait()
