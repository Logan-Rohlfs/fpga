"""FPGA-to-host link protocol: COBS-framed, CRC-checked, typed messages.

Wire format (docs/superpowers/specs/2026-09-29-host-link-layer-design.md):
COBS(type u8, flags u8, seq u8, len u16 LE, payload, crc16 LE) followed by 0x00.
"""
from collections import Counter, deque
from dataclasses import dataclass, field
import struct
import time

FLAG_SYNTHETIC, FLAG_EMPTY = 0x01, 0x02
STATUS, BEST_TELEM, CHAN_FRAME = 0x01, 0x10, 0x11
CHAN_METRICS, LINK_STATS = 0x20, 0x21
SPECTRUM, IQ_SNAPSHOT = 0x30, 0x31
TYPE_NAMES = {STATUS: 'STATUS', BEST_TELEM: 'BEST_TELEM', CHAN_FRAME: 'CHAN_FRAME',
              CHAN_METRICS: 'CHAN_METRICS', LINK_STATS: 'LINK_STATS', SPECTRUM: 'SPECTRUM',
              IQ_SNAPSHOT: 'IQ_SNAPSHOT'}
PROTOCOL_VERSION = 2   # STATUS.version; v2 added spectrum/IQ axis metadata
HEADER = struct.Struct('<BBBH')
MAX_PAYLOAD = 512
CHANNELS = ('A', 'B')
SOURCES = ('A', 'B', 'combined')

# type: (fixed struct, field names, variable tail kind, tail count field)
SCHEMAS = {
    STATUS: ('<BBIIH', ('version', 'channels', 'uptime_ms', 'build_id', 'dropped'), None, None),
    BEST_TELEM: ('<IBB', ('t_us', 'source', 'frame_len'), 'raw', 'frame_len'),
    CHAN_FRAME: ('<BBIhBiB', ('channel', 'crc_ok', 't_us', 'rssi_dbm_x10', 'quality', 'freq_offset_hz',
                              'frame_len'), 'raw', 'frame_len'),
    CHAN_METRICS: ('<BBhhhiIII', ('channel', 'rsvd', 'rssi_dbm_x10', 'noise_dbm_x10', 'snr_db_x10',
                                  'freq_offset_hz', 'sync_hits', 'crc_good', 'crc_bad'), None, None),
    LINK_STATS: ('<IIIII', ('from_a', 'from_b', 'both_ok', 'neither_ok', 'best_sent'), None, None),
    # Bin k is centered at center_hz + (k - bins/2) * bin_hz, lowest frequency first.
    # Power in dBFS is db_ref + power[k] * db_step.
    SPECTRUM: ('<BBHHIiIhBB', ('channel', 'averages', 'row', 'bins', 't_us', 'center_hz', 'bin_mhz',
                               'db_ref_x10', 'db_step_x100', 'rsvd'), 'power', 'bins'),
    # int16 I/Q, full scale ±32767, captured at sample_rate_hz starting at t_us.
    IQ_SNAPSHOT: ('<BBHII', ('channel', 'rsvd', 'pairs', 't_us', 'sample_rate_hz'), 'iq', 'pairs'),
}


def crc16_ccitt(data, crc=0xFFFF):
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
        crc &= 0xFFFF
    return crc


def cobs_encode(data):
    """Same single-pass algorithm as rtl/cobs_encoder.sv (code 0xFF closes a block)."""
    out = bytearray([0])
    code_at, code = 0, 1
    for byte in data:
        if byte == 0:
            out[code_at] = code
            code_at, code = len(out), 1
            out.append(0)
        else:
            out.append(byte)
            code += 1
            if code == 0xFF:
                out[code_at] = code
                code_at, code = len(out), 1
                out.append(0)
    out[code_at] = code
    return bytes(out)


def cobs_decode(data):
    if not data or 0 in data:
        raise ValueError('empty or contains delimiter')
    out = bytearray()
    i = 0
    while i < len(data):
        code = data[i]
        end = i + code
        if end > len(data):
            raise ValueError('block overruns message')
        out += data[i + 1:end]
        i = end
        if code < 0xFF and i < len(data):
            out.append(0)
    return bytes(out)


def build_payload(mtype, fields):
    """Pack raw-unit fields into a payload (used by tests, golden vectors, and simulators)."""
    if mtype not in SCHEMAS:
        return bytes(fields.get('payload', b''))
    fmt, names, tail, count = SCHEMAS[mtype]
    values = dict(fields)
    tail_bytes = b''
    if tail == 'raw':
        tail_bytes = bytes(values.get('raw', b''))
        values[count] = len(tail_bytes)
    elif tail == 'power':
        tail_bytes = bytes(values.get('power', []))
        values[count] = len(tail_bytes)
    elif tail == 'iq':
        pairs = values.get('iq', [])
        tail_bytes = b''.join(struct.pack('<hh', i, q) for i, q in pairs)
        values[count] = len(pairs)
    return struct.pack(fmt, *[values.get(n, 0) for n in names]) + tail_bytes


