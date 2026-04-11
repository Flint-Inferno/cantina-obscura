"""
Toy Pad runner — session-aware NFC URL launcher with tandem tag support.

States
------
  IDLE         All zones passive, accepting new scans.
  SINGLE       Center tag active; URL open; L/R zones deaf.
  SINGLE_CD    Center tag removed; countdown running; L/R still deaf.
  TANDEM_WAIT  One tandem tag on L or R; waiting for partner; center deaf.
  TANDEM       Both tandem tags present; tandem URL open; center deaf.
  TANDEM_CD    One or both tandem tags gone; countdown running; center deaf.
  LOCKOUT      Brief post-session cooldown before IDLE resumes.

Run with:     sudo python3 toypad_run.py
With editor:  sudo python3 toypad_run.py --editor
"""

import json
import os
import queue
import re
import subprocess
import sys
import termios
import threading
import time
import tty
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import usb.core
import toypad_lib as pad

FRONTEND_PORT = 8082
FRONTEND_HTML = Path(__file__).parent / 'runner_frontend.html'
MISSION_EDITOR_HTML = Path(__file__).parent / 'mission_editor.html'
CANTINA_REPO  = Path(__file__).parent / 'cantina-obscura'

TAGS_FILE    = Path(__file__).parent / 'tags.json'
PROFILES_DIR = Path(__file__).parent / 'led_profiles'


# ── Tag data ──────────────────────────────────────────────────────────────────

def load_tags():
    if not TAGS_FILE.exists():
        return {'tags': {}, 'tandem_pairs': []}
    data = json.load(open(TAGS_FILE))
    # Support old flat format: {uid: url}
    if isinstance(data, dict) and 'tags' not in data and 'tandem_pairs' not in data:
        return {'tags': data, 'tandem_pairs': []}
    return {'tags': data.get('tags', {}), 'tandem_pairs': data.get('tandem_pairs', [])}


def find_tandem_pair(uid_a, uid_b, pairs):
    for p in pairs:
        if set(p['tags']) == {uid_a, uid_b}:
            return p
    return None


def is_tandem_uid(uid, pairs):
    return any(uid in p['tags'] for p in pairs)


# ── Zone controller ───────────────────────────────────────────────────────────

class ZoneController:
    """Manages LED state for one pad zone via a background thread."""

    def __init__(self, dev, zone_id):
        self.dev     = dev
        self.zone_id = zone_id
        self._stop   = threading.Event()
        self._thread = None

    def start_passive(self):
        self._swap(threading.Thread(target=self._run_named, args=('passive',), daemon=True))

    def trigger_event(self, event_type):
        self._swap(threading.Thread(target=self._run_named, args=(event_type,), daemon=True))

    def trigger_event_then_hold(self, event_type, hold_cfg):
        """Run event animation, then run hold_cfg mode indefinitely (until swapped/stopped)."""
        self._swap(threading.Thread(
            target=self._run_event_then_hold, args=(event_type, hold_cfg), daemon=True
        ))

    def trigger_mode_cfg(self, mode_cfg, return_to_passive=False):
        """Run a mode config object directly (bypasses led_config lookup)."""
        self._swap(threading.Thread(
            target=self._run_direct, args=(mode_cfg, return_to_passive), daemon=True
        ))

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _swap(self, new_thread):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._stop.clear()
        self._thread = new_thread
        new_thread.start()

    def _run_named(self, event_type):
        cfg = pad.load_led_config()
        if event_type == 'passive':
            pad.run_passive(self.dev, self.zone_id, cfg, self._stop)
        else:
            zone_cfg = cfg['zones'].get(str(self.zone_id), {})
            mode_cfg = zone_cfg.get(event_type, {'mode': 'off'})
            pad.run_mode(self.dev, self.zone_id, mode_cfg, self._stop)
            if not self._stop.is_set():
                pad.run_passive(self.dev, self.zone_id, cfg, self._stop)

    def _run_event_then_hold(self, event_type, hold_cfg):
        cfg = pad.load_led_config()
        zone_cfg = cfg['zones'].get(str(self.zone_id), {})
        anim_cfg = zone_cfg.get(event_type, {'mode': 'off'})
        pad.run_mode(self.dev, self.zone_id, anim_cfg, self._stop)
        if not self._stop.is_set():
            pad.run_mode(self.dev, self.zone_id, hold_cfg, self._stop)
        if not self._stop.is_set():
            pad.run_passive(self.dev, self.zone_id, cfg, self._stop)

    def _run_direct(self, mode_cfg, return_to_passive):
        pad.run_mode(self.dev, self.zone_id, mode_cfg, self._stop)
        if return_to_passive and not self._stop.is_set():
            cfg = pad.load_led_config()
            pad.run_passive(self.dev, self.zone_id, cfg, self._stop)


