"""
LED behavior editor for the Lego Dimensions Toy Pad.

Standalone:        sudo python3 toypad_led_editor.py
Via runner:        sudo python3 toypad_run.py --editor

Opens http://localhost:8080 in your browser.
If the pad is not connected, SVG preview still works.
"""

import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import toypad_lib as pad

CONFIG_FILE   = Path(__file__).parent / 'led_config.json'
PROFILES_DIR  = Path(__file__).parent / 'led_profiles'
DEFAULT_PROFILE_NAME = 'Default'
DEFAULT_PROFILE = {
    "global_passive": {"mode": "static", "r": 66, "g": 66, "b": 66},
    "zones": {
        "1": {
            "passive_override": {"mode": "breathe", "r": 154, "g": 153, "b": 150, "speed": 4},
            "match":    {"mode": "flash", "r": 0,   "g": 255, "b": 0,   "count": 3, "on": 0.3, "off": 0.2},
            "no_match": {"mode": "flash", "r": 255, "g": 0,   "b": 0,   "count": 3, "on": 0.3, "off": 0.2},
            "tag_on_pad": {"mode": "off"}
        },
        "2": {
            "passive_override": {"mode": "cycle", "r": 255, "g": 255, "b": 255, "speed": 2},
            "match":    {"mode": "flash", "r": 0,   "g": 255, "b": 0,   "count": 3, "on": 0.3, "off": 0.2},
            "no_match": {"mode": "flash", "r": 255, "g": 0,   "b": 0,   "count": 3, "on": 0.3, "off": 0.2},
            "tag_on_pad": {"mode": "off"}
        },
        "3": {
            "passive_override": None,
            "match":    {"mode": "flash", "r": 0,   "g": 255, "b": 0,   "count": 3, "on": 0.3, "off": 0.2},
            "no_match": {"mode": "flash", "r": 255, "g": 0,   "b": 0,   "count": 3, "on": 0.3, "off": 0.2},
            "tag_on_pad": {"mode": "off"}
        }
    },
    "zone_links": [1, 2, 3],
    "sounds": {},
    "removal_countdown": True,
    "countdown_seconds": 5,
    "lockout_seconds": 3,
    "lockout": {"mode": "breathe", "r": 180, "g": 0, "b": 0, "speed": 1},
    "tandem": {
        "waiting_mode":          {"mode": "static", "r": 0, "g": 80, "b": 255},
        "countdown_flash_colors": {"1": {"r": 255, "g": 100, "b": 0}, "2": {"r": 255, "g": 100, "b": 0}, "3": {"r": 255, "g": 100, "b": 0}},
        "countdown_flash_on":    0.25,
        "countdown_flash_off":   0.25,
        "countdown_fade_color":  {"r": 0, "g": 80, "b": 255},
    }
}


def list_profiles():
    names = [DEFAULT_PROFILE_NAME]
    if PROFILES_DIR.exists():
        names += sorted(p.stem for p in PROFILES_DIR.glob('*.json'))
    return names


def get_profile(name):
    if name == DEFAULT_PROFILE_NAME:
        return DEFAULT_PROFILE
    return json.loads((PROFILES_DIR / f'{name}.json').read_text())


def save_profile(name, cfg):
    PROFILES_DIR.mkdir(exist_ok=True)
    (PROFILES_DIR / f'{name}.json').write_text(json.dumps(cfg, indent=2))


def delete_profile(name):
    (PROFILES_DIR / f'{name}.json').unlink()


