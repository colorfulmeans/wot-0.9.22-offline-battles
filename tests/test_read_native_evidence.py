"""Only complete, correctly matched fragment groups become evidence."""
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class EvidenceReaderTests(unittest.TestCase):
    def setUp(self):
        self.reader=load('_evidence_reader',ROOT/'tools/read_native_evidence.py')
        self.writer=load('_evidence_writer',ROOT/'src/res/scripts/client/gui/mods/offline_lan_0922/native_input_diagnostics.py')

    def lines(self):
        output=io.StringIO()
        with mock.patch('sys.stdout',output):
            self.writer.write_json_record('NATIVE INPUT FALLBACK',{'text':'"\\'*10000})
            self.writer.write_json_record('RICOCHET SURFACE EVIDENCE',{'damage':448})
        return output.getvalue().splitlines()

    def test_support_and_native_module_diagnostics_roundtrip(self):
        for label in ('MODULE PRESENT','BOT SUPPORT MODE','BOT LANDING IMPACT','PLAYER LANDING IMPACT','KILLER CAMERA'):
            with self.subTest(label=label):
                output=io.StringIO()
                payload=dict(phase='sample',points=[dict(valid=True)]*5)
                with mock.patch('sys.stdout',output):
                    self.writer.write_json_record(label,payload)
                result=self.reader.parse_lines(output.getvalue().splitlines())
                self.assertEqual([],result['issues'])
                self.assertEqual(payload,result['records'][0]['data'])

    def test_compact_fragment_writer_keeps_all_fields_and_engine_line_bound(self):
        payload = {'rows': [{'index': i, 'text': 'keep spaces, quotes " and \\ slashes',
                             'points': [1., 2., 3.]} for i in range(500)]}
        output = io.StringIO()
        with mock.patch('sys.stdout', output):
            self.writer.write_json_record('BOT MOTION', payload)
        lines = output.getvalue().splitlines()
        self.assertTrue(all(len(line) < 8000 for line in lines))
        parsed = self.reader.parse_lines(lines)
        self.assertEqual([], parsed['issues'])
        self.assertEqual(payload, parsed['records'][0]['data'])
        parts = [json.loads(line.split(' PART ', 1)[1]) for line in lines]
        self.assertLess(sum(len(p['data']) for p in parts), len(json.dumps(payload)))

    def test_environment_critical_native_feedback_roundtrips(self):
        payload = dict(event_id='3:3357:0', cause='world_collision', count=3,
                       mask=134479874, reason=3, target='bot:9', presented=True)
        output = io.StringIO()
        with mock.patch('sys.stdout', output):
            self.writer.write_json_record('ENV CRITICAL FEEDBACK', payload)
        result = self.reader.parse_lines(output.getvalue().splitlines())
        self.assertEqual([], result['issues'])
        self.assertEqual(payload, result['records'][0]['data'])

    def test_large_environment_contact_roundtrips_below_engine_line_limit(self):
        payload={'actor':1,'evidence':[{'name':'ammoBayHealth','witness':[1.,2.,3.],
            'direction':[0.,1.,0.],'distance':i/10.} for i in range(300)]}
        output=io.StringIO()
        with mock.patch('sys.stdout',output):
            self.writer.write_json_record('ENV MODULE CONTACT',payload)
        lines=output.getvalue().splitlines()
        self.assertTrue(all(len(line)<8000 for line in lines))
        result=self.reader.parse_lines(lines)
        self.assertEqual([],result['issues'])
        self.assertEqual(payload,result['records'][0]['data'])

    def test_writer_reader_roundtrip_and_interleaved_labels(self):
        result=self.reader.parse_lines(self.lines())
        self.assertEqual([],result['issues'])
        self.assertEqual('"\\'*10000,result['records'][0]['data']['text'])
        self.assertEqual({'damage':448},result['records'][1]['data'])

    def test_ram_geometry_fragments_preserve_all_surface_inputs(self):
        payload={'witness_source':'worker_obb_overlap', 'rays':[
            {'witness':[1.,2.,3.], 'surfaces':[{'distance':4.,'material':'leftTrackHealth'}],
             'details':'x'*1000} for unused in range(48)]}
        output=io.StringIO()
        with mock.patch('sys.stdout',output):
            self.writer.write_json_record('RAM CONTACT GEOMETRY',payload)
        result=self.reader.parse_lines(output.getvalue().splitlines())
        self.assertEqual([],result['issues'])
        self.assertEqual(payload,result['records'][0]['data'])
        self.assertTrue(all(len(line)<8192 for line in output.getvalue().splitlines()))

    def test_motion_fragments_and_legacy_truncation_are_observable(self):
        payload={'id':5,'planning_verdicts':['x'*4000]*48}
        output=io.StringIO()
        with mock.patch('sys.stdout',output):self.writer.write_json_record('BOT MOTION',payload)
        result=self.reader.parse_lines(output.getvalue().splitlines())
        self.assertEqual([],result['issues'])
        self.assertEqual(payload,result['records'][0]['data'])
        bad=self.reader.parse_lines(['[BOT MOTION] {"id":5,"text":"cut'])
        self.assertEqual(1,len(bad['issues']))

    def test_missing_or_conflicting_parts_are_not_accepted(self):
        lines=self.lines()
        missing=self.reader.parse_lines(lines[1:])
        self.assertEqual(1,len(missing['records']))
        self.assertEqual([1],missing['issues'][0]['missing_parts'])
        part=json.loads(lines[0].split('PART ',1)[1]);part['data']='conflicting data'
        conflict=self.reader.parse_lines([lines[0],'[Offline LAN 0.9.22] NATIVE INPUT FALLBACK PART '+json.dumps(part)]+lines[1:])
        self.assertEqual(1,len(conflict['records']))
        self.assertTrue(conflict['issues'][0]['conflict'])

    def test_old_truncated_records_are_reported(self):
        result=self.reader.parse_lines(['[Offline LAN 0.9.22] NATIVE INPUT FALLBACK {"inputs":'])
        self.assertEqual([],result['records'])
        self.assertEqual(1,len(result['issues']))

    def test_server_settlement_joins_by_projectile_identity(self):
        result=self.reader.parse_lines(['[19:25:00] PROJECTILE SETTLEMENT '+json.dumps({
            'projectile':'1:b:18:4','phase':'terminal_commit','actual_hp_loss':448})],'server.log')
        self.assertEqual([],result['issues'])
        self.assertEqual('1:b:18:4',result['records'][0]['data']['projectile'])
        self.assertEqual('server.log',result['records'][0]['source'])
