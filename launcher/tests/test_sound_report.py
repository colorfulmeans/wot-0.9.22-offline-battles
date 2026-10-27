"""Native errors retain session-local context and exact bank membership."""
import json
import os
import struct
import tempfile
import unittest
import zipfile

import sound_report


class SoundReportTests(unittest.TestCase):
    def test_partial_error_scan_and_event_correlation(self):
        scanner=sound_report.SoundScanner()
        scanner.feed(b'SOUND CALL {"stage":"begin","call":1,"event_ids":[{"name":"event","id":123}]}\n')
        scanner.feed(b'[SOUND_ERROR] Sound fail: 123 - Error')
        scanner.feed(b'Code: 15\n')
        row=scanner.result()
        self.assertEqual(1,row['error_count'])
        self.assertEqual(1,row['retained_errors'][0]['recent'][0]['call'])
        self.assertEqual(['event'],row['event_names']['123'])

    def test_exact_hirc_id_and_no_match_from_unrelated_data(self):
        with tempfile.TemporaryDirectory() as root:
            path=os.path.join(root,'res','packages');os.makedirs(path)
            hirc=struct.pack('<IBII',1,4,4,123)
            blob=b'HIRC'+struct.pack('<I',len(hirc))+hirc
            with zipfile.ZipFile(os.path.join(path,'audioww.pkg'),'w') as archive:
                archive.writestr('audioww/test.bnk',blob)
                archive.writestr('audioww/not_an_event.bnk',b'DATA'+struct.pack('<II',4,456))
            data=sound_report.bank_membership(root,{123,456})
            self.assertEqual([123],[r['resource_id'] for r in data['matches']])
            self.assertTrue(data['matches'][0]['event'])

    def test_normal_entry_does_not_generate_sound_section(self):
        self.assertIsNone(sound_report.describe({'worker':sound_report.SoundScanner()},None))

    def test_event_action_and_embedded_media_structure_is_not_engine_load_proof(self):
        def obj(kind,identifier,data):
            return struct.pack('<BII',kind,4+len(data),identifier)+data
        def chunk(kind,data):return kind+struct.pack('<I',len(data))+data
        with tempfile.TemporaryDirectory() as root:
            folder=os.path.join(root,'res','packages');os.makedirs(folder)
            hirc=struct.pack('<I',2)+obj(4,123,b'\x02'+struct.pack('<II',42,99))+obj(3,42,b'actual-action')
            blob=chunk(b'BKHD',struct.pack('<I',111))+chunk(b'HIRC',hirc)+chunk(b'DIDX',
                struct.pack('<IIIIII',7,0,4,8,3,4))+chunk(b'DATA',b'1234')
            with zipfile.ZipFile(os.path.join(folder,'audioww.pkg'),'w') as z:z.writestr('audioww/test.bnk',blob)
            row=sound_report.bank_membership(root,{123})['matches'][0]['structure']
            self.assertEqual(111,row['bkhd_first_u32'])
            self.assertEqual([True,False],[a['present'] for a in row['actions']])
            self.assertEqual([8],row['invalid_embedded_ranges'])
            self.assertFalse(row['engine_load_observed'])

    def test_error_retention_is_explicit_and_bounded(self):
        scanner=sound_report.SoundScanner()
        for unused in range(140):scanner.feed(b'Sound fail: 123 - ErrorCode: 15\n')
        self.assertEqual(140,scanner.error_count)
        self.assertEqual(128,len(scanner.errors))
