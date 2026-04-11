"""
Shared USB helpers for the Lego Dimensions Toy Pad.
Imported by toypad_run.py, toypad_add.py, and toypad_led_editor.py.
"""

import usb.core
import usb.util
import time
import math
import json
import os
import pwd
import subprocess
import threading
from pathlib import Path

VENDOR_ID  = 0x0e6f
PRODUCT_ID = 0x0241

KIOSK_PROFILE = '/tmp/toypad_kiosk_profile'

PAD_ALL    = 0
PAD_CENTER = 1
PAD_LEFT   = 2
PAD_RIGHT  = 3

INIT_CMD = [
    0x55, 0x0f, 0xb0, 0x01, 0x28, 0x63, 0x29, 0x20,
    0x4c, 0x45, 0x47, 0x4f, 0x20, 0x32, 0x30, 0x31,
    0x34, 0xf7, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
]

CONFIG_FILE = Path(__file__).parent / 'led_config.json'

_config_override = None  # set at session start by profile selection; never written to disk


def set_config_override(cfg):
    global _config_override
    _config_override = cfg

DEFAULT_CONFIG = {
    "global_passive": {"mode": "static", "r": 0, "g": 0, "b": 20},
    "zones": {
        "1": {
            "passive_override": None,
            "match":    {"mode": "flash", "r": 0,   "g": 255, "b": 0,   "count": 3, "on": 0.3, "off": 0.2},
            "no_match": {"mode": "flash", "r": 255, "g": 0,   "b": 0,   "count": 3, "on": 0.3, "off": 0.2},
        },
        "2": {
            "passive_override": None,
            "match":    {"mode": "flash", "r": 0,   "g": 255, "b": 0,   "count": 3, "on": 0.3, "off": 0.2},
            "no_match": {"mode": "flash", "r": 255, "g": 0,   "b": 0,   "count": 3, "on": 0.3, "off": 0.2},
        },
        "3": {
            "passive_override": None,
            "match":    {"mode": "flash", "r": 0,   "g": 255, "b": 0,   "count": 3, "on": 0.3, "off": 0.2},
            "no_match": {"mode": "flash", "r": 255, "g": 0,   "b": 0,   "count": 3, "on": 0.3, "off": 0.2},
        },
    },
    "zone_links": [],
}


# ── Config ────────────────────────────────────────────────────────────────────

def load_led_config():
    if _config_override is not None:
        return _config_override
    if not CONFIG_FILE.exists():
        return DEFAULT_CONFIG
    with open(CONFIG_FILE) as f:
        return json.load(f)


# ── Low-level USB helpers ─────────────────────────────────────────────────────

def _checksum(data):
    return sum(data) % 256

def _send(dev, payload):
    pkt = list(payload)
    pkt.append(_checksum(pkt))
    pkt += [0x00] * (32 - len(pkt))
    dev.write(1, pkt)


# ── LED control ───────────────────────────────────────────────────────────────

def set_color(dev, pad, r, g, b):
    _send(dev, [0x55, 0x06, 0xc0, 0x00, pad, r, g, b])

def flash_color(dev, pad, r, g, b, count=3, on_len=0.3, off_len=0.2):
    for _ in range(count):
        set_color(dev, pad, r, g, b)
        time.sleep(on_len)
        set_color(dev, pad, 0, 0, 0)
        time.sleep(off_len)


# ── Mode runners ──────────────────────────────────────────────────────────────

def _breathe_loop(dev, zone_id, cfg, stop_event):
    r, g, b = cfg.get('r', 0), cfg.get('g', 0), cfg.get('b', 255)
    speed    = cfg.get('speed', 2.0)
    steps    = 40
    interval = speed / (steps * 2)
    t = 0
    while not stop_event.is_set():
        brightness = (math.sin(math.pi * t / steps - math.pi / 2) + 1) / 2
        set_color(dev, zone_id,
                  int(r * brightness),
                  int(g * brightness),
                  int(b * brightness))
        t = (t + 1) % (steps * 2)
        if stop_event.wait(interval):
            break
    set_color(dev, zone_id, 0, 0, 0)

def _flash_forever_loop(dev, zone_id, cfg, stop_event):
    """Flash indefinitely until stop_event is set."""
    r       = cfg.get('r', 255)
    g       = cfg.get('g', 100)
    b       = cfg.get('b', 0)
    on_len  = cfg.get('on',  0.25)
    off_len = cfg.get('off', 0.25)
    while not stop_event.is_set():
        set_color(dev, zone_id, r, g, b)
        if stop_event.wait(on_len):
            break
        set_color(dev, zone_id, 0, 0, 0)
        if stop_event.wait(off_len):
            break
    set_color(dev, zone_id, 0, 0, 0)

