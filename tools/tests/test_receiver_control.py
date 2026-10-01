import struct
import unittest
from dataclasses import replace
from sdr_cli.freqplan import TuningState, with_lo
from sdr_cli.protocol import crc16_ccitt
from sdr_cli.receiver_control import command, profile_for, tuning_words


class ReceiverControlTests(unittest.TestCase):
    def test_profiles_by_build_id(self):
        self.assertEqual(profile_for(0x53445231)['id'], 'default')
        apex = profile_for(0x53445246)
        self.assertEqual(apex['id'], 'apex_demo')
        self.assertIn('441.480 MHz', apex['rf_label'])
        self.assertEqual(profile_for(0x1234), {'id': 'unknown', 'label': 'Unknown build 0x00001234'})

    def test_wire_command(self):
        data = command(17, 0x11223344, 0xaabbccdd, False)
        self.assertEqual(len(data), 15)
        self.assertEqual(data[:13], b'SR\x01\x11\x44\x33\x22\x11\xdd\xcc\xbb\xaa\x00')
        self.assertEqual(struct.unpack('<H', data[13:])[0], crc16_ccitt(data[:13]))
        with self.assertRaises(ValueError):
            command(255, 0, 0)

    def test_requested_lo_changes_adc_carrier_only(self):
        state = TuningState()
        before = tuning_words(state)
        after = tuning_words(with_lo(state, 441_350_000))
        self.assertNotEqual(before[0], after[0])
        self.assertEqual(before[1], after[1])
        self.assertTrue(after[2])
        self.assertFalse(tuning_words(with_lo(state, 440_000_000))[2])

    def test_unsupported_profile_rejected(self):
        for change in [dict(fs_hz=2_000_000), dict(injection='high'), dict(filter_hz=20_000), dict(target_if_hz=120_000), dict(window_hz=20_000)]:
            with self.assertRaises(ValueError):
                tuning_words(replace(TuningState(), **change))


