"""Stream past the reported 768-MiB failure through both real readers."""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT=Path(__file__).resolve().parents[1]
CLIENT=ROOT/'src/res/scripts/client/gui/mods/offline_lan_0922'

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value

writer=module('capacity_writer',ROOT/'tools/replay/replay_writer_process.py')
reader=module('capacity_reader',ROOT/'tools/replay/replay_reader_process.py')
legacy=module('capacity_legacy',CLIENT/'offline_replay.py')

def start(directory):
    path=str(Path(directory)/'replay_last_battle.wotlanreplay');session='a'*32
    return dict(op='start',seq=0,path=path,temp=path+'.'+session+'.part',
        session=session,mode=1,started_wall=100.,header=dict(welcome={},
        start={'type':'battle_start'},snapshot={},config={}))

class ReplayCapacityTests(unittest.TestCase):
    def test_all_stream_limits_match_and_row_bounds_stay_small(self):
        self.assertEqual(8*1024**3,writer.MAX_TOTAL)
        self.assertEqual(writer.MAX_TOTAL,reader.MAX_TOTAL)
        self.assertEqual(writer.MAX_TOTAL,legacy.MAX_TOTAL)
        self.assertEqual(2*1024**2,writer.MAX_LINE)
        self.assertEqual(writer.MAX_LINE,reader.MAX_LINE)
        self.assertEqual(writer.MAX_LINE,legacy.MAX_LINE)

    def test_real_compressed_stream_above_old_limit_publishes_and_reads_to_end(self):
        with tempfile.TemporaryDirectory() as directory:
            w=writer.Writer(start(directory));payload={'type':'snapshot','data':'a'*(1024*1024)}
            try:
                for i in range(770):
                    w.append(dict(op='record',seq=i+1,kind='wire',t=i,data=payload))
                self.assertGreater(w.bytes,768*1024**2)
                path=w.finish(dict(seq=771,records=770,reason='battle_finished'))
            finally:
                w.abort()
            self.assertFalse(Path(w.temp).exists())
            r=legacy.Reader(path);count=0
            try:
                while True:
                    row=r.next()
                    if row is None:break
                    if row['type']=='wire':count+=1
                self.assertTrue(r.ended)
            finally:r.close()
            self.assertEqual(770,count)
            kinds=[]
            with mock.patch.object(reader,'send',side_effect=lambda kind,value:kinds.append((kind,value.get('type')))):
                reader.read(path)
            self.assertEqual(772,len(kinds))
            self.assertEqual(('row','end'),kinds[-1])

    def test_total_limit_logs_values_and_abort_preserves_previous_complete_recording(self):
        with tempfile.TemporaryDirectory() as directory:
            args=start(directory);path=Path(args['path']);path.write_bytes(b'previous-complete')
            with mock.patch.object(writer,'MAX_TOTAL',2000):
                w=writer.Writer(args)
                try:
                    with self.assertRaisesRegex(ValueError,r'total limit: accepted=.*next=.*limit=2000'):
                        w.append(dict(op='record',seq=1,kind='local',t=1.,data={'large':'a'*3000}))
                finally:w.abort()
            self.assertEqual(b'previous-complete',path.read_bytes())
            self.assertTrue(Path(w.temp).exists())
            self.assertEqual(0,w.count)

    def test_row_limit_still_rejects_oversized_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            w=writer.Writer(start(directory))
            try:
                with self.assertRaisesRegex(ValueError,'replay row limit'):
                    w.append(dict(op='record',seq=1,kind='local',t=1.,data={'large':'a'*writer.MAX_LINE}))
            finally:w.abort()
            self.assertFalse(Path(w.path).exists())

    def test_reader_digest_is_updated_for_packaged_helper(self):
        digest=hashlib.sha256((ROOT/'tools/replay/replay_reader_process.py').read_bytes()).hexdigest()
        self.assertIn("DIGEST='"+digest+"'",(CLIENT/'replay_reader.py').read_text())
        validator=module('capacity_validator',ROOT/'tools/validate_wotmod.py')
        self.assertEqual(digest, validator.REPLAY_RESOURCES[validator.REPLAY_READER])
        process=module('capacity_process',CLIENT/'replay_process.py')
        self.assertEqual(process.RUNTIME_DIGEST,
            validator.REPLAY_RESOURCES['res/offline_replay/recorder-runtime.zip'])

if __name__=='__main__':unittest.main()
