"""Observer-only rejection diagnostics must not change input behavior."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock


PATH = Path(__file__).resolve().parents[1] / 'src/res/scripts/client/gui/mods/offline_lan_0922/native_input_diagnostics.py'


class NativeInputDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('_isolated_native_input_diagnostics', PATH)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.output = io.StringIO()
        self.stream = mock.patch.object(sys, 'stdout', self.output)
        self.stream.start()
        self.addCleanup(self.stream.stop)

    def records(self):
        records, pending = [], {}
        for line in self.output.getvalue().splitlines():
            if 'NATIVE INPUT FALLBACK PART ' in line:
                part=json.loads(line.split('NATIVE INPUT FALLBACK PART ',1)[1])
                key=(part['pid'],part['record'])
                pending.setdefault(key,[]).append(part['data'])
                if part['part']==part['parts']:
                    records.append(json.loads(''.join(pending.pop(key))))
            else:
                records.append(json.loads(line.split('NATIVE INPUT FALLBACK ',1)[1]))
        self.assertFalse(pending)
        return records

    def test_large_record_roundtrips_without_crossing_engine_line_limit(self):
        payload={'text':'"\\'*50000,'method':'destr_prepare'}
        self.module._write_record(payload)
        self.assertEqual([payload],self.records())
        self.assertTrue(all(len(line.encode('utf-8'))<7000
                            for line in self.output.getvalue().splitlines()))

    def test_signature_is_canonical_without_using_the_python_json_encoder(self):
        first={'z':[{'type':'float','length':3}],'a':1}
        second={'a':1,'z':[{'length':3,'type':'float'}]}
        with mock.patch.object(self.module.json,'dumps',side_effect=AssertionError('encoder')):
            self.assertEqual(self.module.structural_signature(first),
                             self.module.structural_signature(second))

    def test_prepare_quota_preserves_counts_and_other_method_reports(self):
        for i in range(20):
            self.module.record('destr_prepare',tuple(range(i)))
        self.module.record('control_pose',({'x':1.},))
        self.assertEqual(5,len(self.records()))
        self.assertEqual(21,sum(self.module.snapshot()['counts'].values()))

    def test_native_profile_mapping_matches_the_two_destructible_interfaces(self):
        self.module.record('destr_prepare',())
        self.module.record('destr_required_chunks',())
        rows=self.records()
        self.assertEqual({'family':'destr_query','opcode':8},rows[0]['native_profile'])
        self.assertEqual({'family':'destr_query','opcode':9},rows[1]['native_profile'])

    def test_summary_keeps_suppressed_counts_and_round_identity(self):
        for i in range(20):self.module.record('destr_prepare',tuple(range(i)))
        self.output.seek(0);self.output.truncate()
        self.module.log_summary('round_end',2)
        row=json.loads(self.output.getvalue().split('NATIVE INPUT SUMMARY ',1)[1])
        self.assertEqual(20,sum(row['counts'].values()))
        self.assertEqual(4,row['reports'])
        self.assertEqual(2,row['round'])
        self.assertEqual('round_end',row['phase'])

    def test_only_requested_entrypoints_are_observed(self):
        self.module.record('projectile_math', (0, (), ()))
        self.module.record('other', ())
        self.assertEqual([], self.records())
        self.assertEqual({}, self.module.snapshot()['counts'])

    def test_value_changes_do_not_create_unbounded_shapes(self):
        for i in range(100):
            self.module.record('control_pose', ({'x': float(i), 'position': (float(i), 0., 0.)},))
        records = self.records()
        self.assertEqual(1, len(records))
        self.assertEqual(100, sum(self.module.snapshot()['counts'].values()))
        self.assertEqual('control_pose', records[0]['method'])
        self.assertTrue(records[0]['callers'])

    def test_chunk_failure_captures_later_boxes_and_all_point_values(self):
        boxes=tuple(((float(i),0.,1.),((1.,0.,0.),(0.,1.,0.),(0.,0.,1.))) for i in range(20))
        self.module.record('destr_required_chunks',(boxes,(.25,100.)))
        row=self.records()[0]
        inputs=row['inputs']['items']
        self.assertTrue(inputs[0]['complete'])
        self.assertEqual(19.,inputs[0]['items'][19]['items'][0]['items'][0]['value'])
        self.assertEqual(1.,inputs[0]['items'][19]['items'][1]['items'][2]['items'][2]['value'])
        self.assertEqual(100.,inputs[1]['items'][1]['value'])

    def test_reports_are_capped_but_counts_continue(self):
        for i in range(100):
            self.module.record('driver_geometry', (i, (), (), ()))
        snapshot = self.module.snapshot()
        self.assertEqual(16, len(self.records()))
        self.assertEqual(100, sum(snapshot['counts'].values()))
        self.assertLessEqual(len(snapshot['counts']), 33)

    def test_hostile_scalar_sequence_and_mapping_are_not_evaluated(self):
        events = []
        class Trap:
            def __getattribute__(self, key):
                events.append(('getattribute', key))
                raise AssertionError(key)
            def __float__(self):
                events.append('float')
                raise AssertionError
            def __iter__(self):
                events.append('iter')
                raise AssertionError
            def __len__(self):
                events.append('len')
                raise AssertionError
            def __repr__(self):
                events.append('repr')
                raise AssertionError
            def __str__(self):
                events.append('str')
                raise AssertionError
            def __eq__(self, other):
                events.append('eq')
                raise AssertionError
        class Sequence(list):
            def __iter__(self):
                events.append('sequence_iter')
                raise AssertionError
            def __len__(self):
                events.append('sequence_len')
                raise AssertionError
            def __getitem__(self, key):
                events.append('sequence_getitem')
                raise AssertionError
        class Mapping(dict):
            def items(self):
                events.append('mapping_items')
                raise AssertionError
            def get(self, *args):
                events.append('mapping_get')
                raise AssertionError
        self.module.record('control_pose', ({'position': Trap(), 'speed': Sequence([1.]),
                                            'shape': Mapping(a=1)},))
        self.assertEqual([], events)
        self.assertEqual(1, len(self.records()))

    def test_custom_metaclass_is_not_called_for_type_metadata(self):
        events = []
        class Meta(type):
            def __getattribute__(self, key):
                events.append(key)
                raise AssertionError(key)
        class Value(metaclass=Meta):
            pass
        self.module.record('control_pose', ({'position': Value()},))
        self.assertEqual([], events)
        self.assertEqual(1, len(self.records()))

    def test_foreign_dictionary_keys_are_neither_hashed_nor_compared(self):
        events = []
        class Key:
            active = False
            def __hash__(self):
                if self.active:
                    events.append('hash')
                    raise AssertionError
                return 17
            def __eq__(self, other):
                if self.active:
                    events.append('eq')
                    raise AssertionError
                return self is other
        key = Key()
        value = {key: object(), 'x': 1.}
        key.active = True
        self.module.record('control_pose', (value,))
        self.assertEqual([], events)
        self.assertEqual(1, len(self.records()))

    def test_generator_is_not_consumed(self):
        events = []
        def generated():
            events.append('yield')
            yield 3.
        value = generated()
        self.module.record('control_pose', ({'position': value},))
        self.assertEqual([], events)
        self.assertEqual(3., next(value))

    def test_recursion_and_huge_samples_are_bounded(self):
        value = {'x': 1 << 10000, 'velocity': float('nan')}
        value['position'] = value
        self.module.record('control_pose', (value,))
        self.assertEqual(1, len(self.records()))
        text = self.output.getvalue()
        self.assertLess(len(text), 16000)
        self.assertIn('integer_outside_int64', text)
        self.assertIn('nonfinite', text)

    def test_failed_output_stream_does_not_escape(self):
        class BadStream:
            def write(self, value):
                raise RuntimeError('stream unavailable')
        with mock.patch.object(sys, 'stdout', BadStream()):
            self.module.record('control_pose', ({'x': 1.},))
        self.assertEqual(1, sum(self.module.snapshot()['counts'].values()))

    def test_observer_retains_no_input_reference(self):
        source = {'position': [1., 2., 3.]}
        before = sys.getrefcount(source)
        self.module.record('control_pose', (source,))
        self.assertEqual(before, sys.getrefcount(source))
        self.assertEqual({'position': [1., 2., 3.]}, source)

    def test_exception_message_is_never_rendered(self):
        class Error(Exception):
            def __str__(self):
                raise AssertionError('rendered user exception')
        error = Error()
        self.module.record('control_pose', ({},), 'exception', error)
        self.assertEqual(1, len(self.records()))
        self.assertIsNotNone(self.records()[0]['exception_type'])


if __name__ == '__main__':
    unittest.main()
