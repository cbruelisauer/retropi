"""Render sounds/static.wav, the default tuning static.

Pink noise, band-limited like an AM receiver, with a slow fading wobble and
a few crackles. The end is crossfaded into the start so it loops without a
click. Deterministic, so re-running it gives the same file.

    python tools/make_static.py [output.wav]
"""

import math
import random
import sys
import wave
from array import array
from pathlib import Path

RATE = 22050  # the static is band-limited anyway; ALSA's plug resamples it
SECONDS = 4.0
SEAM_S = 0.2
PEAK_DBFS = -1.0


def one_pole(cutoff_hz: float) -> float:
    return 1.0 - math.exp(-2.0 * math.pi * cutoff_hz / RATE)


def render(seed: int = 4711) -> list[float]:
    rng = random.Random(seed)
    n = int(RATE * (SECONDS + SEAM_S))
    b0 = b1 = b2 = 0.0  # Paul Kellet's economy pink filter
    hp_a, lp_a = one_pole(180.0), one_pole(3800.0)
    hp = lp1 = lp2 = 0.0
    crackle = 0.0
    crackle_decay = math.exp(-1.0 / (0.002 * RATE))
    flutter, flutter_a = 0.0, one_pole(3.0)
    out = []
    for i in range(n):
        t = i / RATE
        white = rng.uniform(-1.0, 1.0)
        b0 = 0.99765 * b0 + white * 0.0990460
        b1 = 0.96300 * b1 + white * 0.2965164
        b2 = 0.57000 * b2 + white * 1.0526913
        pink = b0 + b1 + b2 + white * 0.1848
        if rng.random() < 7.0 / RATE:  # about 7 crackles a second
            crackle += rng.choice((-1, 1)) * rng.uniform(2.0, 6.0)
        crackle *= crackle_decay
        flutter += flutter_a * (rng.uniform(-1.0, 1.0) - flutter)
        wobble = 0.75 + 0.15 * math.sin(2 * math.pi * 0.5 * t) + 0.6 * flutter
        x = pink * wobble + crackle
        hp += hp_a * (x - hp)
        x -= hp  # high-pass
        lp1 += lp_a * (x - lp1)
        lp2 += lp_a * (lp1 - lp2)
        out.append(lp2)
    return out


def loop(samples: list[float]) -> list[float]:
    """Crossfade the extra tail into the start, so the clip loops seamlessly."""
    seam = int(RATE * SEAM_S)
    body = samples[: len(samples) - seam]
    tail = samples[len(samples) - seam :]
    for i in range(seam):
        a = (i + 0.5) / seam  # equal-power: noise is uncorrelated
        body[i] = body[i] * math.sin(a * math.pi / 2) + tail[i] * math.cos(a * math.pi / 2)
    return body


def write(path: Path, samples: list[float]) -> None:
    peak = max(abs(s) for s in samples)
    scale = 32767 * 10 ** (PEAK_DBFS / 20) / peak
    frames = array("h")
    for s in samples:
        v = round(s * scale)
        frames.extend((v, v))  # stereo, same on both channels
    if sys.byteorder == "big":
        frames.byteswap()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(frames.tobytes())


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent / "sounds" / "static.wav"
    write(target, loop(render()))
    print(f"wrote {target}")
