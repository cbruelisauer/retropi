"""Hardware volume on the sound card's mixer control."""

import logging

log = logging.getLogger(__name__)


class Mixer:
    """Sets the card's mixer in dB.

    It talks to the hw card, not the dmix default, so the level applies to
    MPD, Bluetooth and the sounds alike.
    """

    def __init__(self, control, units_db, units_percent):
        self._control = control
        self._units_db = units_db
        self._units_percent = units_percent

    def set_db(self, db: float) -> None:
        # pyalsaaudio takes dB values in hundredths of a dB.
        self._control.setvolume(round(db * 100), units=self._units_db)
        log.debug("volume %.1f dB", db)

    def mute(self) -> None:
        self._control.setvolume(0, units=self._units_percent)


def open_mixer(cfg) -> Mixer:
    import alsaaudio

    control = alsaaudio.Mixer(control=cfg.audio.mixer, device=f"hw:CARD={cfg.audio.card}")
    try:
        control.setmute(0)
    except alsaaudio.ALSAAudioError:
        pass  # control has no mute switch
    return Mixer(control, alsaaudio.VOLUME_UNITS_DB, alsaaudio.VOLUME_UNITS_PERCENTAGE)