def _fade_out_loop(dev, zone_id, cfg, stop_event):
    """Fade from a color to black over `duration` seconds."""
    r        = cfg.get('r', 0)
    g        = cfg.get('g', 80)
    b        = cfg.get('b', 255)
    duration = cfg.get('duration', 5.0)
    steps    = 50
    interval = duration / steps
    for i in range(steps):
        if stop_event.is_set():
            break
        factor = 1.0 - (i / steps)
        set_color(dev, zone_id, int(r * factor), int(g * factor), int(b * factor))
        if stop_event.wait(interval):
            break
    set_color(dev, zone_id, 0, 0, 0)

def _cycle_loop(dev, zone_id, cfg, stop_event):
    r_ceil = cfg.get('r', 255)
    g_ceil = cfg.get('g', 255)
    b_ceil = cfg.get('b', 255)
    speed    = cfg.get('speed', 3.0)
    steps    = 60
    interval = speed / steps
    t = 0
    while not stop_event.is_set():
        r = int(r_ceil * (math.sin(2 * math.pi * t / steps) + 1) / 2)
        g = int(g_ceil * (math.sin(2 * math.pi * t / steps + 2 * math.pi / 3) + 1) / 2)
        b = int(b_ceil * (math.sin(2 * math.pi * t / steps + 4 * math.pi / 3) + 1) / 2)
        set_color(dev, zone_id, r, g, b)
        t = (t + 1) % steps
        if stop_event.wait(interval):
            break
    set_color(dev, zone_id, 0, 0, 0)

def run_mode(dev, zone_id, mode_cfg, stop_event):
    """Run a single mode config on a zone. Blocks until complete or stop_event fires."""
    mode = mode_cfg.get('mode', 'off')

    if mode == 'off':
        set_color(dev, zone_id, 0, 0, 0)
        stop_event.wait()

    elif mode == 'static':
        set_color(dev, zone_id, mode_cfg.get('r', 0), mode_cfg.get('g', 0), mode_cfg.get('b', 0))
        stop_event.wait()

    elif mode == 'hold':
        set_color(dev, zone_id, mode_cfg.get('r', 0), mode_cfg.get('g', 0), mode_cfg.get('b', 0))
        stop_event.wait(mode_cfg.get('duration', 2.0))
        set_color(dev, zone_id, 0, 0, 0)

    elif mode == 'flash':
        r, g, b = mode_cfg.get('r', 0), mode_cfg.get('g', 255), mode_cfg.get('b', 0)
        count   = mode_cfg.get('count', 3)
        on_len  = mode_cfg.get('on', 0.3)
        off_len = mode_cfg.get('off', 0.2)
        for _ in range(count):
            if stop_event.is_set(): break
            set_color(dev, zone_id, r, g, b)
            if stop_event.wait(on_len): break
            set_color(dev, zone_id, 0, 0, 0)
            if stop_event.wait(off_len): break

    elif mode == 'breathe':
        _breathe_loop(dev, zone_id, mode_cfg, stop_event)

    elif mode == 'cycle':
        _cycle_loop(dev, zone_id, mode_cfg, stop_event)

    elif mode == 'flash_loop':
        _flash_forever_loop(dev, zone_id, mode_cfg, stop_event)

    elif mode == 'fade_out':
        _fade_out_loop(dev, zone_id, mode_cfg, stop_event)

def run_passive(dev, zone_id, cfg, stop_event):
    """Run the passive mode for a zone (uses override if set, else global)."""
    zone_passive = cfg['zones'].get(str(zone_id), {}).get('passive_override')
    passive_cfg  = zone_passive if zone_passive else cfg.get('global_passive', {'mode': 'off'})
    run_mode(dev, zone_id, passive_cfg, stop_event)


# ── Setup ─────────────────────────────────────────────────────────────────────

def setup_pad():
    dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
    if dev is None:
        raise RuntimeError("Toy Pad not found — check USB connection.")

    dev.reset()
    time.sleep(0.5)

    for cfg in dev:
        for intf in cfg:
            n = intf.bInterfaceNumber
            try:
                if dev.is_kernel_driver_active(n):
                    dev.detach_kernel_driver(n)
            except usb.core.USBError:
                pass

    try:
        dev.set_configuration()
    except usb.core.USBError as e:
        if e.errno != 16:
            raise

    usb.util.claim_interface(dev, 0)
    dev.write(1, INIT_CMD)
    time.sleep(0.1)
    return dev

def wait_for_tag(dev):
    """Block until a tag is placed. Returns (uid_string, pad_id)."""
    while True:
        try:
            data = dev.read(0x81, 32, timeout=500)
        except usb.core.USBError:
            continue
        if data[0] == 0x56 and data[5] == 0x00:
            uid    = '-'.join(f'{b:02X}' for b in data[6:13])
            pad_id = data[2]
            return uid, pad_id

def _as_user(cmd, popen=False):
    """Run cmd as SUDO_USER with X11 environment. Returns Popen if popen=True, else CompletedProcess."""
    sudo_user = os.environ.get('SUDO_USER')
    if sudo_user:
        display = os.environ.get('DISPLAY', ':0')
        xauth   = f'/home/{sudo_user}/.Xauthority'
        full = ['sudo', '-u', sudo_user, 'env',
                f'DISPLAY={display}', f'XAUTHORITY={xauth}',
                f'HOME=/home/{sudo_user}'] + cmd
    else:
        full = cmd
    if popen:
        return subprocess.Popen(full, stdin=subprocess.DEVNULL)
    return subprocess.run(full, capture_output=True, text=True)

