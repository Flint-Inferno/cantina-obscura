#!/bin/bash
# fix_audio.sh — Check audio device and restart PipeWire (antiX/SysVinit)
# Logs to ~/fix_audio.log for troubleshooting.
# Note: dsp_driver=2 (SST) is permanently set via /etc/modprobe.d/audio-fix.conf

LOG="$HOME/fix_audio.log"
exec > >(tee -a "$LOG") 2>&1

echo ""
echo "══════════════════════════════════════════"
echo " Audio Restart  $(date '+%Y-%m-%d %H:%M:%S')"
echo "══════════════════════════════════════════"

# ── Check ALSA device ────────────────────────────────────────────────────────
echo "[1/2] Checking ALSA devices..."
aplay -l 2>&1
if aplay -l 2>/dev/null | grep -qi "cht\|max98090\|bytcr"; then
    echo "      ✓ Audio device found."
else
    echo "      ✗ Audio device not visible."
    echo "      Driver is set to dsp_driver=2 via /etc/modprobe.d/audio-fix.conf"
    echo "      If this persists after reboot, run: dmesg | grep -i sst"
fi

# ── Restart PipeWire (SysVinit / no systemctl) ───────────────────────────────
echo "[2/2] Restarting PipeWire..."
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"

pkill -x wireplumber 2>/dev/null
pkill -x pipewire-pulse 2>/dev/null
pkill -x pipewire 2>/dev/null
sleep 1

pipewire &>/dev/null &
sleep 0.5
pipewire-pulse &>/dev/null &
sleep 0.5
wireplumber &>/dev/null &

sleep 1
if pgrep -x pipewire >/dev/null; then
    echo "      ✓ PipeWire running."
else
    echo "      ✗ PipeWire did not start — check ~/.config/pipewire/"
fi

echo "──────────────────────────────────────────"
echo " Done. Log saved to: $LOG"
echo "──────────────────────────────────────────"
sleep 4
