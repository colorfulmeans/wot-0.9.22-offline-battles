"""Disposable defaults replace once; custom saves never participate."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import save_slots


class DefaultRevisionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'saves'
        self.default = self.root / 'default'
        self.default.mkdir(parents=True)

    def test_corrupt_default_is_replaced_without_backup_and_only_once(self):
        (self.default/'save.json').write_text('{broken')
        (self.default/'garage_state.json').write_text('old')
        (self.default/'old-backup.zip').write_bytes(b'old')
        custom = self.root/'custom'; custom.mkdir()
        (custom/'garage_state.json').write_text('keep')
        self.assertTrue(save_slots.replace_default(root=str(self.root)))
        self.assertEqual(['save.json'], [p.name for p in self.default.iterdir()])
        (self.default/'garage_state.json').write_text('edited')
        self.assertFalse(save_slots.replace_default(root=str(self.root)))
        self.assertEqual('edited', (self.default/'garage_state.json').read_text())
        self.assertEqual('keep', (custom/'garage_state.json').read_text())

    def test_failed_metadata_write_is_retryable(self):
        with mock.patch.object(save_slots, '_write_metadata', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                save_slots.replace_default(root=str(self.root))
        self.assertTrue(save_slots.replace_default(root=str(self.root)))

    def test_default_recovery_rebuilds_new_seed_without_recovery_folder(self):
        save_slots.replace_default(root=str(self.root))
        (self.default/'garage_state.json').write_text('modified')
        result = save_slots.initialize_slot('default', root=str(self.root), is_running=lambda:False)
        self.assertIsNone(result['backup'])
        self.assertIsNone(result['recovery'])
        metadata = json.loads((self.default/'save.json').read_text())
        self.assertEqual(save_slots.DEFAULT_REVISION, metadata['default_revision'])
        self.assertTrue(metadata['skip_legacy_import'])
        self.assertEqual('unlocked', metadata['mode'])

    def test_rename_does_not_rearm_migration(self):
        save_slots.replace_default(root=str(self.root))
        save_slots.rename_slot('default','My defaults',root=str(self.root))
        self.assertFalse(save_slots.replace_default(root=str(self.root)))

    def test_installer_and_repair_seed_use_the_same_revision(self):
        import core
        with mock.patch.object(save_slots, 'saves_root', return_value=str(self.root)), \
             mock.patch.object(core, 'game_is_running', return_value=False):
            self.assertTrue(core._upgrade_default_save('unused-game-root'))
            (self.default/'garage_state.json').write_text('later edits')
            self.assertEqual([], core._upgrade_default_save('unused-game-root'))
            self.assertEqual('later edits', (self.default/'garage_state.json').read_text())
            core._fresh_default_save('unused-game-root')
            self.assertFalse((self.default/'garage_state.json').exists())
            self.assertEqual([], core._upgrade_default_save('unused-game-root'))
