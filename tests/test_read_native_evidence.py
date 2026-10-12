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

    def test_writer_reader_roundtrip_and_interleaved_labels(self):
        result=self.reader.parse_lines(self.lines())
        self.assertEqual([],result['issues'])
        self.assertEqual('"\\'*10000,result['records'][0]['data']['text'])
        self.assertEqual({'damage':448},result['records'][1]['data'])

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