# ── Runner ────────────────────────────────────────────────────────────────────

class ToyPadRunner:
    IDLE        = 'idle'
    SINGLE      = 'single'
    SINGLE_CD   = 'single_cd'
    TANDEM_WAIT = 'tandem_wait'
    TANDEM      = 'tandem'
    TANDEM_CD   = 'tandem_cd'
    LOCKOUT     = 'lockout'

    _EV_PLACED   = 'placed'
    _EV_REMOVED  = 'removed'
    _EV_COUNTDOWN = 'countdown'
    _EV_LOCKOUT  = 'lockout_end'

    def __init__(self, dev):
        self.dev   = dev
        self.state = self.IDLE
        self.zones = {
            pad.PAD_CENTER: ZoneController(dev, pad.PAD_CENTER),
            pad.PAD_LEFT:   ZoneController(dev, pad.PAD_LEFT),
            pad.PAD_RIGHT:  ZoneController(dev, pad.PAD_RIGHT),
        }
        # Real-time physical state: what UID is currently on each zone (None if empty)
        self.zone_tags    = {pad.PAD_CENTER: None, pad.PAD_LEFT: None, pad.PAD_RIGHT: None}
        # Session data persisted through countdown
        self.session_uid  = None   # UID for the active single session
        self.tandem_zones = {}     # {zone_id: uid} for the active tandem session
        self.tandem_pair  = None   # the pair dict {"tags": [...], "url": "..."}

        self._events   = queue.Queue()
        self._cd_lock  = threading.Lock()
        self._cd_timer = None
        self._loop_stop   = threading.Event()
        self._loop_thread = None

    # ── Config helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _cfg():
        return pad.load_led_config()

    def _sounds(self):
        return self._cfg().get('sounds', {})

    # ── Sound loop helpers ────────────────────────────────────────────────────

    def _start_sound_loop(self, path):
        """Start a looping sound (stopping any previous loop first)."""
        self._stop_sound_loop()
        if not path:
            return
        self._loop_stop.clear()
        self._loop_thread = threading.Thread(
            target=pad.play_ambient_loop,
            args=(path, self._loop_stop),
            daemon=True,
        )
        self._loop_thread.start()

    def _stop_sound_loop(self):
        self._loop_stop.set()
        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=1.0)
        self._loop_thread = None

    def _countdown_secs(self):
        return float(self._cfg().get('countdown_seconds', 5.0))

    def _lockout_secs(self):
        return float(self._cfg().get('lockout_seconds', 3.0))

    def _removal_cd(self):
        return self._cfg().get('removal_countdown', True)

    def _tag_on_pad_led(self, zone_id):
        """LED mode to hold while a tag is actively on the pad. None = return to passive."""
        zone_cfg = self._cfg().get('zones', {}).get(str(zone_id), {})
        led = zone_cfg.get('tag_on_pad')
        if led and led.get('mode', 'off') != 'off':
            return led
        return None

    def _url_confirmed(self):
        """True if the briefing URL has been confirmed/opened. Base always True."""
        return True

    def _tandem_cfg(self):
        return self._cfg().get('tandem', {})

    def _waiting_mode(self):
        t = self._tandem_cfg()
        if 'waiting_mode' in t:
            return t['waiting_mode']
        c = t.get('waiting_color', {'r': 0, 'g': 80, 'b': 255})
        return {'mode': 'static', **c}

    def _cd_flash_mode(self, zone_id):
        t      = self._tandem_cfg()
        colors = t.get('countdown_flash_colors', {})
        c      = colors.get(str(zone_id)) or t.get('countdown_flash_color', {'r': 255, 'g': 100, 'b': 0})
        return {
            'mode': 'flash_loop',
            'on':   t.get('countdown_flash_on',  0.25),
            'off':  t.get('countdown_flash_off', 0.25),
            **c,
        }

    def _cd_fade_mode(self):
        t = self._tandem_cfg()
        c = t.get('countdown_fade_color', {'r': 0, 'g': 80, 'b': 255})
        return {'mode': 'fade_out', 'duration': self._countdown_secs(), **c}

    def _lockout_led_cfg(self):
        return self._cfg().get('lockout', {'mode': 'breathe', 'r': 180, 'g': 0, 'b': 0, 'speed': 1})

    # ── Timer helpers ─────────────────────────────────────────────────────────

    def _start_countdown(self):
        with self._cd_lock:
            if self._cd_timer:
                self._cd_timer.cancel()
            t = threading.Timer(
                self._countdown_secs(),
                lambda: self._events.put((self._EV_COUNTDOWN, None, None)),
            )
            t.daemon = True
            t.start()
            self._cd_timer = t

    def _cancel_countdown(self):
        with self._cd_lock:
            if self._cd_timer:
                self._cd_timer.cancel()
                self._cd_timer = None

    def _start_lockout(self):
        t = threading.Timer(
            self._lockout_secs(),
            lambda: self._events.put((self._EV_LOCKOUT, None, None)),
        )
        t.daemon = True
        t.start()

    # ── State actions ─────────────────────────────────────────────────────────

    def _go_idle(self):
        self._stop_sound_loop()
        self._cancel_countdown()
        self.state       = self.IDLE
        self.session_uid = None
        self.tandem_pair = None
        self.tandem_zones.clear()
        self.zone_tags   = {pad.PAD_CENTER: None, pad.PAD_LEFT: None, pad.PAD_RIGHT: None}
        for z in self.zones.values():
            z.start_passive()

    def _session_end(self):
        """Countdown expired — close browser, enter brief lockout."""
        self._enter_lockout(auto_expire=True)

    def _enter_lockout(self, auto_expire=True, close_browser=True):
        """Enter LOCKOUT state. If auto_expire is False, stay locked until force_idle.
        If close_browser is False, leave any open briefing tab alone."""
        self._stop_sound_loop()
        self._cancel_countdown()
        if close_browser:
            pad.play_sound(self._sounds().get('page_close'))
            self._close_url()
        self.state       = self.LOCKOUT
        self.session_uid = None
        self.tandem_pair = None
        self.tandem_zones.clear()
        self.zone_tags   = {pad.PAD_CENTER: None, pad.PAD_LEFT: None, pad.PAD_RIGHT: None}
        lockout_led = self._lockout_led_cfg()
        for z in self.zones.values():
            z.trigger_mode_cfg(lockout_led)
        pad.play_sound(self._sounds().get('lockout_start'))
        if auto_expire:
            self._start_lockout()

    # ── Event loop ────────────────────────────────────────────────────────────

    def run(self):
        for z in self.zones.values():
            z.start_passive()

        threading.Thread(target=self._dispatch_loop, daemon=True).start()

        cfg = self._cfg()
        ambient_stop = threading.Event()
        if cfg.get('sounds', {}).get('ambient'):
            threading.Thread(
                target=pad.play_ambient_loop,
                args=(cfg['sounds']['ambient'], ambient_stop),
                daemon=True,
            ).start()

        print("Pad ready. Place a tag on any zone. (Ctrl-C to stop)\n")

        try:
            while True:
                try:
                    data = self.dev.read(0x81, 32, timeout=500)
                except usb.core.USBError:
                    continue
                if not data or data[0] != 0x56:
                    continue
                zone_id = data[2]
                placed  = (data[5] == 0x00)
                uid     = '-'.join(f'{b:02X}' for b in data[6:13])
                if zone_id not in self.zones:
                    continue
                ev = self._EV_PLACED if placed else self._EV_REMOVED
                self._events.put((ev, zone_id, uid))
        except KeyboardInterrupt:
            print("\nShutting down.")
            ambient_stop.set()
            self._stop_sound_loop()
            for z in self.zones.values():
                z.stop()
            pad.set_color(self.dev, pad.PAD_ALL, 0, 0, 0)

    def _dispatch_loop(self):
        while True:
            ev, zone_id, uid = self._events.get()
            if ev is None:
                break  # stop signal
            if   ev == self._EV_PLACED:    self._on_placed(zone_id, uid)
            elif ev == self._EV_REMOVED:   self._on_removed(zone_id, uid)
            elif ev == self._EV_COUNTDOWN: self._on_countdown()
            elif ev == self._EV_LOCKOUT:
                self.state = self.IDLE
                for z in self.zones.values():
                    z.start_passive()
                self._log("Ready.")

    # ── Overridable hooks (subclass for dry-run / live-preview) ──────────────

    def _log(self, msg):
        print(msg)

    def _open_url(self, url):
        pad.open_url_tab(url)

    def _close_url(self):
        pad.close_briefing_tab()

    def _on_focus_briefing(self):
        """Called when the kiosk/briefing window should come to the front."""
        pass

    def _on_focus_terminal(self):
        """Called when the terminal window should come to the front."""
        pass

    # ── Placed handler ────────────────────────────────────────────────────────

    def _on_placed(self, zone_id, uid):
        td     = load_tags()
        pairs  = td['tandem_pairs']
        tags   = td['tags']
        sounds = self._cfg().get('sounds', {})

        if self.state == self.IDLE:
            if zone_id == pad.PAD_CENTER:
                url = tags.get(uid)
                if url:
                    self.zone_tags[zone_id] = uid
                    self.session_uid = uid
                    self.state = self.SINGLE
                    active_led = self._tag_on_pad_led(zone_id)
                    if active_led:
                        self.zones[zone_id].trigger_event_then_hold('match', active_led)
                    else:
                        self.zones[zone_id].trigger_event('match')
                    pad.play_sound(sounds.get('match'))
                    pad.play_sound(sounds.get('page_open'))
                    self._start_sound_loop(sounds.get('single_loop'))
                    self._open_url(url)
                    self._on_focus_briefing()
                    self._log(f"[SINGLE] {uid} → {url}")
                else:
                    self.zones[zone_id].trigger_event('no_match')
                    pad.play_sound(sounds.get('no_match'))
                    self._set_invalid_scan(zone_id)
                    self._log(f"[IDLE] Center: {uid} not found")
            else:
                if is_tandem_uid(uid, pairs):
                    self.zone_tags[zone_id] = uid
                    self.state = self.TANDEM_WAIT
                    self.zones[zone_id].trigger_mode_cfg(self._waiting_mode())
                    pad.play_sound(sounds.get('tandem_first'))
                    self._start_sound_loop(sounds.get('tandem_wait_loop'))
                    self._log(f"[TANDEM_WAIT] {uid} on zone {zone_id}")
                else:
                    self.zones[zone_id].trigger_event('no_match')
                    pad.play_sound(sounds.get('no_match'))
                    self._set_invalid_scan(zone_id)
                    self._log(f"[IDLE] L/R: {uid} not a tandem tag")

        elif self.state == self.SINGLE:
            pass  # L/R deaf; center already occupied

        elif self.state == self.SINGLE_CD:
            if zone_id == pad.PAD_CENTER and uid == self.session_uid:
                self._cancel_countdown()
                self._stop_sound_loop()
                self.zone_tags[zone_id] = uid
                self.state = self.SINGLE
                active_led = self._tag_on_pad_led(zone_id)
                if active_led:
                    self.zones[zone_id].trigger_event_then_hold('match', active_led)
                else:
                    self.zones[zone_id].trigger_event('match')
                pad.play_sound(sounds.get('session_restore'))
                self._start_sound_loop(sounds.get('single_loop'))
                self._on_focus_briefing()
                self._log(f"[SINGLE restored] {uid}")
            # Different tag or wrong zone during countdown: ignore

        elif self.state == self.TANDEM_WAIT:
            if zone_id == pad.PAD_CENTER:
                pass  # center deaf
            else:
                waiting_zone = next(
                    (z for z in (pad.PAD_LEFT, pad.PAD_RIGHT) if self.zone_tags[z] is not None),
                    None,
                )
                if waiting_zone is None or zone_id == waiting_zone:
                    return
                waiting_uid = self.zone_tags[waiting_zone]
                pair = find_tandem_pair(uid, waiting_uid, pairs)
                if pair:
                    self.zone_tags[zone_id] = uid
                    self.tandem_zones = {waiting_zone: waiting_uid, zone_id: uid}
                    self.tandem_pair  = pair
                    self.state = self.TANDEM
                    self._stop_sound_loop()
                    for z in (waiting_zone, zone_id):
                        active_led = self._tag_on_pad_led(z)
                        if active_led:
                            self.zones[z].trigger_event_then_hold('match', active_led)
                        else:
                            self.zones[z].trigger_event('match')
                    pad.play_sound(sounds.get('tandem_match'))
                    pad.play_sound(sounds.get('page_open'))
                    self._start_sound_loop(sounds.get('tandem_loop'))
                    self._open_url(pair['url'])
                    self._on_focus_briefing()
                    self._log(f"[TANDEM] {waiting_uid} + {uid} → {pair['url']}")
                else:
                    self.zones[zone_id].trigger_event('no_match')
                    pad.play_sound(sounds.get('no_match'))
                    self._set_invalid_scan(zone_id)
                    self._log(f"[TANDEM_WAIT] wrong tag: {uid}")

        elif self.state == self.TANDEM:
            pass  # center deaf; tandem zones occupied

        elif self.state == self.TANDEM_CD:
            if zone_id == pad.PAD_CENTER:
                pass  # center deaf
            elif zone_id in self.tandem_zones and uid == self.tandem_zones[zone_id]:
                self.zone_tags[zone_id] = uid
                # Check if both tandem tags are back
                if all(self.zone_tags[z] == u for z, u in self.tandem_zones.items()):
                    self._cancel_countdown()
                    self._stop_sound_loop()
                    self.state = self.TANDEM
                    for z in self.tandem_zones:
                        active_led = self._tag_on_pad_led(z)
                        if active_led:
                            self.zones[z].trigger_event_then_hold('match', active_led)
                        else:
                            self.zones[z].trigger_event('match')
                    pad.play_sound(sounds.get('session_restore'))
                    self._start_sound_loop(sounds.get('tandem_loop'))
                    self._on_focus_briefing()
                    self._log("[TANDEM restored]")
                else:
                    # One tag back — show waiting color, countdown still running
                    self.zones[zone_id].trigger_mode_cfg(self._waiting_mode())
                    self._log(f"[TANDEM_CD] {uid} returned, waiting for partner")

        elif self.state == self.LOCKOUT:
            pass

    # ── Removed handler ───────────────────────────────────────────────────────

    def _on_removed(self, zone_id, uid):
        if self.state == self.IDLE:
            pass

        elif self.state == self.SINGLE:
            if zone_id == pad.PAD_CENTER:
                self.zone_tags[zone_id] = None
                if not self._url_confirmed():
                    self._close_url()
                    self._go_idle()
                    self._log(f"[SINGLE] {uid} removed before confirm, back to idle")
                elif self._removal_cd():
                    sounds = self._sounds()
                    self.state = self.SINGLE_CD
                    self._start_countdown()
                    self.zones[zone_id].trigger_mode_cfg(self._cd_flash_mode(zone_id))
                    pad.play_sound(sounds.get('countdown_start'))
                    self._start_sound_loop(sounds.get('countdown_loop'))
                    self._on_focus_terminal()
                    self._log(f"[SINGLE_CD] {uid} removed, countdown started")
                else:
                    self._session_end()

        elif self.state == self.SINGLE_CD:
            pass  # already counting down

        elif self.state == self.TANDEM_WAIT:
            if zone_id in (pad.PAD_LEFT, pad.PAD_RIGHT) and self.zone_tags.get(zone_id) == uid:
                self.zone_tags[zone_id] = None
                self._go_idle()
                self._log("[TANDEM_WAIT] tag removed, back to idle")

        elif self.state == self.TANDEM:
            if zone_id in self.tandem_zones:
                self.zone_tags[zone_id] = None
                if not self._url_confirmed():
                    self._close_url()
                    self._stop_sound_loop()
                    still_zone = next((z for z in self.tandem_zones if z != zone_id), None)
                    self.state = self.TANDEM_WAIT
                    self.tandem_pair = None
                    self.tandem_zones.clear()
                    if still_zone is not None:
                        self.zones[still_zone].trigger_mode_cfg(self._waiting_mode())
                    self.zones[zone_id].start_passive()
                    self._start_sound_loop(self._sounds().get('tandem_wait_loop'))
                    self._log(f"[TANDEM_WAIT] {uid} removed before confirm — still waiting for partner")
                elif self._removal_cd():
                    sounds = self._sounds()
                    still_zone = next(
                        (z for z in self.tandem_zones if z != zone_id), None
                    )
                    self.state = self.TANDEM_CD
                    self._start_countdown()
                    self.zones[zone_id].trigger_mode_cfg(self._cd_flash_mode(zone_id))
                    if still_zone is not None:
                        self.zones[still_zone].trigger_mode_cfg(self._cd_fade_mode())
                    pad.play_sound(sounds.get('countdown_start'))
                    self._start_sound_loop(sounds.get('countdown_loop'))
                    self._on_focus_terminal()
                    self._log(f"[TANDEM_CD] {uid} removed, countdown started")
                else:
                    self._session_end()

        elif self.state == self.TANDEM_CD:
            if zone_id in self.tandem_zones and self.zone_tags.get(zone_id) is not None:
                # A tag that had returned is now gone again — sync to flash
                self.zone_tags[zone_id] = None
                self.zones[zone_id].trigger_mode_cfg(self._cd_flash_mode(zone_id))
                self._log(f"[TANDEM_CD] {uid} removed again, both zones flashing")

        elif self.state == self.LOCKOUT:
            pass

    # ── Countdown handler ─────────────────────────────────────────────────────

    def _on_countdown(self):
        if self.state in (self.SINGLE_CD, self.TANDEM_CD):
            self._log(f"[{self.state.upper()}] Countdown expired — closing session")
            self._session_end()


