import usb.core
import usb.util
import time
import webbrowser

VENDOR_ID  = 0x0e6f
PRODUCT_ID = 0x0241

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

# ── Tag URL map ───────────────────────────────────────────────────────────────
# Add entries here: 'UID-STRING': 'https://...'
# Run the script and place a tag to see its UID printed in the terminal.
TAG_URLS = {
    'CF-00-04-BC-00-00-00': 'https://www.youtube.com/watch?v=example',
}


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
    _send(dev, [0x55, 0x06, 0xc0, pad, 0x00, r, g, b])

def flash_color(dev, pad, r, g, b, count=3, on_len=5, off_len=3):
    _send(dev, [0x55, 0x08, 0xc2, pad, on_len, off_len, count, r, g, b])


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


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    dev = setup_pad()
    print("Pad ready. Place a tag on any zone. (Ctrl-C to stop)\n")

    for pad in (PAD_LEFT, PAD_CENTER, PAD_RIGHT):
        set_color(dev, pad, 0, 0, 60)
    time.sleep(0.8)
    set_color(dev, PAD_ALL, 0, 0, 0)

    while True:
        try:
            data = dev.read(0x81, 32, timeout=500)
        except usb.core.USBError:
            continue
        except KeyboardInterrupt:
            print("\nShutting down.")
            set_color(dev, PAD_ALL, 0, 0, 0)
            break

        if data[0] != 0x56:
            continue

        pad_id = data[2]
        placed = (data[5] == 0x00)
        uid    = '-'.join(f'{b:02X}' for b in data[6:13])

        if placed:
            print(f"Tag placed  pad={pad_id}  uid={uid}")

            url = TAG_URLS.get(uid)
            if url:
                print(f"  Found: {url}")
                flash_color(dev, pad_id, 0, 255, 0, count=3)
                time.sleep(1.5)
                set_color(dev, pad_id, 0, 0, 0)
                webbrowser.open(url)
            else:
                print(f"  UID not in list.")
                flash_color(dev, pad_id, 255, 0, 0, count=3)
                time.sleep(1.5)
                set_color(dev, pad_id, 0, 0, 0)
        else:
            print(f"Tag removed pad={pad_id}")
            set_color(dev, pad_id, 0, 0, 0)

if __name__ == '__main__':
    main()
