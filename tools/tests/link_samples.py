"""A small synthetic link stream containing every message type (mirrors rtl/link_test_sources.sv)."""
from sdr_cli import protocol as p
from sdr_cli.apex import build_test_frame as apex_test_frame


def sample_messages(slots=3):
    msgs = [(p.STATUS, dict(version=2, channels=3, uptime_ms=1500, build_id=0x1234, dropped=0))]
    for slot in range(slots):
        bad_b = slot == 1
        msgs.append((p.BEST_TELEM, dict(t_us=slot * 50000, source=0, raw=apex_test_frame(slot))))
        for ch, rssi in ((0, -716), (1, -781)):
            ok = not (ch == 1 and bad_b)
            msgs.append((p.CHAN_FRAME, dict(channel=ch, crc_ok=int(ok), t_us=slot * 50000, rssi_dbm_x10=rssi,
                                            quality=200 - 30 * ch, freq_offset_hz=10300,
                                            raw=apex_test_frame(slot, ok))))
    for ch in (0, 1):
        msgs.append((p.CHAN_METRICS, dict(channel=ch, rssi_dbm_x10=-716 - 65 * ch, noise_dbm_x10=-1000,
                                          snr_db_x10=284 - 65 * ch, freq_offset_hz=10300, sync_hits=slots,
                                          crc_good=slots - ch, crc_bad=ch)))
        for row in range(4):
            power = [24 + (k * 7 + row) % 16 for k in range(256)]
            power[90] = power[218] = 140
            msgs.append((p.SPECTRUM, dict(channel=ch, averages=1, row=row, t_us=row * 100000, center_hz=100000,
                                          bin_mhz=390625, db_ref_x10=-1200, db_step_x100=50, power=power)))
        msgs.append((p.IQ_SNAPSHOT, dict(channel=ch, t_us=0, sample_rate_hz=100000,
                                         iq=[(8000 >> ch, 0), (0, 8000 >> ch), (-8000 >> ch, 0), (0, -8000 >> ch)])))
    msgs.append((p.LINK_STATS, dict(from_a=slots, from_b=0, both_ok=slots - 1, neither_ok=0, best_sent=slots)))
    return msgs


def sample_stream(slots=3):
    return b''.join(p.encode_message(t, p.build_payload(t, f), seq=n)
                    for n, (t, f) in enumerate(sample_messages(slots)))