# ── Frontend runner ───────────────────────────────────────────────────────────

class FrontendRunner(ToyPadRunner):
    """ToyPadRunner subclass that feeds the web frontend with live state."""

    def __init__(self, dev, shared, lock):
        super().__init__(dev)
        self._shared  = shared
        self._lock    = lock
        self._log_seq = 0

    def _log(self, msg):
        print(msg)
        self._log_seq += 1
        with self._lock:
            self._shared['log'].append({'seq': self._log_seq, 'msg': msg})
            if len(self._shared['log']) > 200:
                self._shared['log'] = self._shared['log'][-100:]
            self._shared['state']     = self.state
            self._shared['zone_tags'] = {str(k): v for k, v in self.zone_tags.items()}

    def _set_invalid_scan(self, zone_id):
        with self._lock:
            self._shared['invalid_scan'] = {'zone': str(zone_id), 'ts': time.time()}

    def _open_url(self, url):
        with self._lock:
            self._shared['pending_url']   = url
            self._shared['briefing_url']  = url
            self._shared['is_tandem']     = (self.state == self.TANDEM)
            self._shared['session_start'] = time.time()
        # Tab opens only after the frontend sends confirm_open

    def _close_url(self):
        with self._lock:
            was_pending = self._shared['pending_url'] is not None
            self._shared['pending_url']   = None
            self._shared['briefing_url']  = None
            self._shared['is_tandem']     = False
            self._shared['session_start'] = None
        if not was_pending:
            pad.close_briefing_tab()

    def _on_focus_briefing(self):
        with self._lock:
            pending = self._shared['pending_url']
        if pending:
            return  # tab not open yet; frontend drives the confirm
        def _do():
            time.sleep(0.5)
            pad.focus_briefing_tab()
        threading.Thread(target=_do, daemon=True).start()

    def _url_confirmed(self):
        with self._lock:
            return (self._shared['pending_url'] is None
                    and self._shared['briefing_url'] is not None)

    def _on_focus_terminal(self):
        pad.focus_frontend()

    def _start_countdown(self):
        super()._start_countdown()
        with self._lock:
            self._shared['countdown_start'] = time.time()
            self._shared['countdown_total'] = self._countdown_secs()

    def _cancel_countdown(self):
        super()._cancel_countdown()
        with self._lock:
            self._shared['countdown_start'] = None
            self._shared['countdown_total'] = None

    def _session_end(self):
        super()._session_end()
        with self._lock:
            self._shared['countdown_start'] = None
            self._shared['countdown_total'] = None
            self._shared['pending_url']     = None
            self._shared['briefing_url']    = None
            self._shared['session_start']   = None
            self._shared['state']           = self.state
            self._shared['zone_tags']       = {str(k): v for k, v in self.zone_tags.items()}

    def force_lockout(self):
        self._events.put(('_force_lockout', None, None))

    def force_idle(self):
        self._events.put(('_force_idle', None, None))

    def _dispatch_loop(self):
        while True:
            ev, zone_id, uid = self._events.get()
            if ev is None:
                break
            elif ev == '_force_idle':
                self._go_idle()
                self._log("[CMD] Forced idle.")
            elif ev == '_force_lockout':
                self._enter_lockout(auto_expire=False, close_browser=False)
                self._log("[CMD] Manual lockout — use /unlock to restore.")
            elif ev == self._EV_PLACED:    self._on_placed(zone_id, uid)
            elif ev == self._EV_REMOVED:   self._on_removed(zone_id, uid)
            elif ev == self._EV_COUNTDOWN: self._on_countdown()
            elif ev == self._EV_LOCKOUT:
                self.state = self.IDLE
                for z in self.zones.values():
                    z.start_passive()
                self._log("Ready.")


