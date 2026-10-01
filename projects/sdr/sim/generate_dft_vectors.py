#!/usr/bin/env python3
"""Independent floating-point DFT reference vectors for rx_observer_tb.

The RTL uses a fixed-point sine table, truncating normalization and a coarse
logarithm. This reference uses math.cos/sin and math.log10 in double precision
on the same deterministic I/Q block, so the testbench checks the RTL against an
independent spectrum, power and noise computation within stated tolerances.

Output: one 32-bit hex word per line.
  lines 0..N-1    captured sample n as {Q[15:0], I[15:0]}
  lines N..2N-1   expected spectrum byte k (bin k-N/2): floor(2*(dBFS+120)), 0..255
  line 2N         expected power_dbfs_x10 (two's complement in bits 15:0)
  line 2N+1       expected noise_dbfs_x10 (outer-bin mean power times N)

Regenerate the committed files with:
  python3 projects/sdr/sim/generate_dft_vectors.py
"""
import argparse
import cmath
import math
from pathlib import Path
import random

SAMPLE_RATE_HZ = 100000
FULL_SCALE = 16384       # rx_observer default; the testbench uses the default
NOISE_EDGE_HZ = 35000


def samples(points, seed=26):
    """Two tones (one between bins) plus Gaussian noise, clipped to int16."""
    rng = random.Random(seed + points)
    tones = ((0.13 * points + 0.37, 6000.0, 0.4), (-0.3 * points, 2500.0, 1.9))
    out = []
    for n in range(points):
        value = sum(a * cmath.exp(1j * (2 * math.pi * f * n / points + ph)) for f, a, ph in tones)
        value += complex(rng.gauss(0, 1200), rng.gauss(0, 1200))
        clip = lambda x: max(-32768, min(32767, int(round(x))))
        out.append((clip(value.real), clip(value.imag)))
    return out


def reference(points, iq):
    scale = (points * FULL_SCALE) ** 2
    power = []
    for b in range(points):  # unshifted bin index; b >= N/2 is negative frequency
        x = sum(complex(i, q) * cmath.exp(-2j * math.pi * b * n / points) for n, (i, q) in enumerate(iq))
        power.append(abs(x) ** 2 / scale)
    edge = -(-NOISE_EDGE_HZ * points // SAMPLE_RATE_HZ)
    outer = [power[b] for b in range(points) if edge <= b <= points - edge]
    noise = sum(outer) / len(outer) * points
    signal = sum(i * i + q * q for i, q in iq) / points / FULL_SCALE ** 2
    to_byte = lambda p: 0 if p <= 0 else max(0, min(255, math.floor(2 * (10 * math.log10(p) + 120))))
    to_x10 = lambda p: -1200 if p <= 0 else max(-1200, round(100 * math.log10(p)))
    spectrum = [to_byte(power[(k + points // 2) % points]) for k in range(points)]
    return spectrum, to_x10(signal), to_x10(noise)


def write(path, points):
    iq = samples(points)
    spectrum, signal, noise = reference(points, iq)
    lines = ['{:04x}{:04x}'.format(q & 0xFFFF, i & 0xFFFF) for i, q in iq]
    lines += ['{:08x}'.format(b) for b in spectrum]
    lines += ['{:08x}'.format(signal & 0xFFFF), '{:08x}'.format(noise & 0xFFFF)]
    Path(path).write_text('\n'.join(lines) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', type=Path, default=Path(__file__).resolve().parent / 'vectors')
    args = parser.parse_args()
    for points in (64, 128, 256):
        write(args.out / 'dft_{}.hex'.format(points), points)


if __name__ == '__main__':
    main()