# ── HTML page ─────────────────────────────────────────────────────────────────

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Toy Pad LED Editor</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#1a1a1a;color:#ddd;font-family:monospace;font-size:14px;padding:16px}
h1{font-size:18px;margin-bottom:4px}
.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.pad-status{font-size:12px;margin-top:4px}
.pad-status.on{color:#4f4}.pad-status.off{color:#f44}
button{background:#333;color:#ddd;border:1px solid #555;padding:6px 12px;cursor:pointer;font-family:monospace}
button:hover{background:#444}
button.primary{background:#2a5;color:#fff;border-color:#3b6}
button.primary:hover{background:#3b6}
button.active{background:#25a;border-color:#36b;color:#fff}
.profiles-bar{background:#222;border:1px solid #333;padding:10px 12px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.profiles-bar .bar-label{font-size:11px;color:#777;text-transform:uppercase;letter-spacing:1px;white-space:nowrap}
.saveas-row{display:none;background:#222;border:1px solid #333;border-top:none;padding:8px 12px;gap:8px;align-items:center;flex-wrap:wrap}
.main-tabs{display:flex;gap:0;margin-top:16px;border-bottom:2px solid #333}
.main-tab{padding:9px 24px;cursor:pointer;background:#222;border:1px solid #333;border-bottom:none;color:#888;font-size:13px;text-transform:uppercase;letter-spacing:1px;margin-bottom:-2px}
.main-tab:hover{color:#ccc;background:#252525}
.main-tab.active{background:#1a1a1a;border-color:#3b6;border-bottom-color:#1a1a1a;color:#4f4}
.main-tab-content{display:none;padding-top:16px}
.main-tab-content.active{display:block}
.section{background:#222;border:1px solid #333;padding:12px;margin-bottom:12px}
.section>h2{font-size:13px;margin-bottom:10px;color:#aaa;text-transform:uppercase;letter-spacing:1px}
.tabs{display:flex;gap:4px;margin-bottom:12px}
.tab{padding:6px 16px;cursor:pointer;background:#333;border:1px solid #444}
.tab.active{background:#2a5;border-color:#3b6;color:#fff}
.tab-content{display:none}.tab-content.active{display:block}
.field-row{display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap}
.field-row label{min-width:72px;color:#aaa}
select{background:#333;color:#ddd;border:1px solid #555;padding:4px 8px;font-family:monospace}
input[type="range"]{width:110px;accent-color:#3b6}
input[type="text"]{background:#333;color:#ddd;border:1px solid #555;padding:4px 8px;font-family:monospace}
.val{min-width:36px;color:#8cf;font-size:13px}
.sub{border-left:2px solid #333;padding-left:12px;margin:10px 0}
.sub>h3{font-size:12px;color:#777;text-transform:uppercase;margin-bottom:8px;letter-spacing:1px}
.mode-params{margin-top:6px}
.dim-warn{color:#f84;font-size:12px;margin-top:4px;display:none}
.override-row{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.override-body{display:none}.override-body.on{display:block}
.zone-tools{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.link-btns{display:flex;gap:6px;flex-wrap:wrap}
.link-btns button{font-size:12px;padding:4px 10px}
.sound-row{display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap}
.sound-lbl{min-width:158px;color:#ccc;font-size:13px}
.sound-note{color:#555;font-size:11px}
.footer{display:flex;gap:8px;justify-content:flex-end;margin-top:4px}
.modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:100}
.modal-bg.on{display:flex;align-items:center;justify-content:center}
.modal{background:#222;border:1px solid #444;padding:24px;max-width:640px;width:92%;max-height:82vh;overflow-y:auto}
.modal h2{margin-bottom:12px}.modal-close{float:right;margin-bottom:8px}
.modal pre{background:#1a1a1a;padding:12px;font-size:12px;white-space:pre-wrap;line-height:1.7}
#toast{position:fixed;bottom:20px;right:20px;background:#2a5;color:#fff;padding:10px 18px;
       border-radius:4px;font-family:monospace;display:none;z-index:200}
.mode-toggle{display:inline-flex}
.mode-toggle button{border-radius:0;border-right:none;padding:5px 14px;font-size:12px}
.mode-toggle button:first-child{border-radius:4px 0 0 4px}
.mode-toggle button:last-child{border-radius:0 4px 4px 0;border-right:1px solid #555}
.svg-pad-wrap{margin-bottom:10px;user-select:none}
.token-dock{display:flex;gap:8px;flex-wrap:wrap;padding:8px;background:#1a1a1a;border:1px solid #333;border-radius:4px;min-height:44px;align-items:center}
.token{display:inline-flex;align-items:center;gap:5px;padding:5px 10px;border-radius:16px;cursor:grab;font-size:12px;border:2px solid;user-select:none;white-space:nowrap}
.token.tandem{background:#1a2040;border-color:#36b;color:#9bf}
.token.single{background:#1a3020;border-color:#3b6;color:#9fb}
.token.unknown{background:#2a2020;border-color:#744;color:#b88}
.token.placed{opacity:0.35;cursor:default;pointer-events:none}
.token-ghost{position:fixed;pointer-events:none;z-index:1000;opacity:0.9}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>Toy Pad LED Editor</h1>
    <div style="display:flex;align-items:center;gap:10px;margin-top:4px">
      <div id="pad-status" class="pad-status off">checking...</div>
      <button id="reconnect-btn" onclick="reconnectPad()" style="font-size:11px;padding:3px 8px">Reconnect</button>
    </div>
  </div>
  <div style="display:flex;gap:8px;align-items:center">
    <button onclick="showHelp()">? Help</button>
    <button class="primary" onclick="saveConfig()">Save Config</button>
  </div>
</div>

<!-- Profiles bar -->
<div class="profiles-bar">
  <span class="bar-label">Profile</span>
  <select id="profile-select" onchange="onProfileChange()" style="min-width:160px"></select>
  <button onclick="loadProfile()">Load</button>
  <button onclick="showSaveAs()">Save As...</button>
  <button id="delete-profile-btn" onclick="deleteProfile()">Delete</button>
</div>
<div id="saveas-row" class="saveas-row">
  <input type="text" id="profile-name-input" placeholder="Profile name..." style="min-width:160px">
  <button class="primary" onclick="confirmSaveProfile()">Save</button>
  <button onclick="hideSaveAs()">Cancel</button>
</div>

<!-- Main tabs -->
<div class="main-tabs">
  <div class="main-tab active" data-mt="led" onclick="mainTab('led')">LED</div>
  <div class="main-tab" data-mt="behavior" onclick="mainTab('behavior')">Behavior</div>
  <div class="main-tab" data-mt="test" onclick="mainTab('test')">Test</div>
</div>

<!-- ═══════════════════════════ LED tab ══════════════════════════════════════ -->
<div id="mt-led" class="main-tab-content active">

  <!-- Global Passive -->
  <div class="section">
    <h2>Global Passive</h2>
    <div class="field-row">
      <label>Mode</label>
      <select id="gp-mode" onchange="renderParams('gp-params',this.value,gpCfg())">
        <option value="off">off</option>
        <option value="static">static</option>
        <option value="breathe">breathe</option>
        <option value="cycle">cycle</option>
        <option value="flash">flash</option>
        <option value="hold">hold</option>
      </select>
      <button onclick="padPreviewPassive()">Preview on pad</button>
    </div>
    <div class="mode-params" id="gp-params"></div>
  </div>

  <!-- Zones -->
  <div class="section">
    <h2>Zones</h2>
    <div class="tabs">
      <div class="tab active" onclick="tab(1)">Center</div>
      <div class="tab" onclick="tab(2)">Left</div>
      <div class="tab" onclick="tab(3)">Right</div>
    </div>
    <div class="zone-tools">
      <button onclick="applyToAll()">Apply this zone to all</button>
      <button onclick="copyGlobal()">Copy global passive here</button>
    </div>
    <div class="sub" style="margin-bottom:10px">
      <h3>Preview All Zones on Pad</h3>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <button onclick="padPreviewAll('passive')" style="font-size:12px;padding:4px 10px">Passive</button>
        <button onclick="padPreviewAll('match')" style="font-size:12px;padding:4px 10px">Match</button>
        <button onclick="padPreviewAll('no_match')" style="font-size:12px;padding:4px 10px">No Match</button>
      </div>
    </div>
    <div id="tab-1" class="tab-content active"></div>
    <div id="tab-2" class="tab-content"></div>
    <div id="tab-3" class="tab-content"></div>
  </div>

  <!-- Zone Links -->
  <div class="section">
    <h2>Zone Links</h2>
    <div style="font-size:12px;color:#888;margin-bottom:10px">Linked zones respond identically when any of them scans a tag.</div>
    <div class="link-btns">
      <button id="lnk-12" onclick="setLinks([1,2])">Link 1+2</button>
      <button id="lnk-13" onclick="setLinks([1,3])">Link 1+3</button>
      <button id="lnk-23" onclick="setLinks([2,3])">Link 2+3</button>
      <button id="lnk-123" onclick="setLinks([1,2,3])">Link All</button>
      <button id="lnk-0" onclick="setLinks([])">Unlink All</button>
    </div>
  </div>

</div>

<!-- ═══════════════════════════ Behavior tab ═════════════════════════════════ -->
<div id="mt-behavior" class="main-tab-content">

  <!-- Session Behavior -->
  <div class="section">
    <h2>Session Behavior</h2>
    <div class="sub">
      <h3>Timing</h3>
      <div class="field-row">
        <input type="checkbox" id="op-removal-cd" checked>
        <label for="op-removal-cd">Removal countdown — browser stays open after tag is removed</label>
      </div>
      <div class="field-row">
        <label>Countdown</label>
        <input type="range" id="op-cd-secs" min="1" max="30" step="1" value="5" oninput="sv('op-cd-secsv',this.value+'s')">
        <span id="op-cd-secsv" class="val">5s</span>
        <span style="font-size:11px;color:#666">seconds before browser closes after tag removed</span>
      </div>
      <div class="field-row">
        <label>Lockout</label>
        <input type="range" id="op-lockout-secs" min="0" max="15" step="1" value="3" oninput="sv('op-lockout-secsv',this.value+'s')">
        <span id="op-lockout-secsv" class="val">3s</span>
        <span style="font-size:11px;color:#666">cooldown after session ends before new scan accepted</span>
      </div>
    </div>
    <div class="sub">
      <h3>Countdown Flash LED <span style="color:#555;font-size:11px;font-weight:normal">(removed zone — color per zone)</span></h3>
      <div class="field-row">
        <label style="min-width:52px;color:#888;font-size:12px">Center</label>
        <label style="margin-left:4px">R</label><input type="number" id="op-cd-flash-1-r" min="0" max="255" value="255" style="width:56px" oninput="updateSwatch('op-cd-flash-1')">
        <label style="margin-left:4px">G</label><input type="number" id="op-cd-flash-1-g" min="0" max="255" value="100" style="width:56px" oninput="updateSwatch('op-cd-flash-1')">
        <label style="margin-left:4px">B</label><input type="number" id="op-cd-flash-1-b" min="0" max="255" value="0" style="width:56px" oninput="updateSwatch('op-cd-flash-1')">
        <span id="op-cd-flash-1-swatch" style="display:inline-block;width:28px;height:28px;border:1px solid #555;background:rgb(255,100,0);margin-left:8px;vertical-align:middle"></span>
        <select style="margin-left:8px" onchange="applyPreset(this,'op-cd-flash-1')"><option value="">— preset —</option></select>
        <button onclick="padPreviewOpMode('countdown_flash_1')">Preview</button>
      </div>
      <div class="field-row">
        <label style="min-width:52px;color:#888;font-size:12px">Left</label>
        <label style="margin-left:4px">R</label><input type="number" id="op-cd-flash-2-r" min="0" max="255" value="255" style="width:56px" oninput="updateSwatch('op-cd-flash-2')">
        <label style="margin-left:4px">G</label><input type="number" id="op-cd-flash-2-g" min="0" max="255" value="100" style="width:56px" oninput="updateSwatch('op-cd-flash-2')">
        <label style="margin-left:4px">B</label><input type="number" id="op-cd-flash-2-b" min="0" max="255" value="0" style="width:56px" oninput="updateSwatch('op-cd-flash-2')">
        <span id="op-cd-flash-2-swatch" style="display:inline-block;width:28px;height:28px;border:1px solid #555;background:rgb(255,100,0);margin-left:8px;vertical-align:middle"></span>
        <select style="margin-left:8px" onchange="applyPreset(this,'op-cd-flash-2')"><option value="">— preset —</option></select>
        <button onclick="padPreviewOpMode('countdown_flash_2')">Preview</button>
      </div>
      <div class="field-row">
        <label style="min-width:52px;color:#888;font-size:12px">Right</label>
        <label style="margin-left:4px">R</label><input type="number" id="op-cd-flash-3-r" min="0" max="255" value="255" style="width:56px" oninput="updateSwatch('op-cd-flash-3')">
        <label style="margin-left:4px">G</label><input type="number" id="op-cd-flash-3-g" min="0" max="255" value="100" style="width:56px" oninput="updateSwatch('op-cd-flash-3')">
        <label style="margin-left:4px">B</label><input type="number" id="op-cd-flash-3-b" min="0" max="255" value="0" style="width:56px" oninput="updateSwatch('op-cd-flash-3')">
        <span id="op-cd-flash-3-swatch" style="display:inline-block;width:28px;height:28px;border:1px solid #555;background:rgb(255,100,0);margin-left:8px;vertical-align:middle"></span>
        <select style="margin-left:8px" onchange="applyPreset(this,'op-cd-flash-3')"><option value="">— preset —</option></select>
        <button onclick="padPreviewOpMode('countdown_flash_3')">Preview</button>
      </div>
      <div class="field-row">
        <label>On time</label>
        <input type="range" id="op-cd-flash-on" min="0.05" max="1" step="0.05" value="0.25" oninput="sv('op-cd-flash-onv',this.value+'s')">
        <span id="op-cd-flash-onv" class="val">0.25s</span>
      </div>
      <div class="field-row">
        <label>Off time</label>
        <input type="range" id="op-cd-flash-off" min="0.05" max="1" step="0.05" value="0.25" oninput="sv('op-cd-flash-offv',this.value+'s')">
        <span id="op-cd-flash-offv" class="val">0.25s</span>
      </div>
    </div>
    <div class="sub">
      <h3>Tandem Waiting LED <span style="color:#555;font-size:11px;font-weight:normal">(one tag placed, partner not yet present)</span></h3>
      <div class="field-row">
        <label>Mode</label>
        <select id="op-tandem-wait-mode" onchange="renderParams('op-tandem-wait-params',this.value,{})">
          <option value="static">static</option>
          <option value="breathe">breathe</option>
          <option value="flash">flash</option>
          <option value="cycle">cycle</option>
          <option value="off">off</option>
        </select>
        <button onclick="padPreviewOpMode('tandem_wait')">Preview on pad</button>
      </div>
      <div class="mode-params" id="op-tandem-wait-params"></div>
    </div>
    <div class="sub">
      <h3>Tandem Countdown Fade LED <span style="color:#555;font-size:11px;font-weight:normal">(still-present zone)</span></h3>
      <div class="field-row">
        <label>Fade color</label>
        <label style="margin-left:4px">R</label><input type="number" id="op-tandem-fade-r" min="0" max="255" value="0" style="width:56px" oninput="updateSwatch('op-tandem-fade')">
        <label style="margin-left:4px">G</label><input type="number" id="op-tandem-fade-g" min="0" max="255" value="80" style="width:56px" oninput="updateSwatch('op-tandem-fade')">
        <label style="margin-left:4px">B</label><input type="number" id="op-tandem-fade-b" min="0" max="255" value="255" style="width:56px" oninput="updateSwatch('op-tandem-fade')">
        <span id="op-tandem-fade-swatch" style="display:inline-block;width:28px;height:28px;border:1px solid #555;background:rgb(0,80,255);margin-left:8px;vertical-align:middle"></span>
        <select style="margin-left:8px" onchange="applyPreset(this,'op-tandem-fade')"><option value="">— preset —</option></select>
        <span style="font-size:11px;color:#666">Zone dims from this color to off over countdown duration</span>
        <button onclick="padPreviewOpMode('tandem_fade')">Preview on pad</button>
      </div>
    </div>
  </div>

  <!-- Lockout -->
  <div class="section">
    <h2>Lockout</h2>
    <div style="font-size:12px;color:#666;margin-bottom:12px">Applies when a page closes and the cooldown begins, or when the terminal is manually locked out via command.</div>
    <div class="sub">
      <h3>LED <span style="color:#555;font-size:11px;font-weight:normal">(all zones for the duration of the lockout)</span></h3>
      <div class="field-row">
        <label>Mode</label>
        <select id="op-lockout-mode" onchange="renderParams('op-lockout-params',this.value,{})">
          <option value="breathe">breathe</option>
          <option value="static">static</option>
          <option value="flash">flash</option>
          <option value="cycle">cycle</option>
          <option value="off">off</option>
        </select>
        <button onclick="padPreviewOpMode('lockout')">Preview on pad</button>
      </div>
      <div class="mode-params" id="op-lockout-params"></div>
    </div>
    <div class="sub">
      <h3>Sound <span style="color:#555;font-size:11px;font-weight:normal">&mdash; plays once when lockout begins</span></h3>
      <div class="sound-row">
        <span class="sound-lbl">Lockout Start</span>
        <button onclick="browseSound(this)">Browse</button>
        <input type="text" id="sound-lockout_start" placeholder="/path/to/file" style="flex:1;min-width:180px">
        <button onclick="testSound('sound-lockout_start')" title="Test">&#9654;</button>
        <button onclick="$('sound-lockout_start').value=''">Clear</button>
      </div>
    </div>
  </div>

  <!-- Sounds -->
  <div class="section">
    <h2>Sounds</h2>
    <div style="font-size:12px;color:#666;margin-bottom:12px">WAV &middot; MP3 &middot; OGG &middot; FLAC &mdash; full file path. Sounds are saved as part of the profile. Click &#9654; to test a path.</div>

    <div class="sub">
      <h3>One-shot <span style="color:#555;font-size:11px;font-weight:normal">&mdash; plays once when event fires</span></h3>
      <div class="sound-row">
        <span class="sound-lbl">Match <span class="sound-note">(single tag found)</span></span>
        <button onclick="browseSound(this)">Browse</button>
        <input type="text" id="sound-match" placeholder="/path/to/file" style="flex:1;min-width:180px">
        <button onclick="testSound('sound-match')" title="Test">&#9654;</button>
        <button onclick="$('sound-match').value=''">Clear</button>
      </div>
      <div class="sound-row">
        <span class="sound-lbl">No Match <span class="sound-note">(unknown tag)</span></span>
        <button onclick="browseSound(this)">Browse</button>
        <input type="text" id="sound-no_match" placeholder="/path/to/file" style="flex:1;min-width:180px">
        <button onclick="testSound('sound-no_match')" title="Test">&#9654;</button>
        <button onclick="$('sound-no_match').value=''">Clear</button>
      </div>
      <div class="sound-row">
        <span class="sound-lbl">Tandem First <span class="sound-note">(first key scanned)</span></span>
        <button onclick="browseSound(this)">Browse</button>
        <input type="text" id="sound-tandem_first" placeholder="/path/to/file" style="flex:1;min-width:180px">
        <button onclick="testSound('sound-tandem_first')" title="Test">&#9654;</button>
        <button onclick="$('sound-tandem_first').value=''">Clear</button>
      </div>
      <div class="sound-row">
        <span class="sound-lbl">Tandem Match <span class="sound-note">(both keys placed)</span></span>
        <button onclick="browseSound(this)">Browse</button>
        <input type="text" id="sound-tandem_match" placeholder="/path/to/file" style="flex:1;min-width:180px">
        <button onclick="testSound('sound-tandem_match')" title="Test">&#9654;</button>
        <button onclick="$('sound-tandem_match').value=''">Clear</button>
      </div>
      <div class="sound-row">
        <span class="sound-lbl">Page Open <span class="sound-note">(briefing launches)</span></span>
        <button onclick="browseSound(this)">Browse</button>
        <input type="text" id="sound-page_open" placeholder="/path/to/file" style="flex:1;min-width:180px">
        <button onclick="testSound('sound-page_open')" title="Test">&#9654;</button>
        <button onclick="$('sound-page_open').value=''">Clear</button>
      </div>
      <div class="sound-row">
        <span class="sound-lbl">Page Close <span class="sound-note">(briefing dismissed)</span></span>
        <button onclick="browseSound(this)">Browse</button>
        <input type="text" id="sound-page_close" placeholder="/path/to/file" style="flex:1;min-width:180px">
        <button onclick="testSound('sound-page_close')" title="Test">&#9654;</button>
        <button onclick="$('sound-page_close').value=''">Clear</button>
      </div>
      <div class="sound-row">
        <span class="sound-lbl">Countdown Start <span class="sound-note">(tag removed)</span></span>
        <button onclick="browseSound(this)">Browse</button>
        <input type="text" id="sound-countdown_start" placeholder="/path/to/file" style="flex:1;min-width:180px">
        <button onclick="testSound('sound-countdown_start')" title="Test">&#9654;</button>
        <button onclick="$('sound-countdown_start').value=''">Clear</button>
      </div>
      <div class="sound-row">
        <span class="sound-lbl">Session Restore <span class="sound-note">(tag replaced in time)</span></span>
        <button onclick="browseSound(this)">Browse</button>
        <input type="text" id="sound-session_restore" placeholder="/path/to/file" style="flex:1;min-width:180px">
        <button onclick="testSound('sound-session_restore')" title="Test">&#9654;</button>
        <button onclick="$('sound-session_restore').value=''">Clear</button>
      </div>
    </div>

    <div class="sub">
      <h3>Loops <span style="color:#555;font-size:11px;font-weight:normal">&mdash; play continuously until the state ends</span></h3>
      <div class="sound-row">
        <span class="sound-lbl">Ambient <span class="sound-note">(whole session)</span></span>
        <button onclick="browseSound(this)">Browse</button>
        <input type="text" id="sound-ambient" placeholder="/path/to/file" style="flex:1;min-width:180px">
        <button onclick="testSound('sound-ambient')" title="Test">&#9654;</button>
        <button onclick="$('sound-ambient').value=''">Clear</button>
      </div>
      <div class="sound-row">
        <span class="sound-lbl">Single Loop <span class="sound-note">(single tag on pad)</span></span>
        <button onclick="browseSound(this)">Browse</button>
        <input type="text" id="sound-single_loop" placeholder="/path/to/file" style="flex:1;min-width:180px">
        <button onclick="testSound('sound-single_loop')" title="Test">&#9654;</button>
        <button onclick="$('sound-single_loop').value=''">Clear</button>
      </div>
      <div class="sound-row">
        <span class="sound-lbl">Tandem Loop <span class="sound-note">(both tandem tags on pad)</span></span>
        <button onclick="browseSound(this)">Browse</button>
        <input type="text" id="sound-tandem_loop" placeholder="/path/to/file" style="flex:1;min-width:180px">
        <button onclick="testSound('sound-tandem_loop')" title="Test">&#9654;</button>
        <button onclick="$('sound-tandem_loop').value=''">Clear</button>
      </div>
      <div class="sound-row">
        <span class="sound-lbl">Tandem Wait Loop <span class="sound-note">(awaiting partner)</span></span>
        <button onclick="browseSound(this)">Browse</button>
        <input type="text" id="sound-tandem_wait_loop" placeholder="/path/to/file" style="flex:1;min-width:180px">
        <button onclick="testSound('sound-tandem_wait_loop')" title="Test">&#9654;</button>
        <button onclick="$('sound-tandem_wait_loop').value=''">Clear</button>
      </div>
      <div class="sound-row">
        <span class="sound-lbl">Countdown Loop <span class="sound-note">(during countdown)</span></span>
        <button onclick="browseSound(this)">Browse</button>
        <input type="text" id="sound-countdown_loop" placeholder="/path/to/file" style="flex:1;min-width:180px">
        <button onclick="testSound('sound-countdown_loop')" title="Test">&#9654;</button>
        <button onclick="$('sound-countdown_loop').value=''">Clear</button>
      </div>
    </div>
  </div>

</div>

<!-- ═══════════════════════════ Test tab ══════════════════════════════════════ -->
<div id="mt-test" class="main-tab-content">
  <div class="section">
    <h2>Live Tag Preview</h2>
    <div style="font-size:12px;color:#888;margin-bottom:10px">Runs the full state machine — LEDs, sounds, countdowns — without opening URLs.</div>

    <!-- Input mode toggle -->
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap">
      <span style="font-size:11px;color:#777;text-transform:uppercase;letter-spacing:1px">Input</span>
      <span class="mode-toggle">
        <button id="mode-live" class="active" onclick="setInputMode('live')">Live</button>
        <button id="mode-emulated" onclick="setInputMode('emulated')">Emulated</button>
        <button id="mode-both" onclick="setInputMode('both')">Both</button>
      </span>
      <span id="mode-note" style="font-size:11px;color:#555">Uses real hardware tags</span>
    </div>

    <!-- Start / Stop -->
    <div style="display:flex;gap:8px;align-items:center;margin-bottom:10px">
      <button id="live-start-btn" class="primary" onclick="startLive()">Start</button>
      <button id="live-stop-btn" onclick="stopLive()" style="display:none">&#9632; Stop</button>
      <span id="live-status" style="font-size:12px;color:#888"></span>
    </div>

    <!-- Virtual pad (shown when emulated/both) -->
    <div id="svg-pad-area" style="display:none">
      <div class="svg-pad-wrap">
        <svg id="virtual-pad" viewBox="0 0 420 190" style="width:100%;max-width:520px;display:block">
          <rect x="5" y="5" width="410" height="180" rx="22" fill="#0d0d0d" stroke="#444" stroke-width="2"/>
          <rect id="svg-zone-2" data-zone="2" x="28" y="38" width="92" height="114" rx="10"
                fill="rgb(0,0,0)" stroke="#555" stroke-width="1.5" onclick="clickZone(2)"/>
          <circle id="svg-zone-1" data-zone="1" cx="210" cy="95" r="54"
                  fill="rgb(0,0,0)" stroke="#555" stroke-width="1.5" onclick="clickZone(1)"/>
          <rect id="svg-zone-3" data-zone="3" x="300" y="38" width="92" height="114" rx="10"
                fill="rgb(0,0,0)" stroke="#555" stroke-width="1.5" onclick="clickZone(3)"/>
          <text x="74"  y="174" text-anchor="middle" fill="#444" font-size="10" font-family="monospace">LEFT</text>
          <text x="210" y="174" text-anchor="middle" fill="#444" font-size="10" font-family="monospace">CENTER</text>
          <text x="346" y="174" text-anchor="middle" fill="#444" font-size="10" font-family="monospace">RIGHT</text>
          <text id="zone-label-2" x="74"  y="92" text-anchor="middle" fill="#888" font-size="9" font-family="monospace"></text>
          <text id="zone-label-1" x="210" y="92" text-anchor="middle" fill="#888" font-size="9" font-family="monospace"></text>
          <text id="zone-label-3" x="346" y="92" text-anchor="middle" fill="#888" font-size="9" font-family="monospace"></text>
        </svg>
      </div>
      <div style="font-size:11px;color:#555;margin-bottom:6px">Drag a tag token onto a zone &mdash; release outside to remove:</div>
      <div id="token-dock" class="token-dock">
        <span style="color:#444;font-size:12px">Loading tokens...</span>
      </div>
    </div>

    <!-- Log -->
    <div id="live-log" style="background:#111;border:1px solid #333;padding:8px;height:160px;overflow-y:auto;font-size:12px;font-family:monospace;display:none;line-height:1.6;margin-top:10px"></div>
  </div>
</div>

<div class="footer">
  <button onclick="showHelp()">? Help</button>
  <button class="primary" onclick="saveConfig()">Save Config</button>
</div>

<!-- Help Modal -->
<div class="modal-bg" id="help-modal">
  <div class="modal">
    <button class="modal-close" onclick="hideHelp()">X Close</button>
    <h2>LED Editor Help</h2>
    <pre>
TABS
  LED       Global passive, per-zone match/no-match, and zone links.
  Behavior  Session timing, countdown/tandem LED effects, and all
            sound assignments.
  Test      Live tag preview — runs LED effects with a real tag,
            without opening any URLs.

MODES
  off      Zone is dark. No parameters.
  static   Solid color until the next event.
  hold     Solid color for a set duration, then returns to passive.
           Params: Color, Duration (seconds)
  flash    Blink N times, then return to passive.
           Params: Color, Count, On time (s), Off time (s)
  breathe  Fade in and out continuously.
           Params: Color (peak brightness), Speed (seconds per cycle)
  cycle    Rotate through the color spectrum.
           Params: R/G/B ceilings (0-255), Speed (seconds per rotation)
           Note: if all ceilings are below 30 the zone may appear
           off or very dim — a warning will appear in the editor.

GLOBAL PASSIVE
  The ambient LED behavior for all zones when no tag is active.
  Applies to every zone unless that zone has a passive override set.

PASSIVE OVERRIDE (per zone)
  Enables a zone-specific ambient behavior, replacing the global
  passive for that zone only.

ZONE LINKS
  Linked zones respond identically when any of them scans a tag.

ZONE TOOLS
  "Apply this zone to all"  — copies the current zone's match and
                              no_match settings to all three zones.
  "Copy global passive here" — sets this zone's passive override to
                               match the current global passive config.

SOUNDS
  One-shot sounds play once when their event fires.
  Loop sounds play continuously until their state ends:
    Ambient         — loops the entire time toypad_run.py is active.
    Single Loop     — loops while a single tag is on the pad.
    Tandem Loop     — loops while both tandem tags are on the pad.
    Tandem Wait     — loops while waiting for the tandem partner.
    Countdown Loop  — loops during the removal countdown window.
  Click &#9654; to test a path immediately without scanning a tag.
  All sounds are saved as part of the profile — loading a different
  profile swaps the entire LED + sound vibe at once.

OPERATIONS (Behavior tab)
  Removal Countdown — when enabled, removing a tag starts a countdown
    before the browser closes. Replacing the same tag within that
    window restores the session. If the briefing was never confirmed
    (key not yet pressed), removal always returns to idle immediately
    with no countdown.
  Countdown seconds — how long before the browser closes.
  Lockout seconds   — brief cooldown after a session ends before new
    scans are accepted.
  Tag on Pad LED    — Per-zone LED mode held after the match animation
    until the tag is removed. Configured in the Zones tab alongside
    Match / No Match. Set to off to return to passive instead.
  Countdown Flash   — LED color/timing for a removed zone.
  Tandem Waiting    — LED shown when one tandem tag is placed while
    waiting for its partner.
  Tandem Fade       — the still-present zone dims from this color to
    off over the countdown duration when one tandem tag is removed.

PROFILES
  Profiles save all LED settings, operations, AND sound assignments
  together. Load a profile to switch the entire look and feel.
  Click Save Config to write led_config.json immediately.
  toypad_run.py reloads config on every tag scan.
    </pre>
  </div>
</div>

<div id="toast">Saved!</div>

<script>
// ── State ─────────────────────────────────────────────────────────────────────
let config = {};
let activeTab = 1;

const SOUND_KEYS = [
  'match', 'no_match', 'tandem_first', 'tandem_match',
  'page_open', 'page_close', 'lockout_start', 'countdown_start', 'session_restore',
  'ambient', 'single_loop', 'tandem_loop', 'tandem_wait_loop', 'countdown_loop',
];

// ── Helpers ───────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
function gpCfg(){return config.global_passive||{mode:'off'}}
function zoneCfg(z,k){return(config.zones&&config.zones[z]&&config.zones[z][k])||{mode:'off'}}
function sel(id,v){const e=$(id);if(e)e.value=v}

// ── Main tab switching ────────────────────────────────────────────────────────
function mainTab(name){
  document.querySelectorAll('.main-tab').forEach(t=>t.classList.toggle('active',t.dataset.mt===name));
  document.querySelectorAll('.main-tab-content').forEach(t=>t.classList.remove('active'));
  $('mt-'+name).classList.add('active');
}

// ── Zone tab switching ────────────────────────────────────────────────────────
function tab(n){
  activeTab=n;
  document.querySelectorAll('.tab').forEach((t,i)=>t.classList.toggle('active',i+1===n));
  document.querySelectorAll('.tab-content').forEach((t,i)=>t.classList.toggle('active',i+1===n));
}

// ── Build zone panels ─────────────────────────────────────────────────────────
function buildZonePanels(){
  [1,2,3].forEach(z=>{
    $('tab-'+z).innerHTML = `
      <div class="sub">
        <h3>Passive Override</h3>
        <div class="override-row">
          <input type="checkbox" id="z${z}-ov-en" onchange="toggleOv(${z})">
          <label for="z${z}-ov-en">Override global passive for this zone</label>
        </div>
        <div id="z${z}-ov-body" class="override-body">
          <div class="field-row">
            <label>Mode</label>
            <select id="z${z}-ov-mode" onchange="renderParams('z${z}-ov-params',this.value,zoneCfg(${z},'passive_override'))">
              <option value="off">off</option><option value="static">static</option>
              <option value="breathe">breathe</option><option value="cycle">cycle</option>
              <option value="flash">flash</option><option value="hold">hold</option>
            </select>
            <button onclick="padPreviewPassiveZone(${z})">Preview on pad</button>
          </div>
          <div class="mode-params" id="z${z}-ov-params"></div>
        </div>
      </div>
      <div class="sub">
        <h3>Match (tag found)</h3>
        <div class="field-row">
          <label>Mode</label>
          <select id="z${z}-match-mode" onchange="renderParams('z${z}-match-params',this.value,zoneCfg(${z},'match'))">
            <option value="off">off</option><option value="static">static</option>
            <option value="hold">hold</option><option value="flash">flash</option>
            <option value="breathe">breathe</option><option value="cycle">cycle</option>
          </select>
          <button onclick="padPreview(${z},'match')">Preview on pad</button>
        </div>
        <div class="mode-params" id="z${z}-match-params"></div>
      </div>
      <div class="sub">
        <h3>No Match (unknown tag)</h3>
        <div class="field-row">
          <label>Mode</label>
          <select id="z${z}-no_match-mode" onchange="renderParams('z${z}-no_match-params',this.value,zoneCfg(${z},'no_match'))">
            <option value="off">off</option><option value="static">static</option>
            <option value="hold">hold</option><option value="flash">flash</option>
            <option value="breathe">breathe</option><option value="cycle">cycle</option>
          </select>
          <button onclick="padPreview(${z},'no_match')">Preview on pad</button>
        </div>
        <div class="mode-params" id="z${z}-no_match-params"></div>
      </div>
      <div class="sub">
        <h3>Tag on Pad <span style="color:#555;font-size:11px;font-weight:normal">&mdash; held after match animation until tag is removed</span></h3>
        <div class="field-row">
          <label>Mode</label>
          <select id="z${z}-tag_on_pad-mode" onchange="renderParams('z${z}-tag_on_pad-params',this.value,zoneCfg(${z},'tag_on_pad'))">
            <option value="off">off (return to passive)</option>
            <option value="static">static</option>
            <option value="breathe">breathe</option>
            <option value="flash_loop">flash (loop)</option>
            <option value="cycle">cycle</option>
          </select>
          <button onclick="padPreview(${z},'tag_on_pad')">Preview on pad</button>
        </div>
        <div class="mode-params" id="z${z}-tag_on_pad-params"></div>
      </div>
    `;
  });
}

// ── Mode param rendering ──────────────────────────────────────────────────────
function renderParams(cid, mode, ex){
  ex=ex||{};
  const c=$(cid); if(!c)return;
  let h='';
  if(['static','hold','breathe','flash','flash_loop'].includes(mode)){
    const rv=ex.r!==undefined?ex.r:128, gv=ex.g!==undefined?ex.g:128, bv=ex.b!==undefined?ex.b:128;
    h+=`<div class="field-row"><label>Color</label>`
      +`<label style="margin-left:4px">R</label><input type="number" id="${cid}-r" min="0" max="255" value="${rv}" style="width:56px" oninput="updateSwatch('${cid}');onPC('${cid}')">`
      +`<label style="margin-left:4px">G</label><input type="number" id="${cid}-g" min="0" max="255" value="${gv}" style="width:56px" oninput="updateSwatch('${cid}');onPC('${cid}')">`
      +`<label style="margin-left:4px">B</label><input type="number" id="${cid}-b" min="0" max="255" value="${bv}" style="width:56px" oninput="updateSwatch('${cid}');onPC('${cid}')">`
      +`<span id="${cid}-swatch" style="display:inline-block;width:28px;height:28px;border:1px solid #555;background:rgb(${rv},${gv},${bv});margin-left:8px;vertical-align:middle"></span>`
      +`<select style="margin-left:8px" onchange="applyPreset(this,'${cid}')">${presetOptions()}</select></div>`;
  }
  if(mode==='cycle'){
    const rv=ex.r!==undefined?ex.r:255, gv=ex.g!==undefined?ex.g:255, bv=ex.b!==undefined?ex.b:255;
    h+=`<div class="field-row"><label>R ceil</label><input type="range" id="${cid}-r" min="0" max="255" value="${rv}" oninput="sv('${cid}-rv',this.value);dimCheck('${cid}');onPC('${cid}')"><span id="${cid}-rv" class="val">${rv}</span></div>`;
    h+=`<div class="field-row"><label>G ceil</label><input type="range" id="${cid}-g" min="0" max="255" value="${gv}" oninput="sv('${cid}-gv',this.value);dimCheck('${cid}');onPC('${cid}')"><span id="${cid}-gv" class="val">${gv}</span></div>`;
    h+=`<div class="field-row"><label>B ceil</label><input type="range" id="${cid}-b" min="0" max="255" value="${bv}" oninput="sv('${cid}-bv',this.value);dimCheck('${cid}');onPC('${cid}')"><span id="${cid}-bv" class="val">${bv}</span></div>`;
    h+=`<div class="dim-warn" id="${cid}-dim">Warning: all ceilings below 30 — zone may appear off or very dim</div>`;
  }
  if(mode==='hold'){
    const d=ex.duration!==undefined?ex.duration:2;
    h+=`<div class="field-row"><label>Duration</label><input type="range" id="${cid}-dur" min="0.5" max="10" step="0.5" value="${d}" oninput="sv('${cid}-durv',this.value+'s');onPC('${cid}')"><span id="${cid}-durv" class="val">${d}s</span></div>`;
  }
  if(mode==='flash'){
    const cnt=ex.count!==undefined?ex.count:3, on=ex.on!==undefined?ex.on:0.3, off=ex.off!==undefined?ex.off:0.2;
    h+=`<div class="field-row"><label>Count</label><input type="range" id="${cid}-cnt" min="1" max="10" value="${cnt}" oninput="sv('${cid}-cntv',this.value);onPC('${cid}')"><span id="${cid}-cntv" class="val">${cnt}</span></div>`;
    h+=`<div class="field-row"><label>On time</label><input type="range" id="${cid}-on" min="0.1" max="1" step="0.05" value="${on}" oninput="sv('${cid}-onv',this.value+'s');onPC('${cid}')"><span id="${cid}-onv" class="val">${on}s</span></div>`;
    h+=`<div class="field-row"><label>Off time</label><input type="range" id="${cid}-off" min="0.1" max="1" step="0.05" value="${off}" oninput="sv('${cid}-offv',this.value+'s');onPC('${cid}')"><span id="${cid}-offv" class="val">${off}s</span></div>`;
  }
  if(mode==='flash_loop'){
    const on=ex.on!==undefined?ex.on:0.25, off=ex.off!==undefined?ex.off:0.25;
    h+=`<div class="field-row"><label>On time</label><input type="range" id="${cid}-on" min="0.05" max="1" step="0.05" value="${on}" oninput="sv('${cid}-onv',this.value+'s');onPC('${cid}')"><span id="${cid}-onv" class="val">${on}s</span></div>`;
    h+=`<div class="field-row"><label>Off time</label><input type="range" id="${cid}-off" min="0.05" max="1" step="0.05" value="${off}" oninput="sv('${cid}-offv',this.value+'s');onPC('${cid}')"><span id="${cid}-offv" class="val">${off}s</span></div>`;
  }
  if(['breathe','cycle'].includes(mode)){
    const sp=ex.speed!==undefined?ex.speed:2;
    h+=`<div class="field-row"><label>Speed</label><input type="range" id="${cid}-spd" min="0.5" max="8" step="0.5" value="${sp}" oninput="sv('${cid}-spdv',this.value+'s');onPC('${cid}')"><span id="${cid}-spdv" class="val">${sp}s</span></div>`;
  }
  c.innerHTML=h;
  if(mode==='cycle')dimCheck(cid);
}

function sv(id,v){const e=$(id);if(e)e.textContent=v}

const PRESETS=[
  ['Off',          0,   0,   0  ],
  ['White',        255, 255, 255],
  ['Dim White',    80,  80,  80 ],
  ['Red',          255, 0,   0  ],
  ['Dark Red',     180, 0,   0  ],
  ['Green',        0,   255, 0  ],
  ['Dark Green',   0,   180, 0  ],
  ['Blue',         0,   0,   255],
  ['Rebel Blue',   0,   80,  255],
  ['Cyan',         0,   255, 255],
  ['Yellow',       255, 255, 0  ],
  ['Orange',       255, 100, 0  ],
  ['Amber',        255, 140, 0  ],
  ['Magenta',      255, 0,   255],
  ['Purple',       128, 0,   255],
];

function presetOptions(){
  return '<option value="">— preset —</option>'
    +PRESETS.map(([n,r,g,b])=>`<option value="${r},${g},${b}">${n}</option>`).join('');
}

function updateSwatch(cid){
  const r=Math.max(0,Math.min(255,parseInt($(cid+'-r')?.value||0)));
  const g=Math.max(0,Math.min(255,parseInt($(cid+'-g')?.value||0)));
  const b=Math.max(0,Math.min(255,parseInt($(cid+'-b')?.value||0)));
  const sw=$(cid+'-swatch');
  if(sw) sw.style.background=`rgb(${r},${g},${b})`;
}

function applyPreset(sel,cid){
  if(!sel.value)return;
  const[r,g,b]=sel.value.split(',').map(Number);
  $(cid+'-r').value=r; $(cid+'-g').value=g; $(cid+'-b').value=b;
  updateSwatch(cid); sel.value=''; onPC(cid);
}

function dimCheck(cid){
  const r=parseInt($(cid+'-r')?.value||255), g=parseInt($(cid+'-g')?.value||255), b=parseInt($(cid+'-b')?.value||255);
  const w=$(cid+'-dim'); if(w)w.style.display=(r<30&&g<30&&b<30)?'block':'none';
}

function collectCfg(cid, mode){
  const cfg={mode};
  if(['static','hold','breathe','flash','flash_loop','cycle'].includes(mode)){
    cfg.r=Math.max(0,Math.min(255,parseInt($(cid+'-r')?.value||0)));
    cfg.g=Math.max(0,Math.min(255,parseInt($(cid+'-g')?.value||0)));
    cfg.b=Math.max(0,Math.min(255,parseInt($(cid+'-b')?.value||0)));
  }
  if(mode==='hold')   cfg.duration=parseFloat($(cid+'-dur')?.value||2);
  if(mode==='flash'){
    cfg.count=parseInt($(cid+'-cnt')?.value||3);
    cfg.on=parseFloat($(cid+'-on')?.value||0.3);
    cfg.off=parseFloat($(cid+'-off')?.value||0.2);
  }
  if(mode==='flash_loop'){
    cfg.on=parseFloat($(cid+'-on')?.value||0.25);
    cfg.off=parseFloat($(cid+'-off')?.value||0.25);
  }
  if(['breathe','cycle'].includes(mode)) cfg.speed=parseFloat($(cid+'-spd')?.value||2);
  return cfg;
}

// ── Collect full config from form ─────────────────────────────────────────────
function collectConfig(){
  const cfg={global_passive:{},zones:{1:{},2:{},3:{}},zone_links:config.zone_links||[]};
  cfg.global_passive=collectCfg('gp-params',$('gp-mode').value);
  [1,2,3].forEach(z=>{
    const oven=$('z'+z+'-ov-en').checked;
    cfg.zones[z].passive_override=oven?collectCfg('z'+z+'-ov-params',$('z'+z+'-ov-mode').value):null;
    cfg.zones[z].match      =collectCfg('z'+z+'-match-params',    $('z'+z+'-match-mode').value);
    cfg.zones[z].no_match   =collectCfg('z'+z+'-no_match-params', $('z'+z+'-no_match-mode').value);
    cfg.zones[z].tag_on_pad =collectCfg('z'+z+'-tag_on_pad-params',$('z'+z+'-tag_on_pad-mode').value);
  });
  cfg.sounds={};
  SOUND_KEYS.forEach(k=>{const v=$('sound-'+k)?.value.trim();if(v)cfg.sounds[k]=v;});
  cfg.removal_countdown = $('op-removal-cd').checked;
  cfg.countdown_seconds = parseFloat($('op-cd-secs').value);
  cfg.lockout_seconds   = parseFloat($('op-lockout-secs').value);
  cfg.lockout = collectCfg('op-lockout-params', $('op-lockout-mode').value);
  function cdfc(z){
    return {
      r:Math.max(0,Math.min(255,parseInt($('op-cd-flash-'+z+'-r').value||255))),
      g:Math.max(0,Math.min(255,parseInt($('op-cd-flash-'+z+'-g').value||100))),
      b:Math.max(0,Math.min(255,parseInt($('op-cd-flash-'+z+'-b').value||0))),
    };
  }
  const fr=Math.max(0,Math.min(255,parseInt($('op-tandem-fade-r').value||0)));
  const fg=Math.max(0,Math.min(255,parseInt($('op-tandem-fade-g').value||80)));
  const fb=Math.max(0,Math.min(255,parseInt($('op-tandem-fade-b').value||255)));
  const twm=$('op-tandem-wait-mode').value;
  cfg.tandem={
    waiting_mode:           collectCfg('op-tandem-wait-params',twm),
    countdown_flash_colors: {'1':cdfc(1),'2':cdfc(2),'3':cdfc(3)},
    countdown_flash_on:     parseFloat($('op-cd-flash-on').value),
    countdown_flash_off:    parseFloat($('op-cd-flash-off').value),
    countdown_fade_color:   {r:fr,g:fg,b:fb},
  };
  return cfg;
}

// ── Populate form from config ─────────────────────────────────────────────────
function populateForm(){
  const gp=config.global_passive||{mode:'off'};
  sel('gp-mode',gp.mode); renderParams('gp-params',gp.mode,gp);
  [1,2,3].forEach(z=>{
    const zc=config.zones&&config.zones[z]?config.zones[z]:{};
    const ov=!!zc.passive_override;
    $('z'+z+'-ov-en').checked=ov;
    $('z'+z+'-ov-body').classList.toggle('on',ov);
    if(ov){sel('z'+z+'-ov-mode',zc.passive_override.mode);renderParams('z'+z+'-ov-params',zc.passive_override.mode,zc.passive_override);}
    const m=zc.match||{mode:'flash',r:0,g:255,b:0,count:3,on:0.3,off:0.2};
    sel('z'+z+'-match-mode',m.mode); renderParams('z'+z+'-match-params',m.mode,m);
    const nm=zc.no_match||{mode:'flash',r:255,g:0,b:0,count:3,on:0.3,off:0.2};
    sel('z'+z+'-no_match-mode',nm.mode); renderParams('z'+z+'-no_match-params',nm.mode,nm);
    const tap=zc.tag_on_pad||{mode:'off'};
    sel('z'+z+'-tag_on_pad-mode',tap.mode); renderParams('z'+z+'-tag_on_pad-params',tap.mode,tap);
  });
  updateLinks();
  const s=config.sounds||{};
  SOUND_KEYS.forEach(k=>{const el=$('sound-'+k);if(el&&k in s)el.value=s[k];});
  $('op-removal-cd').checked=config.removal_countdown!==false;
  const cdSecs=config.countdown_seconds||5;
  sel('op-cd-secs',cdSecs); sv('op-cd-secsv',cdSecs+'s');
  const lkSecs=config.lockout_seconds||3;
  sel('op-lockout-secs',lkSecs); sv('op-lockout-secsv',lkSecs+'s');
  const lkLed=config.lockout||{mode:'breathe',r:180,g:0,b:0,speed:1};
  sel('op-lockout-mode',lkLed.mode); renderParams('op-lockout-params',lkLed.mode,lkLed);
  const t=config.tandem||{};
  const wm=t.waiting_mode||{mode:'static',r:0,g:80,b:255};
  sel('op-tandem-wait-mode',wm.mode);
  renderParams('op-tandem-wait-params',wm.mode,wm);
  const cfcs=t.countdown_flash_colors||{};
  const cfc_fb=t.countdown_flash_color||{r:255,g:100,b:0};
  [1,2,3].forEach(z=>{
    const c=cfcs[z]||cfcs[String(z)]||cfc_fb;
    $('op-cd-flash-'+z+'-r').value=c.r; $('op-cd-flash-'+z+'-g').value=c.g; $('op-cd-flash-'+z+'-b').value=c.b;
    updateSwatch('op-cd-flash-'+z);
  });
  const cfon=t.countdown_flash_on!==undefined?t.countdown_flash_on:0.25;
  sel('op-cd-flash-on',cfon); sv('op-cd-flash-onv',cfon+'s');
  const cfoff=t.countdown_flash_off!==undefined?t.countdown_flash_off:0.25;
  sel('op-cd-flash-off',cfoff); sv('op-cd-flash-offv',cfoff+'s');
  const tfc=t.countdown_fade_color||{r:0,g:80,b:255};
  $('op-tandem-fade-r').value=tfc.r; $('op-tandem-fade-g').value=tfc.g; $('op-tandem-fade-b').value=tfc.b;
  updateSwatch('op-tandem-fade');
}

// ── Override toggle ───────────────────────────────────────────────────────────
function toggleOv(z){
  const en=$('z'+z+'-ov-en').checked;
  $('z'+z+'-ov-body').classList.toggle('on',en);
  if(en){const gp=gpCfg();sel('z'+z+'-ov-mode',gp.mode);renderParams('z'+z+'-ov-params',gp.mode,gp);}
}

// ── Zone tools ────────────────────────────────────────────────────────────────
function applyToAll(){
  const z=activeTab;
  const mm=$('z'+z+'-match-mode').value,       mc=collectCfg('z'+z+'-match-params',mm);
  const nm=$('z'+z+'-no_match-mode').value,    nc=collectCfg('z'+z+'-no_match-params',nm);
  const tm=$('z'+z+'-tag_on_pad-mode').value,  tc=collectCfg('z'+z+'-tag_on_pad-params',tm);
  [1,2,3].forEach(t=>{
    if(t===z)return;
    sel('z'+t+'-match-mode',mc.mode);      renderParams('z'+t+'-match-params',mc.mode,mc);
    sel('z'+t+'-no_match-mode',nc.mode);   renderParams('z'+t+'-no_match-params',nc.mode,nc);
    sel('z'+t+'-tag_on_pad-mode',tc.mode); renderParams('z'+t+'-tag_on_pad-params',tc.mode,tc);
  });
}
function copyGlobal(){
  const z=activeTab;
  const gp=collectCfg('gp-params',$('gp-mode').value);
  $('z'+z+'-ov-en').checked=true;
  $('z'+z+'-ov-body').classList.add('on');
  sel('z'+z+'-ov-mode',gp.mode); renderParams('z'+z+'-ov-params',gp.mode,gp);
}

// ── Zone links ────────────────────────────────────────────────────────────────
function setLinks(arr){config.zone_links=arr;updateLinks();}
function updateLinks(){
  const l=config.zone_links||[];
  const is=(...zs)=>zs.length===l.length&&zs.every(z=>l.includes(z));
  $('lnk-12')?.classList.toggle('active',is(1,2));
  $('lnk-13')?.classList.toggle('active',is(1,3));
  $('lnk-23')?.classList.toggle('active',is(2,3));
  $('lnk-123')?.classList.toggle('active',is(1,2,3));
  $('lnk-0')?.classList.toggle('active',l.length===0);
}

// ── Sound browse ─────────────────────────────────────────────────────────────
function browseSound(btn){
  const input=btn.parentElement.querySelector('input[type="text"]');
  btn.disabled=true; btn.textContent='...';
  fetch('/api/browse',{method:'POST'}).then(r=>r.json()).then(d=>{
    btn.disabled=false; btn.textContent='Browse';
    if(d.path) input.value=d.path;
  }).catch(()=>{btn.disabled=false; btn.textContent='Browse';});
}

// ── Sound test ────────────────────────────────────────────────────────────────
function testSound(inputId){
  const path=$(inputId)?.value.trim();
  if(!path){alert('No file path entered.');return;}
  fetch('/api/sound/test',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({path})})
    .then(r=>r.json()).then(d=>{if(!d.ok)alert('Sound error: '+(d.error||'unknown'));});
}

// ── Stubs (SVG removed) ───────────────────────────────────────────────────────
function passiveCfgFor(z){
  const oven=$('z'+z+'-ov-en')?.checked;
  if(oven){const m=$('z'+z+'-ov-mode')?.value||'off';return collectCfg('z'+z+'-ov-params',m);}
  const m=$('gp-mode')?.value||'off'; return collectCfg('gp-params',m);
}
function zonePassive(z){}
function allPassive(){}
function onPC(cid){}

function padPreviewAll(ev){
  if(ev==='passive'){
    [1,2,3].forEach(z=>{
      const cfg=passiveCfgFor(z);
      fetch('/api/preview',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({zone:z,mode_cfg:cfg,passive_cfg:cfg})});
    });
  } else {
    [1,2,3].forEach(z=>padPreview(z,ev));
  }
}

// ── Physical pad preview ──────────────────────────────────────────────────────
function padPreview(z,ev){
  const m=$('z'+z+'-'+ev+'-mode').value;
  fetch('/api/preview',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({zone:z,mode_cfg:collectCfg('z'+z+'-'+ev+'-params',m),passive_cfg:passiveCfgFor(z)})});
}
function padPreviewPassiveZone(z){
  const m=$('z'+z+'-ov-mode').value;
  fetch('/api/preview',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({zone:z,mode_cfg:collectCfg('z'+z+'-ov-params',m),passive_cfg:passiveCfgFor(z)})});
}
function padPreviewPassive(){
  const m=$('gp-mode').value, cfg=collectCfg('gp-params',m);
  [1,2,3].forEach(z=>fetch('/api/preview',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({zone:z,mode_cfg:cfg,passive_cfg:passiveCfgFor(z)})}));
}

// ── Operations preview ────────────────────────────────────────────────────────
function padPreviewOpMode(type){
  const cfg=collectConfig();
  const secs=cfg.countdown_seconds||5;
  if(type.startsWith('countdown_flash_')){
    const z=parseInt(type.slice('countdown_flash_'.length));
    const cfcs=cfg.tandem.countdown_flash_colors||{};
    const c=cfcs[z]||cfcs[String(z)]||cfg.tandem.countdown_flash_color||{r:255,g:100,b:0};
    const previewCfg={mode:'flash',r:c.r,g:c.g,b:c.b,count:5,
      on:cfg.tandem.countdown_flash_on||0.25,off:cfg.tandem.countdown_flash_off||0.25};
    fetch('/api/preview',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({zone:z,mode_cfg:previewCfg,passive_cfg:passiveCfgFor(z)})});
  } else if(type==='tandem_wait'){
    const wm=collectCfg('op-tandem-wait-params',$('op-tandem-wait-mode').value);
    [2,3].forEach(z=>fetch('/api/preview',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({zone:z,mode_cfg:wm,passive_cfg:passiveCfgFor(z)})}));
  } else if(type==='tandem_fade'){
    const fr=parseInt($('op-tandem-fade-r').value||0), fg=parseInt($('op-tandem-fade-g').value||80), fb=parseInt($('op-tandem-fade-b').value||255);
    const fadeCfg={mode:'fade_out',r:fr,g:fg,b:fb,duration:secs};
    [2,3].forEach(z=>fetch('/api/preview',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({zone:z,mode_cfg:fadeCfg,passive_cfg:passiveCfgFor(z)})}));
  } else if(type==='lockout'){
    const lkm=collectCfg('op-lockout-params',$('op-lockout-mode').value);
    [1,2,3].forEach(z=>fetch('/api/preview',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({zone:z,mode_cfg:lkm,passive_cfg:passiveCfgFor(z)})}));
  }
}

// ── Live Tag Preview ──────────────────────────────────────────────────────────
let liveActive=false, livePoll=null, liveOffset=0, ledPoll=null;
let inputMode='live';
let tokenData=[], tokenZones={}, dragState=null;

const MODE_NOTES={
  live:'Uses real hardware tags',
  emulated:'Drag tokens onto the virtual pad — no hardware needed',
  both:'Accepts both real tags and dragged tokens',
};

function setInputMode(m){
  inputMode=m;
  ['live','emulated','both'].forEach(k=>$('mode-'+k).classList.toggle('active',k===m));
  $('mode-note').textContent=MODE_NOTES[m];
}

function startLive(){
  fetch('/api/live/start',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({mode:inputMode})}).then(r=>r.json()).then(d=>{
    if(d.ok){
      liveActive=true; liveOffset=0;
      $('live-start-btn').style.display='none';
      $('live-stop-btn').style.display='';
      $('live-log').style.display='block';
      $('live-log').innerHTML='';
      $('live-status').textContent=
        inputMode==='live'?'Running — scan a tag...':
        inputMode==='emulated'?'Running — drag a token...':'Running...';
      livePoll=setInterval(pollLive,400);
      if(inputMode!=='live'){
        $('svg-pad-area').style.display='block';
        loadTokens();
        ledPoll=setInterval(pollLedState,100);
      }
    } else {
      $('live-status').textContent='Error: '+(d.error||'unknown');
    }
  });
}

function stopLive(){
  fetch('/api/live/stop',{method:'POST'}).then(()=>{
    liveActive=false;
    $('live-start-btn').style.display='';
    $('live-stop-btn').style.display='none';
    $('live-status').textContent='Stopped.';
    if(livePoll){clearInterval(livePoll);livePoll=null;}
    if(ledPoll){clearInterval(ledPoll);ledPoll=null;}
    $('svg-pad-area').style.display='none';
    tokenData=[]; tokenZones={};
    [1,2,3].forEach(z=>{
      const el=$('svg-zone-'+z);if(el)el.style.fill='rgb(0,0,0)';
      const lb=$('zone-label-'+z);if(lb)lb.textContent='';
    });
  });
}

function pollLive(){
  fetch('/api/live/log?offset='+liveOffset).then(r=>r.json()).then(d=>{
    if(d.lines&&d.lines.length){
      const log=$('live-log');
      d.lines.forEach(l=>{const el=document.createElement('div');el.textContent=l;log.appendChild(el);});
      log.scrollTop=log.scrollHeight;
      liveOffset=d.next_offset;
    }
    if(!d.active&&liveActive){
      liveActive=false;
      $('live-start-btn').style.display='';
      $('live-stop-btn').style.display='none';
      $('live-status').textContent='Stopped.';
      if(livePoll){clearInterval(livePoll);livePoll=null;}
      if(ledPoll){clearInterval(ledPoll);ledPoll=null;}
    }
  });
}

// ── LED state polling ─────────────────────────────────────────────────────────
function pollLedState(){
  fetch('/api/live/led-state').then(r=>r.json()).then(s=>{
    [1,2,3].forEach(z=>{
      const c=s[String(z)]||{r:0,g:0,b:0};
      const el=$('svg-zone-'+z);
      if(el) el.style.fill=`rgb(${c.r},${c.g},${c.b})`;
    });
  }).catch(()=>{});
}

// ── Token loading ─────────────────────────────────────────────────────────────
function loadTokens(){
  fetch('/api/live/tag-tokens').then(r=>r.json()).then(tokens=>{
    tokenData=tokens;
    tokenZones={};
    tokens.forEach(t=>tokenZones[t.uid]=null);
    renderTokenDock();
  });
}

function renderTokenDock(){
  const dock=$('token-dock');
  if(!tokenData.length){
    dock.innerHTML='<span style="color:#444;font-size:12px">No tags registered yet — enroll some in toypad_add.</span>';
    return;
  }
  dock.innerHTML='';
  tokenData.forEach(t=>{
    const placed=tokenZones[t.uid]!==null;
    const el=document.createElement('div');
    el.className='token '+t.type+(placed?' placed':'');
    el.dataset.uid=t.uid;
    el.title=t.uid;
    el.innerHTML=`<span style="font-size:9px;opacity:0.6;text-transform:uppercase">${t.type}</span> ${t.label}`;
    if(!placed) el.addEventListener('mousedown',e=>startDrag(e,t));
    dock.appendChild(el);
  });
}

// ── Drag and drop ─────────────────────────────────────────────────────────────
function startDrag(e,token){
  if(!liveActive) return;
  e.preventDefault();
  const ghost=document.createElement('div');
  ghost.className='token '+token.type+' token-ghost';
  ghost.innerHTML=`<span style="font-size:9px;opacity:0.6;text-transform:uppercase">${token.type}</span> ${token.label}`;
  ghost.style.left=(e.clientX-50)+'px';
  ghost.style.top=(e.clientY-14)+'px';
  document.body.appendChild(ghost);
  dragState={token,ghost,fromZone:tokenZones[token.uid]};
  document.addEventListener('mousemove',onDragMove);
  document.addEventListener('mouseup',onDragEnd);
}

function onDragMove(e){
  if(!dragState) return;
  dragState.ghost.style.left=(e.clientX-50)+'px';
  dragState.ghost.style.top=(e.clientY-14)+'px';
  const hz=zoneFromPoint(e.clientX,e.clientY);
  [1,2,3].forEach(z=>{
    const el=$('svg-zone-'+z); if(!el) return;
    el.setAttribute('stroke',hz===z?'#fff':'#555');
    el.setAttribute('stroke-width',hz===z?'3':'1.5');
  });
}

function onDragEnd(e){
  if(!dragState) return;
  document.removeEventListener('mousemove',onDragMove);
  document.removeEventListener('mouseup',onDragEnd);
  dragState.ghost.remove();
  const target=zoneFromPoint(e.clientX,e.clientY);
  const {token,fromZone}=dragState;
  dragState=null;
  [1,2,3].forEach(z=>{const el=$('svg-zone-'+z);if(el){el.setAttribute('stroke','#555');el.setAttribute('stroke-width','1.5');}});
  if(target===fromZone) return;
  if(fromZone!==null){
    tokenZones[token.uid]=null;
    fetch('/api/live/tag-removed',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({zone:fromZone,uid:token.uid})});
    const lb=$('zone-label-'+fromZone); if(lb) lb.textContent='';
    updateZoneCursor(fromZone);
  }
  if(target!==null){
    // evict any token already on that zone
    Object.entries(tokenZones).forEach(([uid,z])=>{
      if(z===target&&uid!==token.uid){
        tokenZones[uid]=null;
        fetch('/api/live/tag-removed',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({zone:target,uid})});
      }
    });
    tokenZones[token.uid]=target;
    fetch('/api/live/tag-placed',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({zone:target,uid:token.uid})});
    const lb=$('zone-label-'+target); if(lb) lb.textContent=token.label;
    updateZoneCursor(target);
  }
  renderTokenDock();
}

function zoneFromPoint(x,y){
  for(const z of [1,2,3]){
    const el=$('svg-zone-'+z); if(!el) continue;
    const r=el.getBoundingClientRect();
    if(z===1){
      const cx=r.left+r.width/2, cy=r.top+r.height/2, rad=r.width/2;
      if(Math.hypot(x-cx,y-cy)<=rad) return z;
    } else {
      if(x>=r.left&&x<=r.right&&y>=r.top&&y<=r.bottom) return z;
    }
  }
  return null;
}

function clickZone(z){
  if(!liveActive) return;
  const uid=Object.keys(tokenZones).find(k=>tokenZones[k]===z);
  if(!uid) return;
  tokenZones[uid]=null;
  fetch('/api/live/tag-removed',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({zone:z,uid})});
  const lb=$('zone-label-'+z); if(lb) lb.textContent='';
  const el=$('svg-zone-'+z); if(el) el.style.cursor='';
  renderTokenDock();
}

function updateZoneCursor(z){
  const el=$('svg-zone-'+z); if(!el) return;
  const occupied=Object.values(tokenZones).includes(z);
  el.style.cursor=occupied?'pointer':'';
}

// ── Save / Load ───────────────────────────────────────────────────────────────
function saveConfig(){
  const cfg=collectConfig();
  fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)})
    .then(r=>{if(r.ok){config=cfg;showToast();}else alert('Save failed.');});
}
function showToast(){
  const t=$('toast');t.style.display='block';setTimeout(()=>t.style.display='none',1800);
}
function loadConfig(){
  fetch('/api/config').then(r=>r.json()).then(cfg=>{config=cfg;populateForm();});
}

// ── Pad status ────────────────────────────────────────────────────────────────
function updatePadStatus(connected){
  const e=$('pad-status');
  e.textContent=connected?'● Pad connected':'○ Pad not connected';
  e.className='pad-status '+(connected?'on':'off');
}
function checkPad(){
  fetch('/api/pad-status').then(r=>r.json()).then(d=>updatePadStatus(d.connected))
    .catch(()=>updatePadStatus(false));
}
function reconnectPad(){
  const btn=$('reconnect-btn');
  btn.disabled=true; btn.textContent='Scanning...';
  fetch('/api/reconnect',{method:'POST'}).then(r=>r.json()).then(d=>{
    btn.disabled=false; btn.textContent='Reconnect';
    updatePadStatus(d.connected);
  }).catch(()=>{btn.disabled=false; btn.textContent='Reconnect';});
}

// ── Profiles ──────────────────────────────────────────────────────────────────
function loadProfileList(){
  fetch('/api/profiles').then(r=>r.json()).then(names=>{
    const sel=$('profile-select');
    sel.innerHTML=names.map(n=>`<option value="${n}">${n==='Default'?'Default (built-in)':n}</option>`).join('');
    onProfileChange();
  });
}
function onProfileChange(){
  $('delete-profile-btn').disabled=($('profile-select').value==='Default');
}
function loadProfile(){
  const name=$('profile-select').value;
  fetch('/api/profiles/load',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name})})
    .then(r=>r.json()).then(cfg=>{if(!cfg.error){config=cfg;populateForm();}else alert(cfg.error);});
}
function showSaveAs(){$('saveas-row').style.display='flex';}
function hideSaveAs(){$('saveas-row').style.display='none';$('profile-name-input').value='';}
function confirmSaveProfile(){
  const name=$('profile-name-input').value.trim();
  if(!name){alert('Enter a profile name.');return;}
  if(name==='Default'){alert('Cannot overwrite the Default profile.');return;}
  fetch('/api/profiles/save',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name,config:collectConfig()})})
    .then(r=>r.json()).then(d=>{
      if(d.ok){hideSaveAs();loadProfileList();showToast();}
      else alert('Save failed: '+(d.error||'unknown error'));
    });
}
function deleteProfile(){
  const name=$('profile-select').value;
  if(name==='Default')return;
  if(!confirm('Delete profile "'+name+'"?'))return;
  fetch('/api/profiles/delete',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name})})
    .then(r=>r.json()).then(d=>{
      if(d.ok)loadProfileList();
      else alert('Delete failed: '+(d.error||'unknown error'));
    });
}

// ── Help modal ────────────────────────────────────────────────────────────────
function showHelp(){$('help-modal').classList.add('on');}
function hideHelp(){$('help-modal').classList.remove('on');}

// ── Init ──────────────────────────────────────────────────────────────────────
buildZonePanels();
loadConfig();
loadProfileList();
checkPad();
setInterval(checkPad,5000);
// Populate preset dropdowns in static HTML fields
['op-cd-flash-1','op-cd-flash-2','op-cd-flash-3','op-tandem-fade'].forEach(cid=>{
  const sel=document.querySelector(`[onchange="applyPreset(this,'${cid}')"]`);
  if(sel) sel.innerHTML=presetOptions();
  updateSwatch(cid);
});
</script>
</body>
</html>"""


# ── Live preview runner ───────────────────────────────────────────────────────

import importlib, usb.core as _usb_core

def _get_runner_class():
    mod = importlib.import_module('toypad_run')
    return mod.ToyPadRunner

class LivePreviewRunner:
    """Subclass of ToyPadRunner that logs instead of opening URLs.

    mode: 'live'     — reads real USB hardware only
          'emulated' — only processes injected events (no hardware needed)
          'both'     — reads hardware AND accepts injected events
    """

    def __init__(self, dev, log_fn, mode='live', led_state=None, led_lock=None):
        base = _get_runner_class()
        cls = type('_LiveRunner', (base,), {
            '_open_url': lambda self, url: self._log(f"[WOULD OPEN] {url}"),
            '_close_url': lambda self: self._log("[BROWSER CLOSED]"),
            '_log': lambda self, msg: log_fn(msg),
        })
        self._runner   = cls(dev)
        self._stop     = threading.Event()
        self._mode     = mode
        self._orig_set_color = pad.set_color

        # Monkey-patch pad.set_color so zone threads update the shared LED state dict
        _led_state = led_state
        _led_lock  = led_lock
        _orig      = pad.set_color
        def _patched(pdev, zone_id, r, g, b):
            if _led_state is not None and _led_lock is not None:
                with _led_lock:
                    targets = [pad.PAD_CENTER, pad.PAD_LEFT, pad.PAD_RIGHT] \
                              if zone_id == pad.PAD_ALL else [zone_id]
                    for z in targets:
                        if z in _led_state:
                            _led_state[z] = (r, g, b)
            if pdev is not None:
                try:
                    _orig(pdev, zone_id, r, g, b)
                except Exception:
                    pass
        pad.set_color = _patched

    def run_live(self):
        runner = self._runner
        for z in runner.zones.values():
            z.start_passive()
        threading.Thread(target=runner._dispatch_loop, daemon=True).start()

        if self._mode == 'emulated':
            self._stop.wait()
        else:
            while not self._stop.is_set():
                try:
                    data = runner.dev.read(0x81, 32, timeout=200)
                except _usb_core.USBError:
                    continue
                if not data or data[0] != 0x56:
                    continue
                zone_id = data[2]
                placed  = (data[5] == 0x00)
                uid     = '-'.join(f'{b:02X}' for b in data[6:13])
                if zone_id not in runner.zones:
                    continue
                ev = runner._EV_PLACED if placed else runner._EV_REMOVED
                runner._events.put((ev, zone_id, uid))

        runner._events.put((None, None, None))
        for z in runner.zones.values():
            z.stop()
        if runner.dev is not None:
            pad.set_color(runner.dev, pad.PAD_ALL, 0, 0, 0)

    def inject_event(self, zone_id, uid, placed):
        runner = self._runner
        if zone_id not in runner.zones:
            return
        ev = runner._EV_PLACED if placed else runner._EV_REMOVED
        runner._events.put((ev, zone_id, uid))

    def stop(self):
        self._stop.set()
        pad.set_color = self._orig_set_color


# ── HTTP server ───────────────────────────────────────────────────────────────

class EditorServer(HTTPServer):
    def __init__(self, server_address, RequestHandlerClass, dev=None):
        super().__init__(server_address, RequestHandlerClass)
        self.dev = dev
        self._preview_stops   = {}
        self._preview_threads = {}
        self._live_runner     = None
        self._live_log        = []
        self._live_lock       = threading.Lock()
        self._led_state       = {pad.PAD_CENTER: (0,0,0),
                                  pad.PAD_LEFT:   (0,0,0),
                                  pad.PAD_RIGHT:  (0,0,0)}

    def reconnect(self):
        try:
            self.dev = pad.setup_pad()
            return True
        except Exception:
            self.dev = None
            return False

    def start_live_preview(self, mode='live'):
        if self._live_runner:
            return {'ok': False, 'error': 'Already running'}
        if mode in ('live', 'both') and not self.dev:
            return {'ok': False, 'error': 'Pad not connected'}
        for s in list(self._preview_stops.values()):
            s.set()
        self._preview_stops.clear()
        with self._live_lock:
            self._live_log = []
            for z in self._led_state:
                self._led_state[z] = (0, 0, 0)

        def log_fn(msg):
            with self._live_lock:
                self._live_log.append(msg)
                if len(self._live_log) > 300:
                    self._live_log = self._live_log[-300:]

        self._live_runner = LivePreviewRunner(
            self.dev, log_fn, mode=mode,
            led_state=self._led_state, led_lock=self._live_lock,
        )
        threading.Thread(target=self._live_runner.run_live, daemon=True).start()
        return {'ok': True}

    def stop_live_preview(self):
        if self._live_runner:
            self._live_runner.stop()
            self._live_runner = None
        with self._live_lock:
            for z in self._led_state:
                self._led_state[z] = (0, 0, 0)
        return {'ok': True}

    def get_live_log(self, offset):
        with self._live_lock:
            lines       = self._live_log[offset:]
            next_offset = len(self._live_log)
        return {'lines': lines, 'next_offset': next_offset, 'active': self._live_runner is not None}

    def get_led_state(self):
        with self._live_lock:
            return {str(z): {'r': r, 'g': g, 'b': b}
                    for z, (r, g, b) in self._led_state.items()}

    def get_tag_tokens(self):
        tags_file = Path(__file__).parent / 'tags.json'
        if not tags_file.exists():
            data = {'tags': {}, 'tandem_pairs': []}
        else:
            data = json.loads(tags_file.read_text())
        all_tags     = data.get('tags', {})
        tandem_pairs = data.get('tandem_pairs', [])
        tandem_uids  = {uid for p in tandem_pairs for uid in p.get('tags', [])}
        tokens = []
        # Two tokens from the first tandem pair
        for p in tandem_pairs[:1]:
            uids = p.get('tags', [])
            if len(uids) >= 2:
                tokens.append({'uid': uids[0], 'type': 'tandem',
                                'label': f'Tandem A  {uids[0][:11]}'})
                tokens.append({'uid': uids[1], 'type': 'tandem',
                                'label': f'Tandem B  {uids[1][:11]}'})
        # One single-only token
        for uid in all_tags:
            if uid not in tandem_uids:
                tokens.append({'uid': uid, 'type': 'single',
                                'label': f'Single  {uid[:11]}'})
                break
        # One unknown token
        tokens.append({'uid': 'DE-AD-BE-EF-00-00-00', 'type': 'unknown',
                        'label': 'Unknown tag'})
        return tokens

    def inject_tag_event(self, zone_id, uid, placed):
        if self._live_runner:
            self._live_runner.inject_event(zone_id, uid, placed)

    def preview_mode(self, zone_id, mode_cfg, passive_cfg=None):
        if zone_id in self._preview_stops:
            self._preview_stops[zone_id].set()
        stop = threading.Event()
        self._preview_stops[zone_id] = stop

        def _run():
            pad.run_mode(self.dev, zone_id, mode_cfg, stop)
            if not stop.is_set() and passive_cfg:
                passive_stop = threading.Event()
                self._preview_stops[zone_id] = passive_stop
                pad.run_mode(self.dev, zone_id, passive_cfg, passive_stop)

        t = threading.Thread(target=_run, daemon=True)
        self._preview_threads[zone_id] = t
        t.start()


class EditorHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress access log

    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/':
            self._html()
        elif path == '/api/config':
            self._serve_config()
        elif path == '/api/pad-status':
            self._pad_status()
        elif path == '/api/profiles':
            self._json(list_profiles())
        elif path == '/api/live/log':
            from urllib.parse import parse_qs, urlparse
            qs     = parse_qs(urlparse(self.path).query)
            offset = int(qs.get('offset', ['0'])[0])
            self._json(self.server.get_live_log(offset))
        elif path == '/api/live/led-state':
            self._json(self.server.get_led_state())
        elif path == '/api/live/tag-tokens':
            self._json(self.server.get_tag_tokens())
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == '/api/config':
            self._save_config()
        elif self.path == '/api/preview':
            self._run_preview()
        elif self.path == '/api/reconnect':
            connected = self.server.reconnect()
            self._json({'connected': connected})
        elif self.path == '/api/profiles/load':
            self._profile_load()
        elif self.path == '/api/profiles/save':
            self._profile_save()
        elif self.path == '/api/profiles/delete':
            self._profile_delete()
        elif self.path == '/api/live/start':
            data = self._read_body()
            self._json(self.server.start_live_preview(mode=data.get('mode', 'live')))
        elif self.path == '/api/live/stop':
            self._json(self.server.stop_live_preview())
        elif self.path == '/api/live/tag-placed':
            data = self._read_body()
            self.server.inject_tag_event(data.get('zone'), data.get('uid'), placed=True)
            self._json({'ok': True})
        elif self.path == '/api/live/tag-removed':
            data = self._read_body()
            self.server.inject_tag_event(data.get('zone'), data.get('uid'), placed=False)
            self._json({'ok': True})
        elif self.path == '/api/sound/test':
            self._test_sound()
        elif self.path == '/api/browse':
            self._browse_file()
        else:
            self.send_error(404)

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(length)
        return json.loads(raw) if raw else {}

    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def _html(self):
        body = HTML_PAGE.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def _serve_config(self):
        self._json(pad.load_led_config())

    def _pad_status(self):
        self._json({'connected': self.server.dev is not None})

    def _save_config(self):
        cfg = self._read_body()
        with open(CONFIG_FILE, 'w') as f:
            json.dump(cfg, f, indent=2)
        self._json({'ok': True})

    def _profile_load(self):
        name = self._read_body().get('name')
        try:
            self._json(get_profile(name))
        except Exception as e:
            self._json({'error': str(e)}, 400)

    def _profile_save(self):
        data = self._read_body()
        name = (data.get('name') or '').strip()
        if not name or name == DEFAULT_PROFILE_NAME:
            self._json({'error': 'Invalid name'}, 400)
            return
        save_profile(name, data.get('config', {}))
        self._json({'ok': True})

    def _profile_delete(self):
        name = self._read_body().get('name')
        if name == DEFAULT_PROFILE_NAME:
            self._json({'error': 'Cannot delete the Default profile'}, 400)
            return
        try:
            delete_profile(name)
            self._json({'ok': True})
        except Exception as e:
            self._json({'error': str(e)}, 400)

    def _run_preview(self):
        data        = self._read_body()
        zone_id     = data.get('zone')
        mode_cfg    = data.get('mode_cfg', {})
        passive_cfg = data.get('passive_cfg')
        if self.server.dev and zone_id:
            self.server.preview_mode(zone_id, mode_cfg, passive_cfg)
        self._json({'ok': True})

    def _test_sound(self):
        import os
        data = self._read_body()
        path = data.get('path', '')
        if not path:
            self._json({'ok': False, 'error': 'No path provided'}, 400)
            return
        if not os.path.isfile(path):
            self._json({'ok': False, 'error': f'File not found: {path}'}, 404)
            return
        pad.play_sound(path)
        self._json({'ok': True})

    def _browse_file(self):
        import os, subprocess
        sudo_user = os.environ.get('SUDO_USER')
        display   = os.environ.get('DISPLAY', ':0')
        cmd = [
            'yad', '--file-selection',
            '--title=Select Sound File',
            '--file-filter=Audio|*.wav *.mp3 *.ogg *.flac *.WAV *.MP3 *.OGG *.FLAC',
            '--file-filter=All files|*',
        ]
        if sudo_user:
            xauth = f'/home/{sudo_user}/.Xauthority'
            cmd = ['sudo', '-u', sudo_user, 'env',
                   f'DISPLAY={display}', f'XAUTHORITY={xauth}',
                   f'HOME=/home/{sudo_user}'] + cmd
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            self._json({'path': result.stdout.strip()})
        except Exception as e:
            self._json({'path': '', 'error': str(e)})


# ── Entry points ──────────────────────────────────────────────────────────────

def start_server(dev=None, port=8080, open_browser=False):
    server = EditorServer(('', port), EditorHandler, dev=dev)
    if open_browser:
        import webbrowser
        threading.Timer(0.6, lambda: webbrowser.open(f'http://localhost:{port}')).start()
    server.serve_forever()


if __name__ == '__main__':
    dev = None
    try:
        dev = pad.setup_pad()
        print("Pad connected.")
    except Exception as e:
        print(f"Pad not found: {e}")
        print("Running in preview-only mode — SVG preview works, pad preview disabled.\n")
    start_server(dev, open_browser=False)