# ── Frontend HTTP server ───────────────────────────────────────────────────────

class FrontendHandler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass  # suppress access log

    def do_GET(self):
        p = self.path.split('?')[0]
        if   p == '/':                          self._serve_html()
        elif p == '/api/status':               self._serve_status()
        elif p == '/api/tags':                 self._serve_tags()
        elif p == '/AurebeshAF-Canon.otf':     self._serve_font()
        elif p.startswith('/sounds/'):         self._serve_sound(p[len('/sounds/'):])
        elif p == '/mission-editor':           self._serve_mission_editor()
        elif p == '/api/mission':              self._serve_mission_file()
        else: self.send_error(404)

    def do_POST(self):
        if   self.path == '/api/command':      self._handle_command()
        elif self.path == '/api/mission':      self._save_mission_file()
        else: self.send_error(404)

    def _serve_html(self):
        try:
            body = FRONTEND_HTML.read_bytes()
            ctype = 'text/html; charset=utf-8'
        except FileNotFoundError:
            body  = b'<h1>runner_frontend.html not found</h1>'
            ctype = 'text/html'
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def _serve_font(self):
        font_path = Path(__file__).parent / 'AurebeshAF-Canon.otf'
        try:
            body = font_path.read_bytes()
        except FileNotFoundError:
            self.send_error(404); return
        self.send_response(200)
        self.send_header('Content-Type', 'font/otf')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def _serve_sound(self, key):
        cfg      = pad.load_led_config()
        path_str = cfg.get('sounds', {}).get(key, '')
        if not path_str:
            self.send_error(404); return
        path = Path(path_str)
        if not path.exists():
            self.send_error(404); return
        ctype_map = {'.mp3': 'audio/mpeg', '.wav': 'audio/wav',
                     '.ogg': 'audio/ogg',  '.flac': 'audio/flac'}
        ctype = ctype_map.get(path.suffix.lower(), 'application/octet-stream')
        try:
            body = path.read_bytes()
        except Exception:
            self.send_error(500); return
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', len(body))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def _serve_status(self):
        with self.server._lock:
            out = {
                'state':           self.server._shared['state'],
                'zone_tags':       dict(self.server._shared['zone_tags']),
                'pending_url':     self.server._shared['pending_url'],
                'briefing_url':    self.server._shared['briefing_url'],
                'is_tandem':       self.server._shared['is_tandem'],
                'countdown_start': self.server._shared['countdown_start'],
                'countdown_total': self.server._shared['countdown_total'],
                'session_start':   self.server._shared['session_start'],
                'pad_connected':   self.server._shared['pad_connected'],
                'log':             list(self.server._shared['log']),
                'invalid_scan':    self.server._shared['invalid_scan'],
            }
        self._json(out)

    def _serve_tags(self):
        tags_file = Path(__file__).parent / 'tags.json'
        if tags_file.exists():
            raw = json.loads(tags_file.read_text())
        else:
            raw = {'tags': {}, 'tandem_pairs': []}
        self._json({
            'tags':         [{'uid': k, 'url': v} for k, v in raw.get('tags', {}).items()],
            'tandem_pairs': raw.get('tandem_pairs', []),
        })

    def _serve_mission_editor(self):
        try:
            body  = MISSION_EDITOR_HTML.read_bytes()
            ctype = 'text/html; charset=utf-8'
        except FileNotFoundError:
            body  = b'<h1>mission_editor.html not found</h1>'
            ctype = 'text/html'
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def _serve_mission_file(self):
        qs     = parse_qs(urlparse(self.path).query)
        fname  = (qs.get('file', [''])[0]).strip()
        # Reject anything that looks like path traversal
        if not fname.endswith('.html') or '/' in fname or '..' in fname:
            self.send_error(400, 'Invalid filename'); return
        target = CANTINA_REPO / fname
        template = CANTINA_REPO / 'mission-template.html'
        if target.exists():
            self._json({'exists': True,  'content': target.read_text(encoding='utf-8')})
        elif template.exists():
            self._json({'exists': False, 'content': template.read_text(encoding='utf-8')})
        else:
            self._json({'exists': False, 'content': ''})

    def _save_mission_file(self):
        length = int(self.headers.get('Content-Length', 0))
        if not length:
            self.send_error(400, 'Empty body'); return
        body = json.loads(self.rfile.read(length))
        fname   = (body.get('file', '')).strip()
        content = body.get('content', '')
        if not fname.endswith('.html') or '/' in fname or '..' in fname:
            self._json({'ok': False, 'error': 'Invalid filename'}); return
        target = CANTINA_REPO / fname
        try:
            target.write_text(content, encoding='utf-8')
        except Exception as e:
            self._json({'ok': False, 'error': f'Write failed: {e}'}); return
        # Commit and push as the real user
        sudo_user = os.environ.get('SUDO_USER', '')
        home      = f'/home/{sudo_user}' if sudo_user else os.path.expanduser('~')
        def _git(args):
            cmd = (['sudo', '-u', sudo_user, 'env', f'HOME={home}', 'git'] + args
                   if sudo_user else ['git'] + args)
            return subprocess.run(cmd, capture_output=True, text=True, cwd=str(CANTINA_REPO))
        _git(['add', fname])
        msg = body.get('message') or f'Update {fname}'
        r   = _git(['commit', '-m', msg])
        if r.returncode != 0 and 'nothing to commit' not in r.stdout + r.stderr:
            self._json({'ok': False, 'error': r.stderr.strip()}); return
        r = _git(['push'])
        if r.returncode != 0:
            self._json({'ok': False, 'error': r.stderr.strip()}); return
        self._json({'ok': True})

    def _handle_command(self):
        length = int(self.headers.get('Content-Length', 0))
        body   = json.loads(self.rfile.read(length)) if length else {}
        cmd    = body.get('cmd', '')
        runner = self.server._runner
        if runner:
            if   cmd == 'lockout': runner.force_lockout()
            elif cmd == 'unlock':  runner.force_idle()
            elif cmd == 'confirm_open':
                with self.server._lock:
                    url = self.server._shared.get('pending_url')
                    self.server._shared['pending_url'] = None
                if url:
                    pad.open_url_tab(url)
                    def _focus():
                        time.sleep(0.5)
                        pad.focus_briefing_tab()
                    threading.Thread(target=_focus, daemon=True).start()
            # 'reload' is a no-op — config files are read fresh on every scan
        self._json({'ok': True})


