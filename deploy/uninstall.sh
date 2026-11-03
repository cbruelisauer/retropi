#!/bin/bash
# Stop and remove retropi. Leaves /etc/retropi/ (your settings), the apt
# packages, /etc/asound.conf, /etc/mpd.conf, /etc/bluetooth/main.conf and
# the boot config in place.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "run as root: sudo $0" >&2
    exit 1
fi

systemctl disable --now retropi bluealsa-aplay bluealsa || true
rm -f /etc/systemd/system/retropi.service \
    /etc/systemd/system/bluealsa.service.d/retropi.conf \
    /etc/systemd/system/bluealsa-aplay.service.d/retropi.conf \
    /etc/polkit-1/rules.d/50-retropi-wifi.rules
rm -rf /opt/retropi
systemctl daemon-reload
echo "retropi removed; settings kept in /etc/retropi/"
