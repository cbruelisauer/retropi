"""Internet radio through MPD."""

import logging

log = logging.getLogger(__name__)


class Radio:
    """Plays stations from an MPD playlist.

    MPD closes idle client connections (60 s by default), so every command
    reopens a dropped connection and is retried once.
    """

    def __init__(self, client, host: str, port: int, playlist: str, connection_errors, command_errors):
        self._client = client
        self._host = host
        self._port = port
        self._playlist = playlist
        self._connection_errors = connection_errors
        self._command_errors = command_errors  # anything a command can raise
        self._connected = False

    def load(self) -> int:
        """Replace MPD's queue with the playlist; returns the station count."""
        self._call("clear")
        self._call("load", self._playlist)
        count = len(self._call("playlistinfo"))
        if count == 0:
            raise RuntimeError(f"MPD playlist {self._playlist!r} is empty")
        log.info("loaded %d stations from %r", count, self._playlist)
        return count

    def play(self, index: int) -> bool:
        """Play the station at a 0-based index; True if MPD is playing it."""
        try:
            self._call("clearerror")
            self._call("play", index)
        except self._command_errors as e:
            log.warning("cannot play station %d: %s", index + 1, e)
            return False
        if not self.playing():
            return False
        log.info("playing station %d", index + 1)
        return True

    def playing(self) -> bool:
        """True if MPD is playing without error.

        MPD opens a stream after ``play`` returns, so a stream that fails to
        open, or drops later, shows up here rather than in ``play()``.
        """
        try:
            status = self._call("status")
        except self._command_errors as e:
            log.warning("cannot read MPD status: %s", e)
            return False
        if status.get("state") != "play" or "error" in status:
            log.warning("stream not playing: %s", status.get("error", status.get("state")))
            return False
        return True

    def audible(self) -> bool:
        """True once MPD is playing the stream, not only connecting to it.

        MPD reports "play" while it still opens and buffers a stream; the
        elapsed time starts counting only when the audio comes out.
        """
        try:
            status = self._call("status")
        except self._command_errors:
            return False
        if status.get("state") != "play" or "error" in status:
            return False
        try:
            return float(status.get("elapsed", 0)) > 0
        except ValueError:
            return False

    def stop(self) -> None:
        try:
            self._call("stop")
        except self._command_errors as e:
            log.warning("cannot stop playback: %s", e)

    def close(self) -> None:
        if self._connected:
            try:
                self._client.disconnect()
            except self._connection_errors:
                pass
            self._connected = False

    def _call(self, command, *args):
        for attempt in (1, 2):
            try:
                if not self._connected:
                    self._client.connect(self._host, self._port)
                    self._connected = True
                return getattr(self._client, command)(*args)
            except self._connection_errors:
                self.close()
                if attempt == 2:
                    raise
                log.info("MPD connection lost, reconnecting")


def open_radio(cfg) -> Radio:
    import mpd

    client = mpd.MPDClient()
    client.timeout = 10
    return Radio(
        client, cfg.mpd.host, cfg.mpd.port, cfg.mpd.playlist, (mpd.ConnectionError, OSError), (mpd.MPDError, OSError)
    )