# ── Profile selection ─────────────────────────────────────────────────────────

def _pick_profile():
    """List saved LED/sound profiles and prompt which to use this session."""
    profiles = ['Default']
    if PROFILES_DIR.exists():
        profiles += sorted(p.stem for p in PROFILES_DIR.glob('*.json'))

    print("LED / Sound profiles:")
    for i, name in enumerate(profiles, 1):
        print(f"  {i}. {name}")
    print()

    while True:
        raw = input(f"Select profile [1-{len(profiles)}, Enter = 1]: ").strip()
        if not raw:
            idx = 0
            break
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(profiles):
                break
        print(f"  Enter a number between 1 and {len(profiles)}.")

    name = profiles[idx]
    print(f"Profile: {name}\n")

    if name != 'Default':
        cfg = json.loads((PROFILES_DIR / f'{name}.json').read_text())
        # If the profile has no sounds, pull them from led_config.json so
        # sounds saved via "Save Config" still work when a profile is active.
        if not cfg.get('sounds'):
            base = pad.load_led_config()
            if base.get('sounds'):
                cfg['sounds'] = base['sounds']
        pad.set_config_override(cfg)


# ── Loading sequence ──────────────────────────────────────────────────────────

def _loading_sequence():
    width = 38
    print()
    print("  Establishing secure connection...")
    time.sleep(0.4)

    for i in range(width + 1):
        filled = '\u2588' * i
        empty  = '\u2591' * (width - i)
        pct    = int(i / width * 100)
        print(f'\r  [{filled}{empty}] {pct:3d}%', end='', flush=True)
        time.sleep(0.06 if i < int(width * 0.85) else 0.18)

    print('\n')
    print("  Secure connection found.")
    print("  Press any key to continue...", end='', flush=True)

    try:
        fd  = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except Exception:
        input()

    print('\n')


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    _pick_profile()

    dev = pad.setup_pad()
    pad.startup_flash(dev)

    # Shared state for the web frontend
    shared = {
        'state':           'idle',
        'zone_tags':       {'1': None, '2': None, '3': None},
        'pending_url':     None,
        'briefing_url':    None,
        'is_tandem':       False,
        'countdown_start': None,
        'countdown_total': None,
        'session_start':   None,
        'pad_connected':   True,
        'log':             [],
        'invalid_scan':    None,
    }
    shared_lock = threading.Lock()

    # Start frontend HTTP server
    frontend_server = HTTPServer(('', FRONTEND_PORT), FrontendHandler)
    frontend_server._shared  = shared
    frontend_server._lock    = shared_lock
    frontend_server._runner  = None
    threading.Thread(target=frontend_server.serve_forever, daemon=True).start()
    print(f"Frontend running at http://localhost:{FRONTEND_PORT}\n")
    _loading_sequence()
    threading.Thread(target=pad.open_frontend_kiosk, args=(FRONTEND_PORT,), daemon=True).start()

    if '--editor' in sys.argv:
        from toypad_led_editor import start_server
        threading.Thread(
            target=start_server, args=(dev,), kwargs={'open_browser': True}, daemon=True
        ).start()
        print("LED editor running at http://localhost:8080\n")

    runner = FrontendRunner(dev, shared, shared_lock)
    frontend_server._runner = runner
    runner.run()


if __name__ == '__main__':
    main()