class TuningControllerTests(unittest.TestCase):
    def setUp(self):
        from sdr_cli.receiver_control import TuningController
        self.state = TuningState()
        self.sent = []
        self.now = 0
        self.control = TuningController(lambda: self.state, self.sent.append, lambda: self.now)

    def report(self, sequence=255, words=None, status=0):
        from sdr_cli import protocol as p
        words = words or tuning_words(self.state)
        record = p.StreamDecoder().feed(p.encode_message(p.CONFIG, p.build_payload(p.CONFIG, dict(
            command_seq=sequence, status=status, carrier_ftw=words[0], nco_ftw=words[1], enable=words[2]))))[0]
        self.control.observe(record)

    def test_no_write_until_capability_and_matching_ack(self):
        self.control.tick()
        self.assertEqual(self.sent, [])
        self.report()
        baseline = dict(self.control.applied)
        self.state = with_lo(self.state, 441_360_000)
        self.control.tick()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.control.state, 'pending')
        self.assertIsNone(self.control.applied)
        self.report(sequence=99)
        self.assertIsNone(self.control.applied)
        self.report(sequence=0, words=(1, 2, True))
        self.assertIsNone(self.control.applied)
        self.report(sequence=0)
        self.assertEqual(self.control.state, 'applied')
        self.assertEqual(self.control.applied['lo_hz'], 441_360_000)
        self.assertFalse(self.control.applied['inferred'])

    def test_timeout_bounded_retries_and_no_false_apply(self):
        self.report()
        baseline = dict(self.control.applied)
        self.control.tick()
        for t in (1, 2, 3, 4, 5):
            self.now = t
            self.control.tick()
        self.assertEqual(len(self.sent), 3)
        self.assertEqual(len(set(self.sent)), 1)
        self.assertEqual(self.control.state, 'timeout')
        self.assertIsNone(self.control.applied)
        self.report(sequence=0)
        self.assertEqual(self.control.state, 'timeout')

    def test_coalesces_changes_without_relabelling_pending_ack(self):
        self.report()
        self.state = with_lo(self.state, 441_360_000)
        first = tuning_words(self.state)
        self.control.tick()
        self.state = with_lo(self.state, 441_370_000)
        self.control.tick()
        self.assertEqual(len(self.sent), 1)
        self.report(sequence=0, words=first)
        self.assertEqual(self.control.applied['lo_hz'], 441_360_000)
        self.control.tick()
        self.assertEqual(len(self.sent), 2)
        self.report(sequence=1)
        self.assertEqual(self.control.applied['lo_hz'], 441_370_000)

    def test_unsupported_profile_and_rejection(self):
        self.report()
        self.state = replace(self.state, fs_hz=2_000_000)
        self.control.tick()
        self.assertEqual(self.sent, [])
        self.assertEqual(self.control.state, 'unsupported')
        self.state = TuningState()
        self.control.tick()
        self.report(sequence=0, status=1)
        self.assertEqual(self.control.state, 'rejected')

    def test_dbfs_flags_preserve_legacy_units(self):
        from sdr_cli import protocol as p
        for flags, unit in [(p.FLAG_SYNTHETIC, 'dBm'), (p.FLAG_SYNTHETIC | p.FLAG_DBFS, 'dBFS')]:
            wire = p.encode_message(p.CHAN_METRICS, p.build_payload(p.CHAN_METRICS, dict(rssi_dbm_x10=-230)), flags=flags)
            record = p.StreamDecoder().feed(wire)[0]
            self.assertEqual(record.fields['power_unit'], unit)
            self.assertIn('-23.0'+unit, p.describe(record))

    def test_hub_preserves_reference_across_ack_in_same_uart_chunk(self):
        from sdr_cli import protocol as p
        from sdr_cli.hub import Hub
        from sdr_cli.sources import SerialSource
        class Session:
            config = dict(port='test', baud=1000000)
            port = 'test'
            def __init__(self, config):
                self.sent = []
            def send(self, data):
                self.sent.append(data)
        source = SerialSource({}, session_factory=Session, get_tuning=lambda: self.state)
        hub = Hub()
        hub.set_source(source, 'running')
        def message(kind, fields, seq):
            return p.encode_message(kind, p.build_payload(kind, fields), seq=seq)
        def config(command_seq, words, seq):
            return message(p.CONFIG, dict(command_seq=command_seq, carrier_ftw=words[0],
                nco_ftw=words[1], enable=words[2], status=0), seq)
        def spectrum(seq):
            return message(p.SPECTRUM, dict(channel=0, power=[12,13], bin_mhz=1000000), seq)
        def lo(out):   # SPECTRUM_ROW flags bit1 marks an rf_reference; rf_lo_hz is field 12
            from sdr_cli import gui_wire
            head = gui_wire.SPECTRUM_HEADER.unpack_from(out.data)
            return head[12] if head[3] & gui_wire.FLAG_RF_REFERENCE else None
        first = hub.feed(spectrum(0), source)[0]
        self.assertIsNone(lo(first))
        source.control.tick()
        self.assertEqual(source.session.sent, [])
        hub.feed(config(255, tuning_words(self.state), 1), source)
        old_lo = source.control.applied['lo_hz']
        self.state = with_lo(self.state, 441_360_000)
        source.control.tick()
        rows = hub.feed(spectrum(2)+config(0, tuning_words(self.state), 3)+spectrum(4), source)
        self.assertEqual([r.channel for r in rows], ['spectrum.A', 'link', 'spectrum.A'])
        self.assertIsNone(lo(rows[0]))
        self.assertEqual(lo(rows[2]), 441_360_000)


    def test_lost_ack_report_restores_reference_without_command_success(self):
        self.report()
        self.state = with_lo(self.state, 441_360_000)
        self.control.tick()
        wanted = tuning_words(self.state)
        self.assertIsNone(self.control.applied)
        self.report(words=(1, 2, True))
        self.assertIsNone(self.control.applied)
        for t in (1, 2, 3):
            self.now = t
            self.control.tick()
        self.assertEqual(self.control.state, 'timeout')
        self.assertIsNone(self.control.applied)
        self.state = with_lo(self.state, 441_370_000)
        self.report(words=wanted)
        self.assertEqual(self.control.state, 'timeout')
        self.assertEqual(self.control.applied['confirmed_by'], 'report')
        self.assertEqual(self.control.applied['lo_hz'], 441_360_000)
        self.assertIn('acknowledgement missing', self.control.error)

    def test_hub_stats_refresh_pending_and_timeout_without_uart_data(self):
        from sdr_cli.hub import Hub
        controller = self.control
        class Source:
            kind, detail, responds_to_tuning = 'serial', 'quiet', True
            def source_state(self):
                return controller.snapshot()
        hub = Hub()
        self.report()
        hub.set_source(Source(), 'running')
        self.control.tick()
        self.assertEqual(hub.stats_message()['source']['control_state'], 'pending')
        for t in (1, 2, 3):
            self.now = t
            self.control.tick()
        status = hub.stats_message()['source']
        self.assertEqual(status['control_state'], 'timeout')
        self.assertIsNone(status['applied'])
        self.assertIn('application unknown', status['control_error'])


    def test_reboot_report_restores_requested_tuning_once(self):
        defaults = tuning_words(self.state)
        self.report(words=defaults)
        self.state = with_lo(self.state, 441_360_000)
        wanted = tuning_words(self.state)
        self.control.tick()
        self.report(sequence=0, words=wanted)
        self.assertEqual(self.control.state, 'applied')
        for _ in range(3):
            self.report(words=wanted)
            self.control.tick()
        self.assertEqual(len(self.sent), 1)
        self.report(words=defaults)
        self.assertEqual(self.control.state, 'out_of_sync')
        self.assertEqual(self.control.applied['carrier_ftw'], defaults[0])
        self.control.tick()
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.control.state, 'pending')
        self.report(sequence=1, words=wanted)
        self.assertEqual(self.control.state, 'applied')
        self.assertEqual(self.control.applied['lo_hz'], 441_360_000)
        for _ in range(3):
            self.report(words=wanted)
            self.control.tick()
        self.assertEqual(len(self.sent), 2)
