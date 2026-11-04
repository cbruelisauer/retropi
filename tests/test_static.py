import threading
import time
import wave
from array import array
from pathlib import Path

import pytest

from retropi.static import Loop, Static, read_clip

STATIC_WAV = Path(__file__).parent.parent / "sounds" / "static.wav"


def samples(chunk: bytes) -> array:
    return array("h", chunk)


def test_loop_wraps_around_the_clip():
    loop = Loop(array("h", [1, 2, 3]), channels=1, fade_frames=1)
    chunk, gain = loop.render(7, 1.0, 1.0)
    assert list(samples(chunk)) == [1, 2, 3, 1, 2, 3, 1]
    assert gain == 1.0


def test_loop_fades_in_linearly_and_holds():
    loop = Loop(array("h", [1000] * 8), channels=2, fade_frames=4)
    chunk, gain = loop.render(6, 0.0, 1.0)
    assert list(samples(chunk)) == [250, 250, 500, 500, 750, 750, 1000, 1000, 1000, 1000, 1000, 1000]
    assert gain == 1.0


def test_loop_fades_out_from_where_it_is():
    loop = Loop(array("h", [1000]), channels=1, fade_frames=4)
    chunk, gain = loop.render(3, 0.5, 0.0)
    assert list(samples(chunk)) == [250, 0, 0]
    assert gain == 0.0


def test_read_clip_scales_by_level(tmp_path):
    path = tmp_path / "clip.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(array("h", [10000, -10000, 32767]).tobytes())
    data, channels, rate = read_clip(path, -6.0)
    assert (channels, rate) == (1, 8000)
    assert list(data) == [5011, -5011, 16422]


def test_read_clip_rejects_8_bit(tmp_path):
    path = tmp_path / "clip.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(8000)
        w.writeframes(b"\x80\x80")
    with pytest.raises(ValueError, match="16-bit"):
        read_clip(path, 0.0)


def test_shipped_clip_loads():
    data, channels, rate = read_clip(STATIC_WAV, -6.0)
    assert channels == 2
    assert len(data) / channels / rate >= 2.0


class FakePcm:
    def __init__(self, log):
        self.log = log
        self.closed = False

    def write(self, chunk):
        self.log.append(max(abs(s) for s in samples(chunk)))
        time.sleep(0.001)

    def drop(self):
        pass

    def close(self):
        self.closed = True


def wait_for(predicate, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.005)
    return False


@pytest.fixture
def player():
    log, pcms = [], []

    def open_pcm():
        pcm = FakePcm(log)
        pcms.append(pcm)
        return pcm

    static = Static(Loop(array("h", [1000]), channels=1, fade_frames=4096), open_pcm)
    yield static, log, pcms
    static.close()


def test_static_opens_pcm_only_while_on(player):
    static, log, pcms = player
    time.sleep(0.05)
    assert pcms == []
    static.on()
    assert wait_for(lambda: log and log[-1] == 1000)  # faded in to full level
    static.off()
    assert wait_for(lambda: pcms[-1].closed)
    assert log[-1] < 1000  # faded out, not cut


def test_static_stop_cuts_at_once(player):
    static, log, pcms = player
    static.on()
    assert wait_for(lambda: len(log) >= 2)
    static.stop()
    assert wait_for(lambda: pcms[-1].closed)
    written = len(log)
    time.sleep(0.05)
    assert len(log) == written


def test_static_gives_up_on_pcm_error():
    attempts = threading.Event()

    def broken():
        attempts.set()
        raise OSError("no such device")

    static = Static(Loop(array("h", [1000]), channels=1, fade_frames=4), broken)
    try:
        static.on()
        assert attempts.wait(1)
        static.on()  # a later on() tries again
    finally:
        static.close()
