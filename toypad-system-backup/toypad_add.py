"""
Toy Pad tag enrollment tool.

Enroll single tags (UID → URL) or tandem pairs (two UIDs + individual URLs + pair URL).
Saved to tags.json.

Run with:  sudo python3 toypad_add.py
"""

import json
import os
import subprocess
import threading
import time
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import toypad_lib as pad

TAGS_FILE         = Path(__file__).parent / 'tags.json'
GITHUB_PAGES_BASE = 'https://flint-inferno.github.io/cantina-obscura'
RUNNER_URL        = 'http://localhost:8082'
EDITOR_PORT       = 8082
CANTINA_REPO      = Path(__file__).parent / 'cantina-obscura'
MISSION_EDITOR_HTML = Path(__file__).parent / 'mission_editor.html'
FONT_PATH         = Path(__file__).parent / 'AurebeshAF-Canon.otf'
GH_OWNER          = 'Flint-Inferno'
GH_REPO           = 'cantina-obscura'
PAT_FILE          = Path(__file__).parent / 'gh_pat.txt'
SCANNER_BEEP      = Path.home() / '.claude' / 'scanner_beep.wav'
def _scanner_beep():
    if SCANNER_BEEP.exists():
        subprocess.Popen(['aplay', '-D', 'plughw:1,0', '-q', str(SCANNER_BEEP)],
                         stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL)




_editor_server = None  # set once the mini server is started


# ── Mini editor HTTP server (used when runner isn't running) ──────────────────

class _EditorHandler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass  # silence request logs

    def do_GET(self):
        p = self.path.split('?')[0]
        if p == '/mission-editor':
            self._serve_bytes(MISSION_EDITOR_HTML, 'text/html; charset=utf-8')
        elif p == '/api/mission':
            self._serve_mission()
        elif p == '/AurebeshAF-Canon.otf':
            self._serve_bytes(FONT_PATH, 'font/otf')
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == '/api/mission':
            self._save_mission()
        else:
            self.send_error(404)

    def _serve_bytes(self, path, ctype):
        try:
            body = Path(path).read_bytes()
        except FileNotFoundError:
            self.send_error(404); return
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def _serve_mission(self):
        qs    = parse_qs(urlparse(self.path).query)
        fname = (qs.get('file', [''])[0]).strip()
        if not fname.endswith('.html') or '/' in fname or '..' in fname:
            self.send_error(400); return
        target   = CANTINA_REPO / fname
        template = CANTINA_REPO / 'mission-template.html'
        if target.exists():
            self._json({'exists': True,  'content': target.read_text(encoding='utf-8')})
        elif template.exists():
            self._json({'exists': False, 'content': template.read_text(encoding='utf-8')})
        else:
            self._json({'exists': False, 'content': ''})

    def _save_mission(self):
        length = int(self.headers.get('Content-Length', 0))
        if not length:
            self.send_error(400); return
        body  = json.loads(self.rfile.read(length))
        fname = body.get('file', '').strip()
        if not fname.endswith('.html') or '/' in fname or '..' in fname:
            self._json({'ok': False, 'error': 'Invalid filename'}); return
        try:
            (CANTINA_REPO / fname).write_text(body.get('content', ''), encoding='utf-8')
        except Exception as e:
            self._json({'ok': False, 'error': str(e)}); return
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


def _open_browser(url):
    """Open a URL in a plain Firefox window (no kiosk profile required)."""
    sudo_user = os.environ.get('SUDO_USER')
    if sudo_user:
        display = os.environ.get('DISPLAY', ':0')
        xauth   = f'/home/{sudo_user}/.Xauthority'
        subprocess.Popen(
            ['sudo', '-u', sudo_user, 'env',
             f'DISPLAY={display}', f'XAUTHORITY={xauth}',
             f'HOME=/home/{sudo_user}', 'firefox', url],
            stdin=subprocess.DEVNULL)
    else:
        subprocess.Popen(['firefox', url], stdin=subprocess.DEVNULL)


def _ensure_editor_server():
    """Start the mini editor server if the runner isn't already running."""
    global _editor_server
    if _runner_alive():
        return  # runner handles it
    if _editor_server is not None:
        return  # already started
    server = HTTPServer(('', EDITOR_PORT), _EditorHandler)
    _editor_server = server
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"  (Mini editor server started on port {EDITOR_PORT})")


# ── Data helpers ──────────────────────────────────────────────────────────────

def load_tags():
    if not TAGS_FILE.exists():
        return {'tags': {}, 'tandem_pairs': []}
    data = json.load(open(TAGS_FILE))
    if isinstance(data, dict) and 'tags' not in data and 'tandem_pairs' not in data:
        return {'tags': data, 'tandem_pairs': []}
    return {'tags': data.get('tags', {}), 'tandem_pairs': data.get('tandem_pairs', [])}