def encode_message(mtype, payload, seq=0, flags=FLAG_SYNTHETIC):
    if len(payload) > MAX_PAYLOAD:
        raise ValueError('payload too long')
    body = HEADER.pack(mtype, flags, seq & 0xFF, len(payload)) + bytes(payload)
    return cobs_encode(body + struct.pack('<H', crc16_ccitt(body))) + b'\x00'


@dataclass
class Record:
    type: int
    name: str
    flags: int
    seq: int
    fields: dict = field(default_factory=dict)
    t: float = 0.0

    @property
    def synthetic(self):
        return bool(self.flags & FLAG_SYNTHETIC)

    def as_json(self):
        return dict(t=self.t, type=self.name, seq=self.seq, flags=self.flags, synthetic=self.synthetic,
                    fields={k: v for k, v in self.fields.items() if k != 'raw'},
                    raw=self.fields['raw'].hex() if 'raw' in self.fields else None)


class LengthError(ValueError):
    pass


class CrcError(ValueError):
    pass


def _parse_payload(mtype, payload):
    if mtype not in SCHEMAS:
        return dict(payload=bytes(payload))
    fmt, names, tail, count = SCHEMAS[mtype]
    size = struct.calcsize(fmt)
    if len(payload) < size:
        raise LengthError('payload shorter than fixed fields')
    f = dict(zip(names, struct.unpack_from(fmt, payload)))
    rest = payload[size:]
    expected = {None: 0, 'raw': f.get(count, 0), 'power': f.get(count, 0), 'iq': 4 * f.get(count, 0)}[tail]
    if len(rest) != expected:
        raise LengthError('variable field length mismatch')
    f.pop('rsvd', None)
    if 'channel' in f:
        f['channel'] = CHANNELS[f['channel']] if f['channel'] < 2 else str(f['channel'])
    if tail == 'raw':
        from . import apex
        f['raw'] = bytes(rest)
        f['apex'] = apex.parse_frame(rest)
    elif tail == 'power':
        f['power'] = list(rest)
    elif tail == 'iq':
        f['iq'] = [struct.unpack_from('<hh', rest, 4 * n) for n in range(f['pairs'])]
    if mtype == BEST_TELEM:
        f['source'] = SOURCES[f['source']] if f['source'] < 3 else str(f['source'])
    if 'crc_ok' in f:
        f['crc_ok'] = bool(f['crc_ok'])
    for key in ('rssi_dbm', 'noise_dbm', 'snr_db'):
        if key + '_x10' in f:
            f[key] = f.pop(key + '_x10') / 10.0
    if 'quality' in f:
        f['quality'] = f['quality'] / 255.0
    if mtype == SPECTRUM:
        f['bin_hz'] = f.pop('bin_mhz') / 1000.0
        f['db_ref'] = f.pop('db_ref_x10') / 10.0
        f['db_step'] = f.pop('db_step_x100') / 100.0
    return f


