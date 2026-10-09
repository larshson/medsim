#!/usr/bin/env python3
"""Generate assets/flatline.wav: a few heart-monitor beeps, then a continuous
flatline tone. Pure stdlib (wave + math), no dependencies.

    python3 assets/make_flatline.py
"""
import math
import os
import struct
import wave

RATE = 44100
FREQ = 1000.0        # monitor beep / flatline pitch (Hz)
AMP = 0.55           # 0..1

def tone(dur, freq=FREQ, amp=AMP, fade=0.008):
    n = int(RATE * dur)
    nf = max(1, int(RATE * fade))
    out = []
    for i in range(n):
        env = 1.0
        if i < nf:
            env = i / nf
        elif i > n - nf:
            env = (n - i) / nf
        out.append(amp * env * math.sin(2 * math.pi * freq * i / RATE))
    return out

def silence(dur):
    return [0.0] * int(RATE * dur)

def build():
    s = []
    # three slowing heartbeats, then the flatline
    s += tone(0.12) + silence(0.60)
    s += tone(0.12) + silence(0.75)
    s += tone(0.12) + silence(0.45)
    s += tone(3.5)                      # flatline
    return s

def main():
    samples = build()
    path = os.path.join(os.path.dirname(__file__), "flatline.wav")
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(
            struct.pack("<h", max(-32767, min(32767, int(v * 32767))))
            for v in samples))
    print(f"wrote {path} ({os.path.getsize(path)} bytes, {len(samples)/RATE:.1f}s)")

if __name__ == "__main__":
    main()
