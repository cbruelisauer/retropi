"""Radio static between stations, looped from a WAV clip with fades.

The clip is read once and played by a background thread to the shared dmix
default device, so it mixes with the stream and follows the volume knob.
"""

import logging
import threading
import wave
from array import array
from pathlib import Path

log = logging.getLogger(__name__)

PERIOD_FRAMES = 1024  # about 23 ms at 44.1 kHz: on() and off() react within a few periods
OPEN_RETRY_S = 1.0  # how often a failing PCM is tried again while the static is on


class Loop:
    """A looped 16-bit clip with a gain that ramps linearly towards a target.

    Pure arithmetic, so it is tested without ALSA.
    """

    def __init__(self, samples: array, channels: int, fade_frames: int):
        if len(samples) < channels:
            raise ValueError("static clip is empty")
        self.samples = samples
        self.channels = channels
        self._step = 1.0 / max(1, fade_frames)  # gain change per frame
        self._pos = 0  # in samples

    def render(self, frames: int, gain: float, target: float) -> tuple[bytes, float]:
        """Return the next ``frames`` frames as bytes and the gain at their end."""
        n = frames * self.channels
        chunk = array("h")
        while len(chunk) < n:
            take = min(n - len(chunk), len(self.samples) - self._pos)
            chunk.extend(self.samples[self._pos : self._pos + take])
            self._pos = (self._pos + take) % len(self.samples)
        if gain == target == 1.0:
            return chunk.tobytes(), gain
        out = array("h", bytes(2 * n))
        ch = self.channels
        for frame in range(frames):
            if gain < target:
                gain = min(target, gain + self._step)
            elif gain > target:
                gain = max(target, gain - self._step)
            base = frame * ch
            for c in range(ch):
                out[base + c] = int(chunk[base + c] * gain)
        return out.tobytes(), gain


def read_clip(path: str | Path, level_db: float) -> tuple[array, int, int]:
    """Read a 16-bit WAV and scale it by ``level_db``; returns (samples, channels, rate)."""
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError(f"{path}: static clip must be 16-bit PCM")
        channels, rate = w.getnchannels(), w.getframerate()
        samples = array("h", w.readframes(w.getnframes()))
    factor = 10 ** (level_db / 20)
    scaled = array("h", (max(-32768, min(32767, int(s * factor))) for s in samples))
    return scaled, channels, rate


class Static:
    """Plays the loop on a background thread while it is switched on.

    ``on()`` fades in, ``off()`` fades out, ``stop()`` cuts it at once. The
    PCM is open only while the static is audible. If ALSA fails, the static
    stays switched on and the PCM is opened again every ``OPEN_RETRY_S``.
    """

    def __init__(self, loop: Loop, open_pcm, errors=(OSError,)):
        self._loop = loop
        self._open_pcm = open_pcm
        self._errors = errors
        self._cond = threading.Condition()
        self._target = 0.0
        self._gain = 0.0
        self._cut = False
        self._closing = False
        self._thread = threading.Thread(target=self._run, name="static", daemon=True)
        self._thread.start()

    def on(self) -> None:
        self._set(1.0)

    def off(self) -> None:
        self._set(0.0)

    def stop(self) -> None:
        with self._cond:
            self._target = self._gain = 0.0
            self._cut = True
            self._cond.notify()

    def close(self) -> None:
        with self._cond:
            self._closing = True
            self._cond.notify()
        self._thread.join(timeout=2)

    def _set(self, target: float) -> None:
        with self._cond:
            self._target = target
            self._cond.notify()

    def _run(self) -> None:
        pcm = None
        failing = False  # the PCM cannot be opened or written; retried every OPEN_RETRY_S
        try:
            while True:
                with self._cond:
                    faded_out = self._target == self._gain == 0.0
                    cut = self._cut or self._closing
                    self._cut = False
                if (cut or faded_out) and pcm is not None:
                    # A finished fade-out is still in the ALSA buffer, so let it
                    # play out; stop() and close() discard it. Outside the lock,
                    # since draining blocks for up to a buffer's length.
                    _close(pcm, drain=not cut)
                    pcm = None
                with self._cond:
                    while not self._closing and self._target == self._gain == 0.0:
                        self._cond.wait()
                    if self._closing:
                        return
                    gain, target = self._gain, self._target
                chunk, gain = self._loop.render(PERIOD_FRAMES, gain, target)
                with self._cond:
                    if self._cut:  # stop() came while rendering: drop this chunk
                        continue
                    self._gain = gain
                try:
                    if pcm is None:
                        pcm = self._open_pcm()
                    pcm.write(chunk)
                except self._errors as e:
                    # Keep the target: the static comes back once the device
                    # works again, without the caller having to switch it on anew.
                    if not failing:
                        log.warning("cannot play static, retrying every %.0f s: %s", OPEN_RETRY_S, e)
                    failing = True
                    if pcm is not None:
                        _close(pcm, drain=False)
                        pcm = None
                    with self._cond:
                        self._gain = 0.0  # fade in again once it plays
                        self._cond.wait_for(
                            lambda: self._closing or self._cut or self._target == 0.0, timeout=OPEN_RETRY_S
                        )
                else:
                    if failing:
                        log.info("static plays again")
                    failing = False
        finally:
            if pcm is not None:
                _close(pcm, drain=False)


def _close(pcm, drain: bool) -> None:
    """Close the PCM; ``drain`` plays out what is still buffered, else it is discarded."""
    finish = getattr(pcm, "drain" if drain else "drop", None)
    try:
        if finish is not None:
            finish()
    except Exception as e:  # noqa: BLE001 - closing must never kill the thread
        log.debug("%s static PCM: %s", "draining" if drain else "dropping", e)
    try:
        pcm.close()
    except Exception as e:  # noqa: BLE001
        log.debug("closing static PCM: %s", e)


class NoStatic:
    """Stands in for Static when tuning static is turned off."""

    def on(self) -> None:
        pass

    def off(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def close(self) -> None:
        pass


def open_static(cfg) -> "Static | NoStatic":
    import alsaaudio

    tuning = cfg.tuning
    try:
        samples, channels, rate = read_clip(tuning.static_sound, tuning.static_level_db)
    except (OSError, EOFError, ValueError, wave.Error) as e:
        log.warning("no tuning static: %s", e)
        return NoStatic()

    def open_pcm():
        return alsaaudio.PCM(
            type=alsaaudio.PCM_PLAYBACK,
            device="default",
            channels=channels,
            rate=rate,
            format=alsaaudio.PCM_FORMAT_S16_LE,
            periodsize=PERIOD_FRAMES,
        )

    fade_frames = rate * tuning.static_fade_ms // 1000
    return Static(Loop(samples, channels, fade_frames), open_pcm, (alsaaudio.ALSAAudioError, OSError))