def bin_frequency(fields, k):
    """Center frequency in Hz (FPGA IF domain) of spectrum bin k."""
    return fields['center_hz'] + (k - fields['bins'] // 2) * fields['bin_hz']


def power_db(fields):
    """Spectrum bins converted to dBFS."""
    return [fields['db_ref'] + v * fields['db_step'] for v in fields['power']]


def parse_message(raw, t=None):
    """Parse one un-COBSed message. Raises LengthError or CrcError."""
    if len(raw) < HEADER.size + 2:
        raise LengthError('message too short')
    mtype, flags, seq, length = HEADER.unpack_from(raw)
    if len(raw) != HEADER.size + length + 2:
        raise LengthError('length field disagrees with message size')
    (crc,) = struct.unpack_from('<H', raw, len(raw) - 2)
    if crc16_ccitt(raw[:-2]) != crc:
        raise CrcError('crc mismatch')
    name = TYPE_NAMES.get(mtype, 'UNKNOWN(0x{:02X})'.format(mtype))
    return Record(mtype, name, flags, seq, _parse_payload(mtype, raw[HEADER.size:-2]),
                  time.time() if t is None else t)


class StreamDecoder:
    """Incremental decoder. Bytes before the first delimiter that do not decode count as resync."""
    MAX_BUFFER = 4 * (MAX_PAYLOAD + 16)

    def __init__(self):
        self.buffer = bytearray()
        self.synced = False
        self.last_seq = None
        self.stats = dict(bytes=0, messages=0, by_type=Counter(), crc_errors=0, cobs_errors=0,
                          length_errors=0, resync_bytes=0, seq_gaps=0, synthetic=0)

    def _reject(self, kind, chunk):
        if self.synced:
            self.stats[kind] += 1
        else:
            self.stats['resync_bytes'] += len(chunk) + 1

    def feed(self, data):
        self.stats['bytes'] += len(data)
        self.buffer += data
        records = []
        while True:
            end = self.buffer.find(0)
            if end < 0:
                break
            chunk = bytes(self.buffer[:end])
            del self.buffer[:end + 1]
            if not chunk:
                continue
            try:
                record = parse_message(cobs_decode(chunk))
            except CrcError:
                self._reject('crc_errors', chunk)
                continue
            except LengthError:
                self._reject('length_errors', chunk)
                continue
            except ValueError:
                self._reject('cobs_errors', chunk)
                continue
            self.synced = True
            if self.last_seq is not None:
                self.stats['seq_gaps'] += (record.seq - self.last_seq - 1) & 0xFF
            self.last_seq = record.seq
            self.stats['messages'] += 1
            self.stats['by_type'][record.name] += 1
            self.stats['synthetic'] += record.synthetic
            records.append(record)
        if len(self.buffer) > self.MAX_BUFFER:
            self.stats['resync_bytes'] += len(self.buffer)
            self.buffer.clear()
            self.synced = False
        return records


class LinkState:
    """Latest decoded view shared by the CLI summary and the dashboard."""
    WINDOW = 5.0

    def __init__(self, history=64):
        self.status = None
        self.link_stats = None
        self.metrics = {}
        self.iq = {}
        self.frames = deque(maxlen=history)
        self.best = deque(maxlen=history)
        self.spectrum = {ch: deque(maxlen=history) for ch in CHANNELS}
        self.synthetic = False
        self.arrivals = deque()

    def update(self, records):
        for r in records:
            self.synthetic = r.synthetic
            self.arrivals.append((r.t, r.name))
            if r.type == STATUS:
                self.status = r
            elif r.type == LINK_STATS:
                self.link_stats = r
            elif r.type == CHAN_METRICS:
                self.metrics[r.fields['channel']] = r
            elif r.type == CHAN_FRAME:
                self.frames.append(r)
            elif r.type == BEST_TELEM:
                self.best.append(r)
            elif r.type == SPECTRUM:
                self.spectrum.setdefault(r.fields['channel'], deque(maxlen=self.frames.maxlen)).append(r)
            elif r.type == IQ_SNAPSHOT:
                self.iq[r.fields['channel']] = r

    def rates(self, now=None):
        now = time.time() if now is None else now
        while self.arrivals and self.arrivals[0][0] < now - self.WINDOW:
            self.arrivals.popleft()
        counts = Counter(name for _, name in self.arrivals)
        return {name: n / self.WINDOW for name, n in counts.items()}


def _khz(hz):
    return '{:+.2f}kHz'.format(hz / 1000.0)


def describe(r):
    """Record body without timestamp, for CLI lines and dashboard lists."""
    f = r.fields
    if r.type == STATUS:
        text = 'v{} up={:.3f}s build=0x{:08x} dropped={} ch={}'.format(
            f['version'], f['uptime_ms'] / 1000.0, f['build_id'], f['dropped'],
            ''.join(c for n, c in enumerate(CHANNELS) if f['channels'] >> n & 1) or '-')
        if f['version'] != PROTOCOL_VERSION:
            text += ' [HOST EXPECTS v{}: rebuild/program the FPGA]'.format(PROTOCOL_VERSION)
    elif r.type in (BEST_TELEM, CHAN_FRAME):
        from . import apex
        if r.type == BEST_TELEM:
            text = 'src={} t={}us'.format(f['source'], f['t_us'])
        else:
            text = '{} crc={} rssi={:.1f}dBm q={:.2f} df={}'.format(
                f['channel'], 'ok' if f['crc_ok'] else 'BAD', f['rssi_dbm'], f['quality'], _khz(f['freq_offset_hz']))
        text += '  APEX ' + apex.summary(f['apex'])
    elif r.type == CHAN_METRICS:
        text = '{} rssi={:.1f}dBm noise={:.1f}dBm snr={:.1f}dB df={} sync={} good={} bad={}'.format(
            f['channel'], f['rssi_dbm'], f['noise_dbm'], f['snr_db'], _khz(f['freq_offset_hz']),
            f['sync_hits'], f['crc_good'], f['crc_bad'])
    elif r.type == LINK_STATS:
        text = 'from_A={from_a} from_B={from_b} both_ok={both_ok} neither={neither_ok} best={best_sent}'.format(**f)
    elif r.type == SPECTRUM:
        power = f['power']
        peak = max(range(len(power)), key=power.__getitem__) if power else 0
        text = '{} row={} bins={}×{:.1f}Hz @{} peak={} {:.1f}dBFS'.format(
            f['channel'], f['row'], f['bins'], f['bin_hz'], _khz(f['center_hz']),
            _khz(bin_frequency(f, peak)), power_db(f)[peak] if power else 0.0)
    elif r.type == IQ_SNAPSHOT:
        mags = [(i * i + q * q) ** .5 for i, q in f['iq']]
        text = '{} pairs={} @{}S/s |iq|avg={:.0f}'.format(f['channel'], f['pairs'], f['sample_rate_hz'],
                                                        sum(mags) / len(mags) if mags else 0)
    else:
        text = '{} payload bytes'.format(len(f.get('payload', b'')))
    return text + (' [SIMULATED]' if r.synthetic else '') + (' [EMPTY]' if r.flags & FLAG_EMPTY else '')


def format_record(r):
    stamp = time.strftime('%H:%M:%S', time.localtime(r.t)) + '.{:02d}'.format(int(r.t * 100) % 100)
    return '{} #{:03d} {:<12} {}'.format(stamp, r.seq, r.name, describe(r))


def summarize(stats, seconds, synthetic=None):
    """Human summary of a decode session: per-type counts/rates and error counters."""
    seconds = max(seconds, 1e-9)
    lines = ['{:<14}{:>8}{:>10}'.format('MESSAGE', 'COUNT', 'RATE/s')]
    names = list(TYPE_NAMES.values()) + sorted(set(stats['by_type']) - set(TYPE_NAMES.values()))
    for name in names:
        n = stats['by_type'].get(name, 0)
        lines.append('{:<14}{:>8}{:>10.1f}'.format(name, n, n / seconds))
    lines.append('decoded={messages} crc_err={crc_errors} cobs_err={cobs_errors} len_err={length_errors} '
                 'seq_gaps={seq_gaps} resync_bytes={resync_bytes}'.format(**stats))
    if stats['synthetic']:
        lines.append('{} of {} messages are SIMULATED (stand-in FPGA producers, not RF measurements).'.format(
            stats['synthetic'], stats['messages']))
    return lines


def golden_vectors():
    """Inputs shared by the host tests and rtl/cobs_encoder testbench."""
    import random
    rng = random.Random(29)
    header = HEADER.pack(STATUS, FLAG_SYNTHETIC, 5, 12) + build_payload(
        STATUS, dict(version=PROTOCOL_VERSION, channels=3, uptime_ms=1000, build_id=0, dropped=0))
    message = header + struct.pack('<H', crc16_ccitt(header))
    return [b'\x42', b'\x00', b'\x00\x00', b'\x11\x22\x00\x33', b'\x01' * 254, b'\x01' * 255,
            b'\x01' * 253 + b'\x00', b'\xab' * 508, bytes(rng.choice([0, rng.randrange(1, 256)]) for _ in range(600)),
            message]


GOLDEN_WORDS = 8192   # cobs_encoder_tb.sv golden[] size


def write_golden(path):
    """16-bit $readmemh words: n_in, in..., n_out, out..., repeated, then FFFF."""
    words = []
    for data in golden_vectors():
        encoded = cobs_encode(data) + b'\x00'
        words += [len(data), *data, len(encoded), *encoded]
    if len(words) >= GOLDEN_WORDS:
        raise ValueError('golden vectors exceed the testbench array')
    words += [0xFFFF] * (GOLDEN_WORDS - len(words))   # terminator; padding fills the $readmemh range
    with open(path, 'w') as out:
        out.write('// Generated by: PYTHONPATH=tools python3 -m sdr_cli.protocol --golden PATH\n')
        out.write('\n'.join('{:04x}'.format(w) for w in words) + '\n')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Link protocol utilities')
    parser.add_argument('--golden', help='Write COBS golden vectors for the RTL testbench')
    parser.add_argument('--check', help='Decode a raw capture; fail on errors or missing message types')
    args = parser.parse_args()
    if args.golden:
        write_golden(args.golden)
    if args.check:
        decoder = StreamDecoder()
        with open(args.check, 'rb') as capture:
            decoder.feed(capture.read())
        s = decoder.stats
        missing = sorted(set(TYPE_NAMES.values()) - set(s['by_type']))
        errors = s['crc_errors'] + s['cobs_errors'] + s['length_errors'] + s['seq_gaps']
        print('Host decode of {}: {} messages {}, errors={}, resync={}B, missing={}'.format(
            args.check, s['messages'], dict(s['by_type']), errors, s['resync_bytes'], missing or 'none'))
        raise SystemExit(1 if errors or missing or s['resync_bytes'] else 0)
