#!/usr/bin/env python3
"""Independent floating-point GFSK -> signed ADC reference (standard library only).

Gaussian frequency shaping uses BT=0.5 by default, a continuous phase oscillator,
AWGN, carrier offset and optional inversion/corruption. No receiver metadata is
embedded in sample files. Each line is one 12-bit two's-complement hex sample.
"""
import argparse
import json
import math
from pathlib import Path
import random


def crc16(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ (0x1021 if crc & 0x8000 else 0)) & 0xFFFF
    return crc


def packet(sequence=0, corrupt=False, preamble_bits=64, sync=0xD391D391):
    data = bytes((1, sequence & 255)) + b'APEX RADIO TEST'
    raw = data + crc16(data).to_bytes(2, 'big')
    if corrupt:
        raw = raw[:-1] + bytes((raw[-1] ^ 1,))
    bits = [i & 1 for i in range(preamble_bits)]
    bits += [(sync >> i) & 1 for i in range(31, -1, -1)]
    bits += [(byte >> i) & 1 for byte in raw for i in range(7, -1, -1)]
    return bits, raw


def waveform(*, sample_rate=1_000_000, bit_rate=10_000, carrier_hz=100_000,
             deviation_hz=20_000, bt=0.5, amplitude=1400, noise=8, seed=1,
             packets=2, period=0.05, cfo=0, corrupt=False, invert=False,
             delay=0, preamble_bits=64, sync=0xD391D391):
    """Yield clipped ADC samples; Gaussian is evaluated independently of RTL FIR."""
    if sample_rate <= 0 or bit_rate <= 0 or bt <= 0 or period <= 0 or packets < 1:
        raise ValueError('rates, BT, period and packet count must be positive')
    sps = sample_rate / bit_rate
    # Gaussian frequency impulse: sigma = sqrt(ln2)/(2*pi*BT) symbols.
    sigma = math.sqrt(math.log(2)) / (2 * math.pi * bt)
    radius = math.ceil(3 * sigma * sps)
    weights = [math.exp(-0.5 * (k / sps / sigma) ** 2)
               for k in range(-radius, radius + 1)]
    norm = sum(weights)
    weights = [x / norm for x in weights]
    # Integrate kernel once: convolution of piecewise-constant NRZ is O(bits),
    # with just neighboring transitions inside its finite Gaussian support.
    prefix = [0.0]
    for weight in weights:
        prefix.append(prefix[-1] + weight)
    rng = random.Random(seed)
    phase = 0.0
    period_samples = round(period * sample_rate)
    bits, _ = packet(0, corrupt, preamble_bits, sync)
    if period_samples <= (len(bits) + 4) * sps:
        raise ValueError('packet period does not leave a guard interval')
    for index in range(packets * period_samples + delay):
        shifted = index - delay
        packet_no, local = divmod(max(0, shifted), period_samples)
        if local == 0:
            bits, _ = packet(packet_no, corrupt, preamble_bits, sync)
        # Two symbols of leading/trailing carrier permit filter transient recovery.
        position = local - round(2 * sps)
        first = max(0, math.floor((position - radius) / sps))
        last = min(len(bits) - 1, math.floor((position + radius) / sps))
        shaped = -1.0
        for bit_index in range(first, last + 1):
            if bits[bit_index]:
                left = max(0, math.ceil(bit_index * sps - position) + radius)
                right = min(len(weights), math.ceil((bit_index + 1) * sps - position) + radius)
                if right > left:
                    shaped += 2 * (prefix[right] - prefix[left])
        if invert:
            shaped = -shaped
        phase += 2 * math.pi * (carrier_hz + cfo + deviation_hz * shaped) / sample_rate
        active = shifted >= 0 and local < (len(bits) + 4) * sps
        signal = amplitude * math.cos(phase) if active else 0.0
        yield max(-2048, min(2047, round(signal + rng.gauss(0, noise))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    for name, default, typ in [('sample-rate', 1_000_000, int), ('bit-rate', 10_000, int),
                               ('carrier-hz', 100_000, float), ('deviation-hz', 20_000, float),
                               ('bt', 0.5, float), ('amplitude', 1400, float), ('noise', 8, float),
                               ('seed', 1, int), ('packets', 2, int), ('period', 0.05, float),
                               ('cfo', 0, float), ('delay', 0, int), ('preamble-bits', 64, int)]:
        parser.add_argument('--' + name, default=default, type=typ)
    parser.add_argument('--sync', type=lambda value: int(value, 0), default=0xD391D391)
    parser.add_argument('--corrupt', action='store_true')
    parser.add_argument('--invert', action='store_true')
    args = vars(parser.parse_args())
    output = args.pop('output')
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output.open('w') as stream:
        for value in waveform(**args):
            stream.write(f'{value & 0xFFF:03x}\n')
            count += 1
    output.with_suffix(output.suffix + '.json').write_text(json.dumps({
        'profile': args, 'samples': count,
        'expected_frames': [packet(seq, args['corrupt'], args['preamble_bits'], args['sync'])[1].hex()
                            for seq in range(args['packets'])]
    }, indent=2) + '\n')
    print(f'{output}: {count} samples')


if __name__ == '__main__':
    main()
