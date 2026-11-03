#!/bin/bash
# Turn a freshly flashed Raspberry Pi OS Lite (Trixie) card into a working
# retropi radio. Idempotent: re-running it is also the update path.
#
#   git clone https://github.com/cbruelisauer/retropi.git ~/retropi && cd ~/retropi
#   sudo ./deploy/install.sh
#
# Set RETROPI_NO_REBOOT=1 to skip the reboot after a boot config change.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SYSTEM="$REPO/system"
APP_DIR=/opt/retropi
RADIO_USER=pi
BOOT_CONFIG=/boot/firmware/config.txt
PACKAGES=(
    mpd mpc bluez bluez-alsa-utils alsa-utils
    python3-gpiozero python3-lgpio python3-alsaaudio python3-mpd python3-dbus-next python3-venv
)
SERVICES=(mpd bluetooth bluealsa bluealsa-aplay retropi)
REBOOT=0

step() { printf '\n== %s\n' "$*"; }

# Copy a file only when its content differs; prints what changed.
install_file() {
    local src=$1 dst=$2 mode=${3:-644}
    if ! cmp -s "$src" "$dst"; then
        install -D -m "$mode" "$src" "$dst"
        echo "installed $dst"
    fi
}

step "1. Pre-checks"
if [[ $EUID -ne 0 ]]; then
    echo "run as root: sudo $0" >&2
    exit 1
fi
if ! grep -q '^VERSION_CODENAME=trixie$' /etc/os-release; then
    echo "needs Raspberry Pi OS Trixie (Debian 13); found: $(grep '^PRETTY_NAME=' /etc/os-release | cut -d= -f2-)" >&2
    exit 1
fi
if ! id "$RADIO_USER" >/dev/null 2>&1; then
    echo "user $RADIO_USER does not exist; create it in Raspberry Pi Imager" >&2
    exit 1
fi
echo "board: $(tr -d '\0' </proc/device-tree/model 2>/dev/null || echo unknown)"

step "2. Boot config"
BEGIN="# >>> retropi >>>"
END="# <<< retropi <<<"
current="$(cat "$BOOT_CONFIG")"
wanted="$(awk -v b="$BEGIN" -v e="$END" '$0 == b {skip = 1; next} $0 == e {skip = 0; next} !skip' "$BOOT_CONFIG")
$BEGIN
[all]
# HiFiBerry Amp+ (TAS5713): onboard and HDMI audio off, Amp overlay on
dtparam=audio=off
dtoverlay=vc4-kms-v3d,noaudio
dtoverlay=hifiberry-amp
$END"
if [[ "$current" != "$wanted" ]]; then
    [[ -e "$BOOT_CONFIG.retropi-orig" ]] || cp "$BOOT_CONFIG" "$BOOT_CONFIG.retropi-orig"
    printf '%s\n' "$wanted" >"$BOOT_CONFIG"
    echo "updated $BOOT_CONFIG (original kept as $BOOT_CONFIG.retropi-orig)"
    REBOOT=1
fi

step "3. Packages"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y "${PACKAGES[@]}"

step "4. System files"
install_file "$SYSTEM/asound.conf" /etc/asound.conf
install_file "$SYSTEM/mpd.conf" /etc/mpd.conf
install_file "$SYSTEM/bluetooth-main.conf" /etc/bluetooth/main.conf
install_file "$SYSTEM/bluealsa-a2dp-sink.conf" /etc/systemd/system/bluealsa.service.d/retropi.conf
install_file "$SYSTEM/bluealsa-aplay-dmix.conf" /etc/systemd/system/bluealsa-aplay.service.d/retropi.conf
install_file "$SYSTEM/50-retropi-wifi.rules" /etc/polkit-1/rules.d/50-retropi-wifi.rules
install_file "$SYSTEM/retropi.service" /etc/systemd/system/retropi.service

step "5. User"
usermod -aG gpio,audio,bluetooth,netdev "$RADIO_USER"

step "6. App"
[[ -x "$APP_DIR/venv/bin/python" ]] || python3 -m venv --system-site-packages "$APP_DIR/venv"
# Build from a copy, so no root-owned build files land in the checkout.
build="$(mktemp -d)"
trap 'rm -rf "$build"' EXIT
cp -r "$REPO/pyproject.toml" "$REPO/README.md" "$REPO/src" "$build/"
"$APP_DIR/venv/bin/pip" install --quiet --disable-pip-version-check "$build"
for sound in "$REPO"/sounds/*.wav; do
    install_file "$sound" "$APP_DIR/sounds/$(basename "$sound")"
done

step "7. Config"
if [[ ! -e /etc/retropi/config.toml ]]; then
    install -D -m 644 "$REPO/config.toml" /etc/retropi/config.toml
    echo "installed /etc/retropi/config.toml"
elif ! cmp -s "$REPO/config.toml" /etc/retropi/config.toml; then
    echo "kept your /etc/retropi/config.toml; compare with $REPO/config.toml for new keys"
fi

step "8. Playlist"
install_file "$REPO/stations.m3u" /var/lib/mpd/playlists/stations.m3u

step "9. Services"
systemctl daemon-reload
systemctl enable "${SERVICES[@]}"
if [[ $REBOOT -eq 0 ]]; then
    systemctl restart "${SERVICES[@]}"
else
    echo "boot config changed: services start after the reboot"
fi

step "10. Self-check"
aplay -l || true
amixer -c sndrpihifiberry scontrols || echo "no HiFiBerry card$([[ $REBOOT -eq 1 ]] && echo ' yet (expected before the reboot)')"
bluetoothctl show || true
for service in "${SERVICES[@]}"; do
    printf '%-16s %s\n' "$service" "$(systemctl is-active "$service" || true)"
done
wifi_permission="$(sudo -u "$RADIO_USER" nmcli -t general permissions |
    awk -F: '$1 == "org.freedesktop.NetworkManager.enable-disable-wifi" {print $2}')"
echo "nmcli radio wifi as $RADIO_USER: ${wifi_permission:-unknown} (needs: yes)"

if [[ $REBOOT -eq 1 ]]; then
    if [[ "${RETROPI_NO_REBOOT:-0}" == 1 ]]; then
        echo "reboot needed for the boot config"
    else
        echo "rebooting in 5 s for the boot config..."
        sleep 5
        reboot
    fi
fi
