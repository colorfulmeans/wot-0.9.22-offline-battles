"""Sound receipts are opt-in, bounded, observational and removable."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import sound_diagnostics as sound


class SoundDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        sound.remove();self.addCleanup(sound.remove)
        self.calls=[];self.result=object()
        calls=self.calls;result=self.result
        class Groups:
            def playSound2D(self,*args,**kwargs):
                calls.append((self,args,kwargs));return result
        self.groups=Groups
        self.native=mock.Mock(return_value=result)
        self.modules=mock.patch.dict(sys.modules,SoundGroups=SimpleNamespace(SoundGroups=Groups),
                                    WWISE=SimpleNamespace(WW_eventGlobal=self.native))
        self.modules.start();self.addCleanup(self.modules.stop)
        self.enabled=mock.patch.object(sound,'detailed_enabled',return_value=True).start()
        self.addCleanup(mock.patch.stopall)
        self.records=[]
        mock.patch.object(sound,'_emit',side_effect=self.records.append).start()

    def test_normal_entrance_does_not_install_wrappers(self):
        self.enabled.return_value=False;original=self.groups.playSound2D
        self.assertEqual(0,sound.install());self.assertIs(original,self.groups.playSound2D)

    def test_identity_arguments_and_native_return_are_preserved(self):
        sound.install();instance=self.groups();value=object()
        self.assertIs(self.result,instance.playSound2D('event',value,volume=.4))
        self.assertEqual([(instance,('event',value),{'volume':.4})],self.calls)
        begin=next(r for r in self.records if r['stage']=='begin')
        self.assertEqual('event',begin['args'][0]);self.assertTrue(begin['caller'])
        self.assertIs(self.result,sys.modules['WWISE'].WW_eventGlobal(2967843034))
        self.native.assert_called_once_with(2967843034)

    def test_native_exception_is_not_swallowed_or_replaced(self):
        self.native.side_effect=ValueError('native sound refusal');sound.install()
        with self.assertRaisesRegex(ValueError,'native sound refusal'):
            sys.modules['WWISE'].WW_eventGlobal('bad_event')
        self.assertEqual('raised',self.records[-1]['stage'])

    def test_unsigned_resource_identifier_remains_numeric(self):
        self.assertEqual(2967843034,sound._scalar(2967843034))

    def test_diagnostic_failure_cannot_prevent_audio(self):
        sound.install()
        with mock.patch.object(sound.traceback,'extract_stack',side_effect=RuntimeError('diagnostic only')):
            self.assertIs(self.result,self.groups().playSound2D('event'))
        self.assertEqual(1,len(self.calls))

    def test_distinct_call_cap_and_repeated_requests_do_not_grow_output(self):
        sound.install();instance=self.groups()
        for unused in range(30):instance.playSound2D('same')
        self.assertEqual(1,len(sound._SEEN))
        for n in range(sound.MAX_CALLS+50):instance.playSound2D('event_%d'%n)
        self.assertEqual(sound.MAX_CALLS,len(sound._SEEN))
        self.assertGreaterEqual(sum(r['stage']=='begin' for r in self.records),sound.MAX_CALLS)
        self.assertLessEqual(sum(r['stage']=='begin' for r in self.records),sound.MAX_CALLS+6)
        self.assertEqual(30+sound.MAX_CALLS+50,len(self.calls))

    def test_idempotent_install_and_remove_restores_original(self):
        original=self.groups.playSound2D;sound.install();wrapped=self.groups.playSound2D
        sound.install();self.assertIs(wrapped,self.groups.playSound2D)
        sound.remove();self.assertIs(original,self.groups.playSound2D)
        sound.remove()

    def test_error_context_preserves_partial_writes_and_recent_event_ids(self):
        import io,json
        target=io.StringIO();stream=sound._ErrorStream(target)
        sound.install();self.groups().playSound2D('gun_damaged')
        stream.write('[SOUND_ERROR] Sound fail: 2967843034 - ')
        stream.write('ErrorCode: 15\n')
        record=json.loads(target.getvalue().split('SOUND CALL ')[1])
        self.assertEqual('native_error',record['stage'])
        self.assertEqual('gun_damaged',record['recent'][-1]['event_ids'][0]['name'])
        self.assertEqual(1544767705,sound.event_id('GUN_DAMAGED'))

    def test_returned_sound_keeps_identity_and_observes_play_and_stop(self):
        class PySound:
            def play(self):return 17
            def stop(self):return 18
        value=PySound();self.native.return_value=value;sound.install()
        self.assertIs(value,sys.modules['WWISE'].WW_eventGlobal('event'))
        self.assertEqual(17,value.play());self.assertEqual(18,value.stop())
        calls=[r for r in self.records if r['stage']=='begin']
        self.assertEqual(id(value),calls[-1]['receiver'])
        self.assertEqual('PySound.stop',calls[-1]['method'])

    def test_errors_and_playback_continue_after_first_distinct_budget(self):
        sound.install();instance=self.groups()
        for n in range(sound.MAX_CALLS*2):instance.playSound2D(str(n))
        self.assertTrue(any(r.get('call',0)>sound.MAX_CALLS for r in self.records))
        self.assertEqual(64,len(sound._RECENT))


if __name__=='__main__':unittest.main()
