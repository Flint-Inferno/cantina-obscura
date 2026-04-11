"""
Demo of software-based breathe and cycle effects, per zone.
Run with: sudo python3 led_demo.py
"""

import time
import math
import toypad_lib as pad

def breathe(dev, zone, r, g, b, speed=2.0, cycles=3):
    steps = 50
    for _ in range(cycles):
        for i in range(steps * 2):
            t = i / steps
            brightness = (math.sin(math.pi * t - math.pi / 2) + 1) / 2
            pad.set_color(dev, zone,
                int(r * brightness),
                int(g * brightness),
                int(b * brightness))
            time.sleep(speed / (steps * 2))
    pad.set_color(dev, zone, 0, 0, 0)

def cycle(dev, zone, r_ceil, g_ceil, b_ceil, speed=3.0, cycles=2):
    steps = 100
    for _ in range(cycles):
        for i in range(steps):
            t = i / steps
            r = int(r_ceil * (math.sin(2 * math.pi * t) + 1) / 2)
            g = int(g_ceil * (math.sin(2 * math.pi * t + 2 * math.pi / 3) + 1) / 2)
            b = int(b_ceil * (math.sin(2 * math.pi * t + 4 * math.pi / 3) + 1) / 2)
            pad.set_color(dev, zone, r, g, b)
            time.sleep(speed / steps)
    pad.set_color(dev, zone, 0, 0, 0)

def main():
    dev = pad.setup_pad()
    print("Demo starting...\n")

    print("Breathe — green, center zone")
    breathe(dev, pad.PAD_CENTER, 0, 255, 0, speed=2.0, cycles=3)
    time.sleep(0.5)

    print("Breathe — blue, left zone")
    breathe(dev, pad.PAD_LEFT, 0, 0, 255, speed=1.5, cycles=3)
    time.sleep(0.5)

    print("Cycle — full color, right zone")
    cycle(dev, pad.PAD_RIGHT, 255, 255, 255, speed=3.0, cycles=2)
    time.sleep(0.5)

    print("Cycle — warm only (no blue), center zone")
    cycle(dev, pad.PAD_CENTER, 255, 180, 0, speed=3.0, cycles=2)
    time.sleep(0.5)

    print("Cycle — cool only (no red), left zone")
    cycle(dev, pad.PAD_LEFT, 0, 100, 255, speed=3.0, cycles=2)
    time.sleep(0.5)

    print("Done.")
    pad.set_color(dev, pad.PAD_ALL, 0, 0, 0)

if __name__ == '__main__':
    main()
