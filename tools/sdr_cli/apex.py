"""APEX flight-computer radio frames (provisional).

Layouts mirror ~/git/apex fsw/src/radio.cpp and sim/scripts/radio_gfsk_rx.py:
type byte, little-endian body, CRC-16-CCITT (init 0xFFFF) over type+body, sent
big-endian. Replace or extend once the defined flight telemetry format is supplied.
"""
import struct

from .protocol import crc16_ccitt

TEST, FLIGHT, HOUSEKEEPING = 0x01, 0x02, 0x03
KINDS = {TEST: 'TEST', FLIGHT: 'FLIGHT', HOUSEKEEPING: 'HK'}
TEST_TEXT_LEN = 15
FLIGHT_STRUCT = struct.Struct('<6sHBBbBff7hBHbbH')   # 41 bytes
HK_STRUCT = struct.Struct('<H3h3h2hH')              # 20 bytes
PHASES = ('IDLE', 'ARMED', 'BOOST', 'COAST', 'DESCENT', 'LANDED')
BODY_LEN = {TEST: 1 + TEST_TEXT_LEN, FLIGHT: FLIGHT_STRUCT.size, HOUSEKEEPING: HK_STRUCT.size}


def _flight(body):
    (callsign, seq, phase_status, health, gps_fix, gps_sats, lat, lon, gps_alt, alt, vel, apogee,
     vacc, accel_z, roll, deploy, baro2, btemp, tilt, azimuth) = FLIGHT_STRUCT.unpack(body)
    phase = phase_status & 0x07
    return dict(callsign=callsign.decode('ascii', 'replace').strip('\x00 '), seq=seq,
                phase=PHASES[phase] if phase < len(PHASES) else 'UNKNOWN', health=health,
                gps_fix=gps_fix, gps_sats=gps_sats, lat_deg=lat, lon_deg=lon, gps_alt_m=gps_alt * 0.5,
                alt_agl_m=alt * 0.1, velocity_mps=vel * 0.02, pred_apogee_m=apogee * 0.1,
                vert_accel_mps2=vacc * 0.01, accel_z_mps2=accel_z * 0.01, roll_rate_rads=roll * 0.002,
                deployment=deploy / 255.0, baro_pa=baro2 * 2.0, baro_temp_c=btemp, tilt_deg=tilt,
                azimuth_deg=azimuth * 0.1)


def _housekeeping(body):
    seq, mx, my, mz, hx, hy, hz, gx, gy, up = HK_STRUCT.unpack(body)
    return dict(seq=seq, mag_gauss=(mx * 1e-4, my * 1e-4, mz * 1e-4),
                highg_mps2=(hx * 0.1, hy * 0.1, hz * 0.1), gyro_xy_rads=(gx * 0.002, gy * 0.002), uptime_s=up)


def parse_frame(raw):
    """Parse type+body+CRC bytes. Never raises; malformed frames report crc_ok False."""
    raw = bytes(raw)
    ftype = raw[0] if raw else None
    result = dict(type=ftype, kind=KINDS.get(ftype, 'UNKNOWN'), crc_ok=False, fields={})
    if len(raw) < 3:
        return result
    data, crc_rx = raw[:-2], (raw[-2] << 8) | raw[-1]
    result['crc_ok'] = crc16_ccitt(data) == crc_rx
    body = data[1:]
    if len(body) != BODY_LEN.get(ftype, -1):
        result['fields'] = dict(body_len=len(body))
        return result
    if ftype == TEST:
        result['fields'] = dict(seq=body[0], text=body[1:].decode('ascii', 'replace'))
    elif ftype == FLIGHT:
        result['fields'] = _flight(body)
    else:
        result['fields'] = _housekeeping(body)
    return result


def summary(frame):
    """One-line description used by the CLI and dashboard."""
    f = frame['fields']
    text = frame['kind']
    if 'seq' in f:
        text += ' seq={}'.format(f['seq'])
    if frame['kind'] == 'TEST' and 'text' in f:
        text += ' {!r}'.format(f['text'])
    elif frame['kind'] == 'FLIGHT' and 'phase' in f:
        text += ' {} alt={:.1f}m v={:.1f}m/s'.format(f['phase'], f['alt_agl_m'], f['velocity_mps'])
    elif frame['kind'] == 'HK' and 'uptime_s' in f:
        text += ' up={}s'.format(f['uptime_s'])
    return text + ('' if frame['crc_ok'] else ' CRC-BAD')


def build_test_frame(seq, good=True):
    """APEX TEST frame as the FPGA stand-in sends it; good=False flips the CRC's last bit."""
    data = bytes([TEST, seq & 0xFF]) + b'APEX RADIO TEST'
    crc = crc16_ccitt(data) ^ (0 if good else 1)
    return data + bytes([crc >> 8, crc & 0xFF])