def _get_firefox_wid():
    """Return the Firefox window ID as a hex string for wmctrl, or None."""
    r = _as_user(['xdotool', 'search', '--class', 'firefox'])
    lines = [l for l in r.stdout.strip().splitlines() if l]
    return hex(int(lines[0])) if lines else None

def _setup_kiosk_profile():
    """Create the kiosk Firefox profile with black about:blank and no extensions needed."""
    profile = Path(KIOSK_PROFILE)
    chrome  = profile / 'chrome'
    profile.mkdir(exist_ok=True)
    chrome.mkdir(exist_ok=True)

    (profile / 'user.js').write_text(
        'user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);\n'
    )
    (chrome / 'userContent.css').write_text(
        '@-moz-document url("about:blank") {\n'
        '  html, body { background-color: #000000 !important; }\n'
        '}\n'
    )

    # Ensure Firefox (running as real user) can write to the profile
    sudo_user = os.environ.get('SUDO_USER')
    if sudo_user:
        try:
            pw = pwd.getpwnam(sudo_user)
            for p in (profile, chrome, profile / 'user.js', chrome / 'userContent.css'):
                os.chown(p, pw.pw_uid, pw.pw_gid)
        except (KeyError, OSError):
            pass

def open_frontend_kiosk(port=8082):
    """Open the runner frontend in a kiosk Firefox window."""
    _setup_kiosk_profile()
    _as_user(['firefox', '--kiosk', '--profile', KIOSK_PROFILE,
              f'http://localhost:{port}'], popen=True)

def open_url_tab(url):
    """Open a URL in a new tab of the running kiosk Firefox instance."""
    _as_user(['firefox', '--profile', KIOSK_PROFILE, '--new-tab', url], popen=True)

def close_briefing_tab():
    """Switch to the last tab (briefing) and close it, returning to the frontend tab."""
    wid = _get_firefox_wid()
    if wid:
        subprocess.run(['wmctrl', '-i', '-a', wid], capture_output=True)
        time.sleep(0.1)
        _as_user(['xdotool', 'key', 'ctrl+9', 'ctrl+w'])

def focus_briefing_tab():
    """Switch to the last tab in Firefox (the briefing)."""
    wid = _get_firefox_wid()
    if wid:
        subprocess.run(['wmctrl', '-i', '-a', wid], capture_output=True)
        time.sleep(0.1)
        _as_user(['xdotool', 'key', 'ctrl+9'])

def focus_frontend():
    """Switch to the first tab in Firefox (the Cantina Obscura Terminal)."""
    wid = _get_firefox_wid()
    if wid:
        subprocess.run(['wmctrl', '-i', '-a', wid], capture_output=True)
        time.sleep(0.1)
        _as_user(['xdotool', 'key', 'ctrl+1'])

def _audio_cmd(path, loop=False):
    """Build an mpg123 command, dropping to the real user when running as root."""
    sudo_user = os.environ.get('SUDO_USER')
    username = sudo_user or os.environ.get('USER', '')
    cmd = ['mpg123', '-q']
    if loop:
        cmd += ['--loop', '-1']
    cmd.append(str(path))
    if os.geteuid() == 0 and username:
        try:
            uid = pwd.getpwnam(username).pw_uid
        except KeyError:
            uid = None
        runtime_dir = None
        if uid:
            for candidate in (f'/run/user/{uid}', f'/tmp/{uid}/.run'):
                if os.path.isdir(candidate):
                    runtime_dir = candidate
                    break
        env_vars = [f'HOME=/home/{username}']
        if runtime_dir:
            env_vars.append(f'XDG_RUNTIME_DIR={runtime_dir}')
        cmd = ['sudo', '-u', username, 'env'] + env_vars + cmd
    return cmd


def play_sound(path):
    """Play a sound file non-blocking. No-op if path is empty/None."""
    if not path:
        return
    try:
        subprocess.Popen(_audio_cmd(path),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


_loop_proc = None
_loop_lock = threading.Lock()


def play_ambient_loop(path, stop_event):
    """Loop a sound file until stop_event is set. Intended for a daemon thread."""
    global _loop_proc
    if not path:
        return
    try:
        proc = subprocess.Popen(_audio_cmd(path, loop=True),
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with _loop_lock:
            _loop_proc = proc
        stop_event.wait()
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
    except Exception:
        pass
    finally:
        with _loop_lock:
            _loop_proc = None


def startup_flash(dev):
    """Brief blue flash across all pads to confirm the pad is connected."""
    for pad in (PAD_LEFT, PAD_CENTER, PAD_RIGHT):
        set_color(dev, pad, 0, 0, 60)
    time.sleep(0.8)
    set_color(dev, PAD_ALL, 0, 0, 0)