def save_tags(data):
    with open(TAGS_FILE, 'w') as f:
        json.dump(data, f, indent=2)


def find_pair_for_uid(uid, pairs):
    for p in pairs:
        if uid in p['tags']:
            return p
    return None


# ── GitHub API helpers ────────────────────────────────────────────────────────

def _load_pat():
    """Return cached GitHub PAT, or prompt and save it."""
    if PAT_FILE.exists():
        pat = PAT_FILE.read_text().strip()
        if pat:
            return pat
    print(f"\n  GitHub Personal Access Token needed to create live pages.")
    print(f"  (Saved to {PAT_FILE.name} for future use.)")
    pat = input("  PAT: ").strip()
    if pat:
        PAT_FILE.write_text(pat)
    return pat or None


def create_github_live_page(name, pat):
    """Create live-page-links/{name}.html on GitHub from the mission template.

    Fetches mission-template.html from the repo via GitHub API and PUTs the
    new file into live-page-links/.  Returns the GitHub Pages URL on success,
    or None on failure.
    """
    import urllib.error

    gh_base = f'https://api.github.com/repos/{GH_OWNER}/{GH_REPO}/contents'
    headers = {
        'Authorization': f'Bearer {pat}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }

    def _gh_get(path):
        req = urllib.request.Request(f'{gh_base}/{path}', headers=headers)
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    # Fetch template (content is already base64 from the API)
    print("  Fetching mission template from GitHub...")
    try:
        tmpl = _gh_get('mission-template.html')
    except urllib.error.HTTPError as e:
        print(f"  ERROR: Could not fetch template ({e.code}).")
        return None
    encoded = tmpl['content'].replace('\n', '')  # strip newlines in base64 block

    filepath = f'live-page-links/{name}.html'

    # Check if file already exists (need SHA to overwrite)
    sha = None
    try:
        existing = _gh_get(filepath)
        sha = existing.get('sha')
        ans = input(f"  '{name}.html' already exists. Overwrite? (y/n): ").strip().lower()
        if ans != 'y':
            # Return existing URL without re-creating
            return f'{GITHUB_PAGES_BASE}/live-page-links/{name}.html'
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"  ERROR checking existing file: {e.code}")
            return None
        # 404 — new file, proceed

    # PUT the new file
    body = {
        'message': f'Add tandem live page: {name}.html',
        'content': encoded,
    }
    if sha:
        body['sha'] = sha

    req = urllib.request.Request(
        f'{gh_base}/{filepath}',
        data=json.dumps(body).encode(),
        method='PUT',
        headers={**headers, 'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req) as r:
            json.loads(r.read())
        print(f"  Created: {filepath}")
    except urllib.error.HTTPError as e:
        print(f"  ERROR creating page: {e.code} {e.read().decode()[:200]}")
        return None

    return f'{GITHUB_PAGES_BASE}/live-page-links/{name}.html'


# ── Enrollment helpers ────────────────────────────────────────────────────────

def scan_tag(dev, prompt="Place a tag on the pad..."):
    print(f"  {prompt}")
    uid, pad_id = pad.wait_for_tag(dev)
    pad.set_color(dev, pad_id, 0, 0, 60)
    return uid, pad_id


def _runner_alive():
    try:
        urllib.request.urlopen(f'{RUNNER_URL}/api/status', timeout=1)
        return True
    except Exception:
        return False


def ask_url(label="Paste URL", existing=None, uid=None):
    """Prompt for a URL, offering (A) paste or (B) open the mission page editor.

    uid — if provided, option B uses {uid}.html as the filename (single /
          individual tandem URLs).  If None, the user types a custom name
          (tandem pair URL).
    """
    hint = f" [{existing}]" if existing else ""
    print(f"\n  {label}{hint}")
    print("  (A) Paste a link")
    print("  (B) Create / Edit a mission page")
    if uid is None:
        print("  (C) Create a named live page on GitHub  ← new tandem page")
    print("  (S) Skip / leave unchanged")

    while True:
        choice = input("  > ").strip().upper()

        if choice == 'S':
            return existing

        elif choice == 'A':
            while True:
                val = input("  URL: ").strip()
                if val:
                    return val
                if existing:
                    print("  (Enter to keep existing, or type a URL)")
                    return existing
                print("  URL cannot be empty.")

        elif choice == 'B':
            _ensure_editor_server()

            if uid:
                fname = f"{uid}.html"
            else:
                while True:
                    name = input("  Page filename (no spaces, no extension): ").strip()
                    if name and ' ' not in name and all(c.isalnum() or c in '-_' for c in name):
                        fname = name if name.lower().endswith('.html') else f"{name}.html"
                        break
                    print("  Use letters, numbers, and hyphens only (e.g. DEAD-STAR).")

            url        = f"{GITHUB_PAGES_BASE}/{fname}"
            editor_url = f"{RUNNER_URL}/mission-editor?file={fname}"
            print(f"\n  Opening editor: {editor_url}")
            print(f"  GitHub Pages URL will be: {url}")
            _open_browser(editor_url)
            input("\n  Edit the page in the browser, click ▲ COMMIT, then press Enter here...")
            return url

        elif choice == 'C' and uid is None:
            while True:
                name = input("  Page name (letters, numbers, hyphens — e.g. jabba-palace): ").strip()
                if name and all(c.isalnum() or c == '-' for c in name):
                    break
                print("  Use letters, numbers, and hyphens only.")
            pat = _load_pat()
            if not pat:
                print("  No PAT provided — cancelling.")
                continue
            url = create_github_live_page(name, pat)
            if url:
                print(f"\n  Tandem page URL: {url}")
                return url
            print("  Failed to create the live page. Try again or choose another option.")

        else:
            print("  Enter A, B, C, or S." if uid is None else "  Enter A, B, or S.")


def verify_url(dev, pad_id, url):
    import sys, termios
    print("  Opening in Firefox to verify...")
    pad.open_url_tab(url)
    time.sleep(1)
    termios.tcflush(sys.stdin, termios.TCIFLUSH)
    confirm = input("  Save this URL? (y/n): ").strip().lower()
    return confirm == 'y'


# ── Enrollment flows ──────────────────────────────────────────────────────────

def enroll_single(dev):
    print("\n── Enroll Single Tag ──")
    uid, pad_id = scan_tag(dev)
    print(f"  Tag UID: {uid}")

    data = load_tags()
    existing_url = data['tags'].get(uid)
    if existing_url:
        print(f"  (Already assigned to: {existing_url})")
    pair = find_pair_for_uid(uid, data['tandem_pairs'])
    if pair:
        print(f"  (Also part of tandem pair with URL: {pair['url']})")

    url = ask_url(existing=existing_url, uid=uid)
    if url is None:
        print("  No URL set — skipped.")
        pad.set_color(dev, pad_id, 0, 0, 0)
        return
    if url == existing_url:
        print("  No changes.")
        pad.set_color(dev, pad_id, 0, 0, 0)
        return
    if not verify_url(dev, pad_id, url):
        pad.set_color(dev, pad_id, 255, 80, 0)
        print("  Skipped.")
        time.sleep(1)
        pad.set_color(dev, pad_id, 0, 0, 0)
        return

    data['tags'][uid] = url
    save_tags(data)
    pad.flash_color(dev, pad_id, 0, 255, 0, count=2)
    print(f"  Saved. ({len(data['tags'])} single tag(s) in tags.json)")
    time.sleep(1)
    pad.set_color(dev, pad_id, 0, 0, 0)


def enroll_tandem(dev):
    print("\n── Enroll Tandem Pair ──")
    print("  Tandem tags open a special URL when placed on LEFT + RIGHT together.")
    print("  Each tag also keeps its own individual URL for center scans.\n")

    # First tag
    uid_a, pad_a = scan_tag(dev, "Place the FIRST tandem tag on the pad...")
    print(f"  Tag A UID: {uid_a}")
    data = load_tags()
    existing_a = data['tags'].get(uid_a)
    if existing_a:
        print(f"  (Individual URL already set: {existing_a})")
    url_a = ask_url("Individual URL for Tag A (center scans)", existing=existing_a, uid=uid_a)

    pad.set_color(dev, pad_a, 0, 0, 0)
    time.sleep(0.5)

    # Second tag
    uid_b, pad_b = scan_tag(dev, "Place the SECOND tandem tag on the pad...")
    if uid_b == uid_a:
        print("  Same tag scanned twice. Aborting.")
        pad.set_color(dev, pad_b, 0, 0, 0)
        return
    print(f"  Tag B UID: {uid_b}")
    data = load_tags()
    existing_b = data['tags'].get(uid_b)
    if existing_b:
        print(f"  (Individual URL already set: {existing_b})")
    url_b = ask_url("Individual URL for Tag B (center scans)", existing=existing_b, uid=uid_b)

    pad.set_color(dev, pad_b, 0, 0, 0)
    time.sleep(0.5)

    # Tandem URL
    existing_pair = find_pair_for_uid(uid_a, data['tandem_pairs'])
    existing_tandem = existing_pair['url'] if existing_pair else None
    url_tandem = ask_url("Tandem URL (opened when BOTH tags are on L+R together)", existing=existing_tandem)

    # Verify tandem URL only if it changed
    if url_tandem and url_tandem != existing_tandem:
        print("  Opening tandem URL in Firefox to verify...")
        _open_browser(url_tandem)
        time.sleep(1)
        confirm = input("  Save this tandem pair? (y/n): ").strip().lower()
        if confirm != 'y':
            print("  Skipped.")
            return

    # Save individual URLs (only if not skipped)
    data = load_tags()
    if url_a is not None:
        data['tags'][uid_a] = url_a
    if url_b is not None:
        data['tags'][uid_b] = url_b

    # Update tandem pair only if a URL is set
    if url_tandem is not None:
        data['tandem_pairs'] = [
            p for p in data['tandem_pairs']
            if uid_a not in p['tags'] and uid_b not in p['tags']
        ]
        data['tandem_pairs'].append({'tags': [uid_a, uid_b], 'url': url_tandem})

    save_tags(data)
    pad.flash_color(dev, pad_a, 0, 255, 0, count=2)
    pad.flash_color(dev, pad_b, 0, 255, 0, count=2)
    print(f"  Saved. ({len(data['tandem_pairs'])} tandem pair(s) in tags.json)")


def list_enrolled():
    data = load_tags()
    print(f"\n── Enrolled Tags ({len(data['tags'])}) ──")
    if data['tags']:
        for uid, url in data['tags'].items():
            print(f"  {uid}  →  {url}")
    else:
        print("  (none)")

    print(f"\n── Tandem Pairs ({len(data['tandem_pairs'])}) ──")
    if data['tandem_pairs']:
        for i, p in enumerate(data['tandem_pairs'], 1):
            print(f"  Pair {i}: {p['tags'][0]}")
            print(f"         + {p['tags'][1]}")
            print(f"         → {p['url']}")
    else:
        print("  (none)")


def delete_entry(dev):
    data = load_tags()
    print("\n── Delete Entry ──")
    print("  (1) Delete a single tag")
    print("  (2) Delete a tandem pair")
    choice = input("  > ").strip()

    if choice == '1':
        if not data['tags']:
            print("  No single tags enrolled.")
            return
        list_enrolled()
        uid = input("  Enter UID to delete: ").strip().upper()
        if uid in data['tags']:
            del data['tags'][uid]
            save_tags(data)
            print(f"  Deleted {uid}.")
        else:
            print("  UID not found.")

    elif choice == '2':
        if not data['tandem_pairs']:
            print("  No tandem pairs enrolled.")
            return
        list_enrolled()
        uid = input("  Enter either UID from the pair to delete: ").strip().upper()
        before = len(data['tandem_pairs'])
        data['tandem_pairs'] = [p for p in data['tandem_pairs'] if uid not in p['tags']]
        if len(data['tandem_pairs']) < before:
            save_tags(data)
            print(f"  Pair containing {uid} deleted.")
        else:
            print("  UID not found in any pair.")


# ── Bulk local enrollment ─────────────────────────────────────────────────────

def bulk_enroll_local(dev):
    print("\n── Bulk Tag Register ──")
    print("  Scans tags and registers each UID → GitHub Pages URL in tags.json.")
    print("  Press Ctrl+C to stop.\n")

    tags_data = load_tags()
    created   = 0

    try:
        while True:
            uid, pad_id = scan_tag(dev)
            colon_uid = uid.replace('-', ':')
            url       = f'{GITHUB_PAGES_BASE}/nfc-tag-redirects/{colon_uid}.html'

            print(f"\n  UID : {uid}")
            print(f"  URL : {url}")

            if uid in tags_data['tags']:
                existing = tags_data['tags'][uid]
                if existing == url:
                    print("  Already registered. Skipped.")
                    pad.set_color(dev, pad_id, 255, 80, 0)
                    time.sleep(1)
                    pad.set_color(dev, pad_id, 0, 0, 0)
                    continue
                print(f"  Replacing existing URL: {existing}")

            tags_data['tags'][uid] = url
            save_tags(tags_data)
            created += 1
            _scanner_beep()

            pad.flash_color(dev, pad_id, 0, 255, 0, count=2)
            print(f"  Registered. Scan next tag...")
            time.sleep(1)
            pad.set_color(dev, pad_id, 0, 0, 0)

    except KeyboardInterrupt:
        print(f"\n  Done. {created} tag(s) registered in tags.json.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    dev = pad.setup_pad()
    pad.startup_flash(dev)

    while True:
        print("\n══ Toy Pad Enrollment ══")
        print("  (1) Enroll single tag")
        print("  (2) Enroll tandem pair")
        print("  (3) List enrolled")
        print("  (4) Delete entry")
        print("  (5) Bulk register tags to tags.json")
        print("  (q) Quit")
        choice = input("  > ").strip().lower()

        if choice == '1':
            enroll_single(dev)
        elif choice == '2':
            enroll_tandem(dev)
        elif choice == '3':
            list_enrolled()
        elif choice == '4':
            delete_entry(dev)
        elif choice == '5':
            bulk_enroll_local(dev)
        elif choice == 'q':
            break
        else:
            print("  Invalid choice.")

    print("Done.")


if __name__ == '__main__':
    main()
